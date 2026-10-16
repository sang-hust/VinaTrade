"""Claude integration: headline rewrite, stock conclusion, assistant chat with read-only data tools, weekly coach.
Every number the model may quote comes from our database via tools; the model never invents figures (spec 3.8)."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from datetime import date, timedelta

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.vntime import today_vn
from app.engines.scoring import RATING_VI
from app.models import (
    AiMessage,
    FinancialRatio,
    FinancialStatement,
    MarketRegime,
    Portfolio,
    PriceDaily,
    RallyStat,
    SectorScore,
    Signal,
    Stock,
    StockSnapshot,
    User,
)

log = logging.getLogger(__name__)

DISCLAIMER = "Thông tin chỉ mang tính tham khảo, không phải lời khuyên mua bán. Bạn tự chịu trách nhiệm với quyết định đầu tư."

SYSTEM = """Bạn là trợ lý phân tích của Vinatrade, ứng dụng phân tích cổ phiếu Việt Nam. Trả lời bằng tiếng Việt, ngắn gọn, như một người môi giới tử tế: kết luận trước, số liệu chứng minh sau.

Quy tắc bắt buộc:
- Mọi con số (giá, điểm, chỉ số, tỷ lệ) phải lấy từ công cụ dữ liệu. Không tự nghĩ ra số liệu. Nếu công cụ không có dữ liệu, nói rõ là thiếu.
- Giá ghi đủ đồng với dấu chấm hàng nghìn (ví dụ 128.500 đồng), % có dấu +/−, chỉ số 2 số lẻ với dấu phẩy.
- Tên khuyến nghị: Mua mạnh (≥80), Tích lũy (65–79), Nắm giữ (50–64), Giảm tỷ trọng (35–49), Bán (<35).
- Luôn nhắc rủi ro khi điểm rủi ro doanh nghiệp ≥ 60, khi thị trường đang giảm, hoặc khi mã đang mua đuổi.
- Không đưa ra lời mời mua/bán; dùng cách nói "theo hệ thống, mã X đang ở mức Tích lũy...".
- Câu hỏi ngoài phạm vi chứng khoán / đầu tư: từ chối lịch sự trong một câu.
- Kết thúc bằng câu miễn trừ: "Thông tin chỉ mang tính tham khảo, không phải lời khuyên mua bán."
Định dạng: tối đa khoảng 180 từ, dùng gạch đầu dòng khi liệt kê, không dùng tiêu đề markdown."""


def available() -> bool:
    return bool(settings.anthropic_api_key)


def _client():
    import anthropic

    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=2, timeout=60)


def _numbers(s: str) -> list[str]:
    return re.findall(r"\d+(?:[.,]\d+)?", s or "")


async def rewrite_headline(draft: str, facts: dict) -> str:
    """Rewrite the rule-based market headline to ≤160 chars, keeping every number (spec 4.6n). Falls back to draft."""
    if not available():
        return draft
    try:
        c = _client()
        r = await c.messages.create(
            model=settings.ai_model,
            max_tokens=200,
            output_config={"effort": "low"},
            system="Bạn viết lại một câu kết luận thị trường chứng khoán Việt Nam cho người mới, tiếng Việt, tối đa 160 ký tự, giữ nguyên mọi con số, không dùng các từ 'chắc chắn', 'cam kết', không thêm số liệu mới. Chỉ trả về đúng một câu.",
            messages=[{"role": "user", "content": f"Câu gốc: {draft}\nSố liệu: {json.dumps(facts, ensure_ascii=False)}"}],
        )
        text = "".join(b.text for b in r.content if b.type == "text").strip().strip('"')
        if not text or len(text) > 170 or sorted(_numbers(text)) != sorted(_numbers(draft)):
            return draft
        return text
    except Exception as e:  # noqa: BLE001
        log.warning("headline rewrite failed: %s", e)
        return draft


def rule_conclusion(snap: dict, horizon: str = "MID") -> str:
    """Deterministic one-line conclusion for the recommendation card (used when AI is off or as the draft)."""
    rating = snap.get(f"rating_{horizon.lower()}") or snap.get("rating")
    score = snap.get(f"score_{horizon.lower()}")
    vi = RATING_VI.get(rating, "Chưa đủ dữ liệu")
    trend = {"STRONG_UP": "xu hướng tăng mạnh", "UP": "xu hướng tăng", "FLAT": "đi ngang", "DOWN": "xu hướng giảm", "STRONG_DOWN": "xu hướng giảm mạnh"}.get(snap.get("trend_state"), "chưa rõ xu hướng")
    parts = [f"{vi} ({score:.0f}/100)" if score is not None else vi, trend]
    if snap.get("is_chase"):
        parts.append("giá đã tăng xa điểm phá nền, không mua đuổi")
    elif snap.get("base_status") == "BROKEN_OUT" and (snap.get("gain_from_base_pct") or 0) <= 5:
        parts.append("vừa phá nền, còn gần điểm mua")
    elif snap.get("base_status") == "FORMING":
        parts.append("đang đi nền")
    if (snap.get("risk_score") or 0) >= 60:
        parts.append("rủi ro doanh nghiệp cao")
    return ", ".join(parts).capitalize() + "."


async def explain_stocks(items: list[dict]) -> dict[str, str]:
    """Batch: for each {symbol, facts, reasons} produce a 1–2 sentence Vietnamese conclusion. Returns {symbol: text}."""
    if not available() or not items:
        return {}
    out: dict[str, str] = {}
    c = _client()
    for i in range(0, len(items), 12):
        chunk = items[i : i + 12]
        prompt = "Với mỗi mã dưới đây, viết 1–2 câu kết luận tiếng Việt cho nhà đầu tư cá nhân (tối đa 45 từ), chỉ dùng số liệu đã cho, nêu điểm mạnh chính và một điểm cần lưu ý. Trả về JSON {\"MÃ\": \"câu\"}.\n\n"
        prompt += json.dumps(chunk, ensure_ascii=False, default=str)
        try:
            r = await c.messages.create(model=settings.ai_model, max_tokens=2000, output_config={"effort": "low"},
                                        system="Bạn là chuyên viên phân tích chứng khoán Việt Nam, viết ngắn gọn, không bịa số liệu. Chỉ trả về JSON hợp lệ.",
                                        messages=[{"role": "user", "content": prompt}])
            text = "".join(b.text for b in r.content if b.type == "text")
            m = re.search(r"\{.*\}", text, re.S)
            if m:
                out.update({k: str(v)[:300] for k, v in json.loads(m.group(0)).items()})
        except Exception as e:  # noqa: BLE001
            log.warning("explain_stocks failed: %s", e)
    return out


# ------------------------------------------------------------------ assistant tools (read-only)
def _fmt_row(obj, cols: list[str]) -> dict:
    out = {}
    for k in cols:
        v = getattr(obj, k, None)
        if isinstance(v, float):
            v = round(v, 2)
        if isinstance(v, date):
            v = v.isoformat()
        out[k] = v
    return out


SNAP_COLS = ["symbol", "trade_date", "exchange", "industry_code", "price", "change", "change_pct", "volume", "vol_ratio", "value_ma20", "ma10", "ma20", "ma50", "ma200",
             "rsi14", "macd", "adx14", "atr14", "rs_rating", "trend_state", "support_1", "resistance_1", "dist_ma50_pct", "high_52w", "low_52w", "pe", "pb", "peg",
             "market_cap", "fair_value", "margin_of_safety", "dividend_yield", "roe", "roa", "net_margin", "debt_to_equity", "revenue_yoy", "profit_yoy",
             "score_short", "score_mid", "score_long", "rating_short", "rating_mid", "rating_long", "trend_short", "trend_mid", "trend_long", "base_status",
             "base_length_days", "gain_from_base_pct", "risk_score", "risk_level", "is_chase", "entry_low", "entry_high", "stop_loss", "take_profit_1", "signals_today",
             "foreign_net_today", "foreign_net_5d", "foreign_net_20d", "prop_net_5d", "insider_net_90d", "insider_pending_sell", "consensus_target",
             "consensus_upside_pct", "consensus_count", "news_sentiment_7d", "news_count_7d", "next_event", "earnings_in_days"]

TOOLS = [
    {"name": "get_stock_snapshot", "description": "Số liệu mới nhất của một mã: giá, chỉ báo, định giá, cơ bản, điểm 3 khung, khuyến nghị, kế hoạch mua bán, rủi ro.",
     "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "get_price_history", "description": "Giá đóng cửa và khối lượng N phiên gần nhất của một mã (tối đa 60).",
     "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "days": {"type": "integer", "default": 20}}, "required": ["symbol"]}},
    {"name": "get_financials", "description": "Báo cáo tài chính 8 quý gần nhất (doanh thu, LNST, EPS, tổng tài sản, vốn chủ, nợ vay, dòng tiền KD) và chỉ số TTM.",
     "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "get_signals", "description": "Tín hiệu hệ thống gần đây (của một mã hoặc toàn thị trường hôm nay).",
     "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "limit": {"type": "integer", "default": 10}}}},
    {"name": "get_rally_stats", "description": "Thống kê các đợt tăng giá lịch sử của mã (số đợt, mức tăng trung vị, số phiên).",
     "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "get_sector_ranking", "description": "Xếp hạng ngành theo điểm và hiệu suất 1 tuần / 1 tháng / 3 tháng.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_market_regime", "description": "Trạng thái thị trường chung hôm nay: VN-Index, độ rộng, tỷ trọng cổ phiếu tối đa, câu kết luận.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_user_portfolio", "description": "Danh mục của chính người hỏi: vị thế, lãi/lỗ, tỷ trọng, cắt lỗ, cầu dao.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "run_screener", "description": "Chạy bộ lọc với điều kiện DSL {all:[{field,op,value}]} trên toàn thị trường, trả tối đa 15 mã điểm cao nhất. Trường hỗ trợ: price, change_pct, vol_ratio, value_ma20, ma50, ma200, rsi14, trend_state, dist_ma50_pct, pe, pb, roe, profit_yoy, score_short/mid/long, rating, base_status, risk_score, industry_code, exchange, gain_from_base_pct.",
     "input_schema": {"type": "object", "properties": {"conditions": {"type": "object"}, "horizon": {"type": "string", "enum": ["SHORT", "MID", "LONG"]}}, "required": ["conditions"]}},
    {"name": "get_news", "description": "Tin tức gần đây (tiêu đề, tóm tắt, nguồn, giờ, cảm xúc −1..1). Truyền symbol để lấy tin của một mã, bỏ trống để lấy tin thị trường.",
     "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "limit": {"type": "integer", "default": 8}}}},
    {"name": "get_insiders", "description": "Giao dịch nội bộ của lãnh đạo, cổ đông lớn, người liên quan (đăng ký và kết quả) của một mã.",
     "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "get_flows", "description": "Khối ngoại và tự doanh mua/bán ròng theo ngày của một mã (20 phiên); bỏ trống symbol để lấy toàn thị trường và top mua/bán ròng.",
     "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}}},
    {"name": "get_events", "description": "Sự kiện quyền sắp tới và gần đây của một mã: cổ tức, phát hành thêm, ĐHCĐ, diện cảnh báo/kiểm soát.",
     "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "get_recommendations", "description": "Khuyến nghị và giá mục tiêu của các công ty chứng khoán cho một mã, kèm giá mục tiêu trung bình.",
     "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "search_stocks", "description": "Tìm mã theo tên công ty hoặc ngành.", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
]


async def run_tool(db: AsyncSession, user: User, name: str, args: dict) -> dict | list:
    sym = (args.get("symbol") or "").upper()
    if name == "get_stock_snapshot":
        s = await db.get(StockSnapshot, sym)
        st = await db.get(Stock, sym)
        if not s:
            return {"error": f"Không có dữ liệu cho {sym}"}
        d = _fmt_row(s, SNAP_COLS)
        d["name"] = st.name_vi if st else None
        d["rating_vi"] = RATING_VI.get(s.rating)
        return d
    if name == "get_price_history":
        n = min(int(args.get("days") or 20), 60)
        rows = (await db.execute(select(PriceDaily).where(PriceDaily.symbol == sym).order_by(desc(PriceDaily.trade_date)).limit(n))).scalars().all()
        return [{"date": r.trade_date.isoformat(), "close": r.close, "volume": r.volume} for r in reversed(rows)]
    if name == "get_financials":
        rows = (await db.execute(select(FinancialStatement).where(FinancialStatement.symbol == sym, FinancialStatement.quarter <= 4)
                                 .order_by(desc(FinancialStatement.year), desc(FinancialStatement.quarter)).limit(8))).scalars().all()
        ratio = await db.get(FinancialRatio, sym)
        return {"quarters": [_fmt_row(r, ["year", "quarter", "revenue", "net_profit", "eps", "total_assets", "equity", "short_debt", "long_debt", "cfo"]) for r in rows],
                "ratios": _fmt_row(ratio, ["eps_ttm", "bvps", "pe", "pb", "roe", "roa", "net_margin", "debt_to_equity", "current_ratio", "revenue_yoy", "profit_yoy", "cfo_to_profit", "fair_value", "margin_of_safety"]) if ratio else None}
    if name == "get_signals":
        q = select(Signal).order_by(desc(Signal.trade_date), desc(Signal.score)).limit(min(int(args.get("limit") or 10), 30))
        q = q.where(Signal.symbol == sym) if sym else q.where(Signal.trade_date >= today_vn() - timedelta(days=4))
        rows = (await db.execute(q)).scalars().all()
        return [_fmt_row(r, ["symbol", "trade_date", "strategy_code", "signal_type", "horizon", "rating", "score", "price", "stop_loss", "take_profit_1", "title", "reliability_pct", "stand_aside", "is_chase"]) for r in rows]
    if name == "get_rally_stats":
        r = await db.get(RallyStat, sym)
        return _fmt_row(r, ["rally_count", "median_gain_pct", "p75_gain_pct", "median_days", "median_peak_vol_ratio", "median_pullback_pct"]) if r else {"rally_count": 0}
    if name == "get_sector_ranking":
        last = await db.scalar(select(func.max(SectorScore.trade_date)))
        rows = (await db.execute(select(SectorScore).where(SectorScore.trade_date == last).order_by(desc(SectorScore.score)))).scalars().all()
        from app.ingestion.icb import ICB_LV2
        return [{"industry_code": r.industry_code, "name": ICB_LV2.get(r.industry_code, ("?",))[0], "score": r.score, "perf_1w": r.perf_1w, "perf_1m": r.perf_1m, "perf_3m": r.perf_3m, "leaders": r.leaders} for r in rows]
    if name == "get_market_regime":
        r = (await db.execute(select(MarketRegime).order_by(desc(MarketRegime.trade_date)).limit(1))).scalar_one_or_none()
        return _fmt_row(r, ["trade_date", "regime", "max_equity_pct", "vnindex", "vnindex_change_pct", "pct_above_ma50", "advances", "declines", "headline"]) if r else {}
    if name == "get_user_portfolio":
        from app.services.portfolio import portfolio_view
        from app.models import RiskGuardStatus
        pfs = (await db.execute(select(Portfolio).where(Portfolio.user_id == user.id))).scalars().all()
        g = await db.get(RiskGuardStatus, user.id)
        out = {"guard_mode": g.mode if g else "NORMAL", "portfolios": []}
        for pf in pfs:
            v = await portfolio_view(db, pf)
            out["portfolios"].append({"name": pf.name, "is_paper": pf.is_paper, "nav": round(v["nav"]), "cash": round(v["cash"]), "unrealized_pnl": round(v["unrealized_pnl"]),
                                      "positions": [{"symbol": p.symbol, "quantity": p.quantity, "avg_cost": round(p.avg_cost), "price": p.price, "pnl_pct": round(p.pnl_pct, 2), "weight_pct": round(p.weight_pct, 1), "stop_loss": p.stop_loss, "rating": p.rating} for p in v["positions"]]})
        return out
    if name == "run_screener":
        from app.screener.dsl import DslError, to_sql, validate
        cond = args.get("conditions") or {}
        try:
            validate(cond)
            hz = (args.get("horizon") or "MID").upper()
            col = {"SHORT": StockSnapshot.score_short, "LONG": StockSnapshot.score_long}.get(hz, StockSnapshot.score_mid)
            rows = (await db.execute(select(StockSnapshot).where(to_sql(cond)).order_by(desc(col)).limit(15))).scalars().all()
            return [_fmt_row(r, ["symbol", "price", "change_pct", "score_mid", "rating", "rsi14", "dist_ma50_pct", "pe", "roe", "risk_score"]) for r in rows]
        except DslError as e:
            return {"error": str(e)}
    if name in ("get_news", "get_insiders", "get_flows", "get_events", "get_recommendations"):
        from app.api.v1 import insights

        if name == "get_news":
            n = min(int(args.get("limit") or 8), 20)
            if sym:
                return (await insights.stock_news(sym, user, db, limit=n))["items"]
            return (await insights.news(user, db, market=True, page=1, size=n))["items"]
        if name == "get_insiders":
            r = await insights.stock_insiders(sym, user, db, limit=15)
            return {"net_90d_vnd": r["net_90d"], "pending_sell_shares": r["pending_sell_shares"],
                    "items": [{k: i[k] for k in ("person", "relation", "side_vi", "status_vi", "quantity", "quantity_done", "announce_date", "start_date", "end_date", "value_est")} for i in r["items"]]}
        if name == "get_flows":
            if sym:
                r = await insights.stock_flows(sym, user, db, days=20)
                return {k: r[k] for k in ("foreign_net_today", "foreign_net_5d", "foreign_net_20d", "prop_net_5d", "foreign_room_pct")} | {"series": r["series"][-10:]}
            r = await insights.market_flows(user, db, top=8)
            return {k: r[k] for k in ("date", "foreign_net", "prop_net", "top_buy", "top_sell")}
        if name == "get_events":
            r = await insights.stock_events(sym, user, db, limit=15)
            return {"upcoming": r["upcoming"][:5], "recent": r["recent"][:6], "alerts": r["alerts"][:3]}
        r = await insights.stock_recommendations(sym, user, db, limit=10)
        return {k: r[k] for k in ("consensus_target", "consensus_upside_pct", "consensus_count")} | {"items": r["items"][:8]}
    if name == "search_stocks":
        q = f"%{args.get('query', '')}%"
        rows = (await db.execute(select(Stock).where(Stock.is_active, (Stock.name_vi.ilike(q)) | (Stock.symbol.ilike(q))).limit(10))).scalars().all()
        return [{"symbol": r.symbol, "name": r.name_vi, "exchange": r.exchange, "industry_code": r.industry_code} for r in rows]
    return {"error": "unknown tool"}


async def daily_usage(db: AsyncSession, user: User) -> int:
    from app.models import AiConversation
    start = today_vn()
    return await db.scalar(select(func.count(AiMessage.id)).join(AiConversation, AiConversation.id == AiMessage.conversation_id)
                           .where(AiConversation.user_id == user.id, AiMessage.role == "user", AiMessage.created_at >= start)) or 0


async def chat_stream(db: AsyncSession, user: User, history: list[dict], context: dict | None) -> AsyncIterator[dict]:
    """Yields {"type": "text", "delta"} | {"type": "card", "data"} | {"type": "done", "text", "tool_calls", "usage"}."""
    if not available():
        yield {"type": "text", "delta": "Trợ lý AI chưa được cấu hình (thiếu khóa API). " + DISCLAIMER}
        yield {"type": "done", "text": "", "tool_calls": [], "usage": {}}
        return

    c = _client()
    ctx = ""
    if context:
        ctx = "\nNgữ cảnh người dùng đang xem: " + json.dumps(context, ensure_ascii=False)
    messages = list(history)
    tool_calls: list[dict] = []
    cards: list[dict] = []
    full_text = ""
    usage = {"input": 0, "output": 0}
    for _round in range(6):
        async with c.messages.stream(model=settings.ai_model, max_tokens=1500, output_config={"effort": "low"},
                                     system=[{"type": "text", "text": SYSTEM + ctx, "cache_control": {"type": "ephemeral"}}],
                                     tools=TOOLS, messages=messages) as stream:
            async for event in stream:
                if event.type == "content_block_delta" and getattr(event.delta, "type", "") == "text_delta":
                    full_text += event.delta.text
                    yield {"type": "text", "delta": event.delta.text}
            final = await stream.get_final_message()
        usage["input"] += final.usage.input_tokens
        usage["output"] += final.usage.output_tokens
        if final.stop_reason == "refusal":
            yield {"type": "text", "delta": "Tôi không thể trả lời câu hỏi này. " + DISCLAIMER}
            break
        tool_uses = [b for b in final.content if b.type == "tool_use"]
        if final.stop_reason != "tool_use" or not tool_uses:
            break
        messages.append({"role": "assistant", "content": [b.model_dump() for b in final.content if b.type in ("text", "tool_use")]})
        results = []
        for tu in tool_uses:
            try:
                res = await run_tool(db, user, tu.name, tu.input if isinstance(tu.input, dict) else json.loads(tu.input))
            except Exception as e:  # noqa: BLE001
                res = {"error": str(e)[:200]}
            tool_calls.append({"name": tu.name, "input": tu.input})
            if tu.name in ("get_stock_snapshot", "get_market_regime") and isinstance(res, dict) and not res.get("error"):
                card = {"kind": tu.name, "data": {k: res.get(k) for k in ("symbol", "name", "price", "change_pct", "score_mid", "rating_vi", "stop_loss", "entry_low", "entry_high", "take_profit_1", "risk_score", "regime", "vnindex", "headline") if k in res}}
                cards.append(card)
                yield {"type": "card", "data": card}
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": json.dumps(res, ensure_ascii=False, default=str)[:12000]})
        messages.append({"role": "user", "content": results})
    yield {"type": "done", "text": full_text, "tool_calls": tool_calls, "cards": cards, "usage": usage}


async def coach_summary(metrics: dict, insights: list[dict], rule: str) -> str:
    if not available():
        return "\n".join(i["text"] for i in insights) + ("\n\nQuy tắc gợi ý tuần tới: " + rule if rule else "")
    try:
        c = _client()
        r = await c.messages.create(model=settings.ai_model, max_tokens=600, output_config={"effort": "low"},
                                    system="Bạn là huấn luyện viên giao dịch, viết tiếng Việt, thẳng thắn nhưng tôn trọng, chỉ diễn giải số liệu đã cho, không bịa thêm. Tối đa 120 từ, 3 gạch đầu dòng + 1 câu quy tắc.",
                                    messages=[{"role": "user", "content": json.dumps({"metrics": metrics, "insights": insights, "rule": rule}, ensure_ascii=False, default=str)}])
        return "".join(b.text for b in r.content if b.type == "text").strip()
    except Exception as e:  # noqa: BLE001
        log.warning("coach summary failed: %s", e)
        return "\n".join(i["text"] for i in insights)

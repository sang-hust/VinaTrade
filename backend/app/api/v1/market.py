from datetime import date, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import desc, func, or_, select

from app.api.deps import DB, CurrentUser
from app.api.presenters import REGIME_VI, clean, price_int, row, snapshot_item
from app.core.errors import not_found
from app.core.vntime import is_market_open, now_vn, session_state, today_vn
from app.engines.indicators import compute_indicators
from app.engines.scoring import RATING_VI
from app.ingestion.icb import ICB_LV2
from app.models import (
    CoachReport,
    CompanyRiskScore,
    CorporateAction,
    FinancialRatio,
    FinancialStatement,
    IndexDaily,
    MarketRegime,
    PriceBase,
    PriceDaily,
    Rally,
    RallyStat,
    SectorScore,
    Signal,
    SignalOutcome,
    SignalReliability,
    Stock,
    StockScore,
    StockSnapshot,
    Strategy,
    Watchlist,
    WatchlistItem,
)
from app.services.ai import DISCLAIMER, rule_conclusion
from app.services.sysconfig import get_config

router = APIRouter(tags=["market"])
HZ = {"SHORT": "Ngắn hạn", "MID": "Trung hạn", "LONG": "Dài hạn"}


def _session_label() -> str:
    st = session_state()
    now = now_vn()
    days = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
    label = {"PRE": "Trước giờ giao dịch", "ATO": "Phiên ATO", "CONTINUOUS": "Đang giao dịch", "LUNCH": "Nghỉ trưa", "ATC": "Phiên ATC", "CLOSED": "Đã đóng cửa", "HOLIDAY": "Nghỉ giao dịch"}[st]
    return f"{label} · {now.strftime('%H:%M')} {days[now.weekday()]} {now.strftime('%d/%m/%Y')}"


@router.get("/market/overview")
async def overview(user: CurrentUser, db: DB, horizon: str = "MID"):
    horizon = horizon.upper() if horizon.upper() in HZ else "MID"
    reg = (await db.execute(select(MarketRegime).order_by(desc(MarketRegime.trade_date)).limit(1))).scalar_one_or_none()
    indexes = []
    for code, label in (("VNINDEX", "VN-Index"), ("VN30", "VN30"), ("HNXINDEX", "HNX-Index"), ("UPCOMINDEX", "UPCoM")):
        rows = (await db.execute(select(IndexDaily).where(IndexDaily.index_code == code).order_by(desc(IndexDaily.trade_date)).limit(2))).scalars().all()
        if rows:
            last, prev = rows[0], (rows[1] if len(rows) > 1 else None)
            chg = (last.close - prev.close) if prev else 0.0
            indexes.append({"code": code, "label": label, "value": round(last.close, 2), "change": round(chg, 2), "change_pct": round(chg / prev.close * 100, 2) if prev and prev.close else 0.0,
                            "date": last.trade_date.isoformat(), "value_vnd": clean(last.value)})
    # today's signals, by horizon
    d = await db.scalar(select(func.max(Signal.trade_date)))
    sigs = (await db.execute(select(Signal).where(Signal.trade_date == d, Signal.horizon == horizon).order_by(desc(Signal.score)))).scalars().all() if d else []
    stocks = {s.symbol: s for s in (await db.execute(select(Stock).where(Stock.symbol.in_({x.symbol for x in sigs})))).scalars()} if sigs else {}
    snaps = {s.symbol: s for s in (await db.execute(select(StockSnapshot).where(StockSnapshot.symbol.in_({x.symbol for x in sigs})))).scalars()} if sigs else {}
    # least-risky first: rank by the snapshot's risk-adjusted score, then the signal score
    adj_col = f"score_adj_{horizon.lower()}"
    sigs.sort(key=lambda x: (-(getattr(snaps.get(x.symbol), adj_col, None) or 0), -(x.score or 0)))
    from app.services.risknumbers import numbers_for, ref_order_vnd

    ref_order = await ref_order_vnd(db, user)
    regime_now = reg.regime if reg else "UPTREND"
    rel_cache: dict = {}
    numbers = {s.id: await numbers_for(db, s.strategy_code, s.regime_at_signal or regime_now, s.horizon, s.price, s.stop_loss, ref_order, getattr(snaps.get(s.symbol), "value_ma20", None), rel_cache) for s in sigs}

    def sig_item(s: Signal) -> dict:
        sn = snaps.get(s.symbol)
        return {"id": s.id, "symbol": s.symbol, "name": (stocks[s.symbol].short_name or stocks[s.symbol].name_vi) if s.symbol in stocks else None, "price": price_int(s.price),
                "change_pct": clean(sn.change_pct) if sn else None, "score": clean(s.score), "rating": s.rating, "rating_vi": RATING_VI.get(s.rating), "signal_type": s.signal_type,
                "strategy_code": s.strategy_code, "title": s.title, "event": s.title.split("] ", 1)[-1].replace(f"{s.symbol} ", "", 1),
                "entry_low": price_int(s.entry_low), "entry_high": price_int(s.entry_high), "stop_loss": price_int(s.stop_loss), "take_profit_1": price_int(s.take_profit_1),
                "reliability_pct": clean(s.reliability_pct), "reliability_samples": s.reliability_samples, "stand_aside": s.stand_aside, "is_chase": s.is_chase,
                "risk_score": clean(s.risk_score), "risk_numbers": numbers.get(s.id), "risk_total": clean(sn.risk_total) if sn else None, "risk_total_level": sn.risk_total_level if sn else None,
                "risk_total_vi": RISK_VI_LBL.get(sn.risk_total_level) if sn else None, "score_adj": clean(getattr(sn, adj_col, None)) if sn else None, "trend3": "".join({"UP": "▲", "FLAT": "▬", "DOWN": "▼"}.get(getattr(sn, k, None) or "FLAT", "▬") for k in ("trend_short", "trend_mid", "trend_long")) if sn else None}

    buys = [sig_item(s) for s in sigs if s.signal_type == "BUY" and not s.stand_aside][:8]
    sells = [sig_item(s) for s in sigs if s.signal_type in ("SELL", "TAKE_PROFIT")][:8]
    watch = [sig_item(s) for s in sigs if s.signal_type == "WATCH"][:6]
    # sectors
    sd = await db.scalar(select(func.max(SectorScore.trade_date)))
    sectors = [{"code": r.industry_code, "name": ICB_LV2.get(r.industry_code, (r.industry_code,))[0], "score": clean(r.score), "perf_1w": clean(r.perf_1w), "perf_1m": clean(r.perf_1m),
                "perf_3m": clean(r.perf_3m), "money_flow": clean(r.money_flow), "breadth": clean(r.breadth), "leaders": r.leaders or [], "macro_note": r.macro_note}
               for r in (await db.execute(select(SectorScore).where(SectorScore.trade_date == sd).order_by(desc(SectorScore.score)))).scalars()] if sd else []
    # upcoming events (7 days)
    today = today_vn()
    from app.api.v1.insights import event_out, news_out
    from app.models import InvestorFlow, NewsArticle
    evd = func.coalesce(CorporateAction.ex_date, CorporateAction.event_date)
    events = [event_out(e) for e in (await db.execute(select(CorporateAction).where(evd.between(today, today + timedelta(days=7)),
                                                                                       CorporateAction.kind.in_(["CASH_DIVIDEND", "STOCK_DIVIDEND", "BONUS", "ISSUE", "AGM"]))
                                                       .join(StockSnapshot, StockSnapshot.symbol == CorporateAction.symbol).order_by(desc(StockSnapshot.value_ma20).nulls_last()).limit(12))).scalars()]
    events.sort(key=lambda e: e["date"] or "")
    fd = await db.scalar(select(func.max(InvestorFlow.trade_date)))
    flows = None
    if fd:
        t = (await db.execute(select(func.sum(InvestorFlow.foreign_net_val), func.sum(InvestorFlow.prop_net_val)).where(InvestorFlow.trade_date == fd))).one()
        flows = {"date": fd.isoformat(), "foreign_net": clean(t[0]), "prop_net": clean(t[1])}
    market_news = [news_out(a) for a in (await db.execute(select(NewsArticle).where(NewsArticle.is_market.is_(True)).order_by(desc(NewsArticle.published_at)).limit(8))).scalars()]
    coach = (await db.execute(select(CoachReport).where(CoachReport.user_id == user.id).order_by(desc(CoachReport.week_start)).limit(1))).scalar_one_or_none()
    # followed symbols with rating change today
    changed = []
    wl_syms = {s for (s,) in (await db.execute(select(WatchlistItem.symbol).join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id).where(Watchlist.user_id == user.id))).all()}
    if wl_syms:
        for sn in (await db.execute(select(StockSnapshot).where(StockSnapshot.symbol.in_(wl_syms), StockSnapshot.rating_changed.is_(True)))).scalars():
            changed.append({"symbol": sn.symbol, "from": RATING_VI.get(sn.prev_rating), "to": RATING_VI.get(sn.rating)})
    return {
        "date": reg.trade_date.isoformat() if reg else None,
        "session": _session_label(),
        "market_open": is_market_open(),
        "regime": reg.regime if reg else None,
        "regime_vi": REGIME_VI.get(reg.regime) if reg else None,
        "headline": reg.headline if reg else "Chưa có dữ liệu phiên gần nhất.",
        "max_equity_pct": reg.max_equity_pct if reg else None,
        "breadth": {"advances": reg.advances, "declines": reg.declines, "pct_above_ma50": clean(reg.pct_above_ma50), "pct_above_ma200": clean(reg.pct_above_ma200),
                    "distribution_days": reg.distribution_days, "liquidity_ratio": clean(reg.liquidity_ratio), "new_highs": reg.new_highs, "new_lows": reg.new_lows,
                    "foreign_net_5d": clean(reg.foreign_net_5d), "foreign_sell_streak": reg.foreign_sell_streak, "pressure_reasons": (reg.facts or {}).get("pressure_reasons", [])} if reg else None,
        "indexes": indexes,
        "horizon": horizon,
        "signals": {"buy": buys, "sell": sells, "watch": watch, "total": len(sigs)},
        "sectors": sectors,
        "events": events,
        "flows": flows,
        "news": market_news,
        "coach": {"week_start": coach.week_start.isoformat(), "insights": coach.insights, "rule": coach.rule, "benchmark": coach.benchmark} if coach else None,
        "rating_changes": changed,
        "disclaimer": DISCLAIMER,
    }


@router.get("/market/regime")
async def regime_history(user: CurrentUser, db: DB, days: int = 90):
    rows = (await db.execute(select(MarketRegime).where(MarketRegime.trade_date >= today_vn() - timedelta(days=days)).order_by(MarketRegime.trade_date))).scalars().all()
    return [row(r, ["trade_date", "regime", "max_equity_pct", "vnindex", "vnindex_change_pct", "pct_above_ma50", "advances", "declines", "headline"]) for r in rows]


@router.get("/market/indexes/{code}/candles")
async def index_candles(code: str, user: CurrentUser, db: DB, days: int = 250):
    rows = (await db.execute(select(IndexDaily).where(IndexDaily.index_code == code.upper()).order_by(desc(IndexDaily.trade_date)).limit(days))).scalars().all()
    return [{"t": r.trade_date.isoformat(), "o": clean(r.open), "h": clean(r.high), "l": clean(r.low), "c": clean(r.close), "v": r.volume} for r in reversed(rows)]


@router.get("/stocks")
async def search_stocks(user: CurrentUser, db: DB, q: str = "", exchange: str | None = None, industry: str | None = None, limit: int = 20):
    stmt = select(Stock, StockSnapshot).join(StockSnapshot, StockSnapshot.symbol == Stock.symbol, isouter=True).where(Stock.is_active)
    if q:
        qq = q.strip()
        stmt = stmt.where(or_(Stock.symbol.ilike(f"{qq}%"), Stock.name_vi.ilike(f"%{qq}%"), Stock.short_name.ilike(f"%{qq}%")))
    if exchange:
        stmt = stmt.where(Stock.exchange == exchange.upper())
    if industry:
        stmt = stmt.where(Stock.industry_code == industry)
    stmt = stmt.order_by(desc(StockSnapshot.value_ma20).nulls_last(), Stock.symbol).limit(min(limit, 100))
    out = []
    for st, sn in (await db.execute(stmt)).all():
        item = snapshot_item(sn, st) if sn else {"symbol": st.symbol, "name": st.short_name or st.name_vi, "exchange": st.exchange}
        item["industry"] = ICB_LV2.get(st.industry_code, ("",))[0] if st.industry_code else None
        out.append(item)
    return out


@router.get("/stocks/{symbol}")
async def stock_profile(symbol: str, user: CurrentUser, db: DB):
    st = await db.get(Stock, symbol.upper())
    if not st:
        raise not_found("Không có mã này")
    sn = await db.get(StockSnapshot, st.symbol)
    d = snapshot_item(sn, st) if sn else {"symbol": st.symbol, "name": st.short_name or st.name_vi}
    d.update({"industry": ICB_LV2.get(st.industry_code, ("",))[0] if st.industry_code else None, "listed_shares": st.listed_shares, "free_float_pct": st.free_float_pct,
              "foreign_pct": st.foreign_pct, "state_pct": st.state_pct, "listing_date": clean(st.listing_date), "profile": st.profile_vi, "is_bank": st.is_bank})
    wl = (await db.execute(select(Watchlist.id, Watchlist.name).join(WatchlistItem, WatchlistItem.watchlist_id == Watchlist.id).where(Watchlist.user_id == user.id, WatchlistItem.symbol == st.symbol))).all()
    d["watchlists"] = [{"id": str(i), "name": n} for i, n in wl]
    return d


@router.get("/stocks/{symbol}/candles")
async def candles(symbol: str, user: CurrentUser, db: DB, tf: str = "1d", days: int = Query(300, le=2000), indicators: bool = True):
    sym = symbol.upper()
    rows = (await db.execute(select(PriceDaily).where(PriceDaily.symbol == sym).order_by(desc(PriceDaily.trade_date)).limit(max(days, 260) + 210))).scalars().all()
    rows = list(reversed(rows))
    if not rows:
        raise not_found("Chưa có dữ liệu giá")
    import pandas as pd

    df = pd.DataFrame([{"trade_date": r.trade_date, "open": r.open, "high": r.high, "low": r.low, "close": r.close, "volume": r.volume, "value": r.value} for r in rows]).set_index("trade_date")
    if tf.lower() in ("1w", "w"):
        df = df.resample("W-FRI").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "value": "sum"}).dropna(subset=["close"])
    elif tf.lower() in ("1m", "m", "1mo"):
        df = df.resample("ME").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "value": "sum"}).dropna(subset=["close"])
    st = await db.get(Stock, sym)
    ind = compute_indicators(df, st.exchange if st else "HOSE") if indicators and len(df) >= 30 else None
    out = []
    for i, (d, r) in enumerate(df.iloc[-days:].iterrows()):
        item = {"t": d.date().isoformat() if hasattr(d, "date") else str(d), "o": price_int(r.open), "h": price_int(r.high), "l": price_int(r.low), "c": price_int(r.close), "v": int(r.volume)}
        if ind is not None:
            x = ind.loc[d]
            item.update({"ma20": clean(x.ma20), "ma50": clean(x.ma50), "ma200": clean(x.ma200), "rsi": clean(x.rsi14), "macd": clean(x.macd), "macd_s": clean(x.macd_signal), "macd_h": clean(x.macd_hist),
                         "adx": clean(x.adx14), "vol_ma20": clean(x.vol_ma20), "bb_u": clean(x.bb_upper), "bb_l": clean(x.bb_lower)})
        out.append(item)
    bases = [row(b, ["id", "start_date", "end_date", "base_high", "base_low", "length_days", "pattern", "status", "breakout_date"]) for b in (await db.execute(select(PriceBase).where(PriceBase.symbol == sym).order_by(desc(PriceBase.start_date)).limit(6))).scalars()]
    return {"symbol": sym, "tf": tf, "candles": out, "bases": bases}


RISK_VI_LBL = {"LOW": "Thấp", "MEDIUM": "Trung bình", "HIGH": "Cao"}


async def _total_risk_block(db, user, sym: str, sn: StockSnapshot, hz: str) -> dict | None:
    """Six-component total risk for the analysis screen. The correlation component is recomputed against the user's
    real holdings when they have any (snapshot stores the beta proxy)."""
    from app.engines.risk import combine_risk, correlation_component, risk_adjusted
    from app.models import Portfolio, Position
    from app.services.riskguard import _returns_frame

    if sn.risk_total is None or not sn.risk_components:
        return None
    comps = list(sn.risk_components)
    held = [p for (p,) in (await db.execute(select(Position.symbol).join(Portfolio, Portfolio.id == Position.portfolio_id)
                                             .where(Portfolio.user_id == user.id, Portfolio.is_paper.is_(False), Position.quantity > 0, Position.symbol != sym))).all()]
    personal = False
    if held:
        rets = await _returns_frame(db, [sym, *held])
        if not rets.empty and sym in rets.columns:
            corr = rets.corr()[sym].drop(sym, errors="ignore").dropna()
            if not corr.empty:
                top = corr.abs().idxmax()
                comps = [c if c["key"] != "correlation" else correlation_component(float(corr[top]), sn.beta_60, top) for c in comps]
                personal = True
    weights, params = await get_config(db, "risk.score_weights"), await get_config(db, "risk.score_params")
    res = combine_risk(comps, weights, params)
    score = getattr(sn, f"score_{hz.lower()}", None)
    return {**res, "level_vi": RISK_VI_LBL.get(res["level"]), "personalized": personal, "score_adj": risk_adjusted(score, res["score"]),
            "downgraded": res["score"] >= float((params or {}).get("downgrade_from", 60)),
            "text": f"Rủi ro {RISK_VI_LBL.get(res['level'], '').lower()} ({res['score']:.0f}/100). Xếp hạng theo cơ hội/rủi ro: {risk_adjusted(score, res['score']) or 0:.0f} điểm."}


@router.get("/stocks/{symbol}/analysis")
async def analysis(symbol: str, user: CurrentUser, db: DB, horizon: str | None = None):
    sym = symbol.upper()
    st = await db.get(Stock, sym)
    sn = await db.get(StockSnapshot, sym)
    if not st or not sn:
        raise not_found("Chưa có phân tích cho mã này")
    from app.models import UserSettings
    us = await db.get(UserSettings, user.id)
    hz = (horizon or (us.default_horizon if us else None) or "MID").upper()
    hz = hz if hz in HZ else "MID"
    sc = (await db.execute(select(StockScore).where(StockScore.symbol == sym).order_by(desc(StockScore.trade_date)).limit(1))).scalar_one_or_none()
    rk = await db.get(CompanyRiskScore, sym)
    rl = await db.get(RallyStat, sym)
    base = (await db.execute(select(PriceBase).where(PriceBase.symbol == sym).order_by(desc(PriceBase.start_date)).limit(1))).scalar_one_or_none()
    # reliability for the strategy of the latest BUY signal in this horizon
    last_sig = (await db.execute(select(Signal).where(Signal.symbol == sym, Signal.horizon == hz).order_by(desc(Signal.trade_date)).limit(1))).scalar_one_or_none()
    reg = (await db.execute(select(MarketRegime).order_by(desc(MarketRegime.trade_date)).limit(1))).scalar_one_or_none()
    rel = None
    if last_sig and reg:
        r = await db.get(SignalReliability, (last_sig.strategy_code, reg.regime, hz, 20))
        if r and r.samples >= 30:
            from app.engines.risk import risk_numbers as _rn
            from app.services.risknumbers import ref_order_vnd, rel_dict

            rel = {"win_rate": clean(r.win_rate), "samples": r.samples, "regime": reg.regime, "regime_vi": REGIME_VI.get(reg.regime), "strategy": last_sig.strategy_code,
                   "text": f"đúng {r.win_rate:.0f}% khi thị trường {REGIME_VI.get(reg.regime)} ({r.samples} lần)", "stand_aside": r.win_rate < 50,
                   "risk_numbers": _rn(rel_dict(r), sn.price, sn.stop_loss, await ref_order_vnd(db, user), sn.value_ma20)}
        else:
            rel = {"win_rate": None, "samples": r.samples if r else 0, "regime": reg.regime, "regime_vi": REGIME_VI.get(reg.regime), "strategy": last_sig.strategy_code,
                   "text": "chưa đủ 30 mẫu để đánh giá", "stand_aside": False}
    snap = snapshot_item(sn, st, hz)
    from app.api.v1.insights import event_out, insider_out, news_out
    from app.models import BrokerRecommendation, InsiderTransaction, NewsArticle, NewsStockLink
    extra_reasons, extra_draw = [], []
    v20 = (sn.value_ma20 or 0) * 5
    if sn.foreign_net_5d and v20 and sn.foreign_net_5d >= 0.1 * v20:
        extra_reasons.append({"code": "FOREIGN", "text": f"Khối ngoại mua ròng {sn.foreign_net_5d / 1e9:,.1f} tỷ đồng trong 5 phiên".replace(",", "X").replace(".", ",").replace("X", ".")})
    elif sn.foreign_net_5d and v20 and sn.foreign_net_5d <= -0.1 * v20:
        extra_draw.append({"code": "FOREIGN", "text": f"Khối ngoại bán ròng {abs(sn.foreign_net_5d) / 1e9:,.1f} tỷ đồng trong 5 phiên".replace(",", "X").replace(".", ",").replace("X", ".")})
    if sn.insider_net_90d and sn.insider_net_90d < -1e9:
        extra_draw.append({"code": "INSIDER", "text": f"Nội bộ bán ròng khoảng {abs(sn.insider_net_90d) / 1e9:,.1f} tỷ đồng trong 90 ngày".replace(",", "X").replace(".", ",").replace("X", ".")})
    elif sn.insider_net_90d and sn.insider_net_90d > 1e9:
        extra_reasons.append({"code": "INSIDER", "text": f"Nội bộ mua ròng khoảng {sn.insider_net_90d / 1e9:,.1f} tỷ đồng trong 90 ngày".replace(",", "X").replace(".", ",").replace("X", ".")})
    if sn.insider_pending_sell and sn.insider_pending_sell > 0:
        extra_draw.append({"code": "INSIDER_PENDING", "text": f"Nội bộ đang đăng ký bán {int(sn.insider_pending_sell):,} cổ phiếu".replace(",", ".")})
    if sn.consensus_upside_pct is not None and (sn.consensus_count or 0) >= 1:
        (extra_reasons if sn.consensus_upside_pct >= 15 else extra_draw if sn.consensus_upside_pct < 0 else []).append(
            {"code": "CONSENSUS", "text": f"Giá mục tiêu trung bình của {sn.consensus_count} CTCK {sn.consensus_upside_pct:+.0f}% so với giá hiện tại"})
    if sn.news_sentiment_7d is not None and (sn.news_count_7d or 0) >= 2:
        if sn.news_sentiment_7d >= 0.3:
            extra_reasons.append({"code": "NEWS", "text": f"Tin tức 7 ngày tích cực ({sn.news_count_7d} tin)"})
        elif sn.news_sentiment_7d <= -0.3:
            extra_draw.append({"code": "NEWS", "text": f"Tin tức 7 ngày tiêu cực ({sn.news_count_7d} tin)"})
    insiders = [insider_out(i, sn.price) for i in (await db.execute(select(InsiderTransaction).where(InsiderTransaction.symbol == sym)
                                                                   .order_by(desc(func.coalesce(InsiderTransaction.announce_date, InsiderTransaction.start_date))).limit(8))).scalars()]
    upcoming = [event_out(e) for e in (await db.execute(select(CorporateAction).where(CorporateAction.symbol == sym, CorporateAction.kind != "LISTED",
                                                                                     func.coalesce(CorporateAction.ex_date, CorporateAction.event_date) >= today_vn())
                                                       .order_by(func.coalesce(CorporateAction.ex_date, CorporateAction.event_date)).limit(5))).scalars()]
    stock_news = [news_out(a) for a in (await db.execute(select(NewsArticle).join(NewsStockLink, NewsStockLink.article_id == NewsArticle.id)
                                                        .where(NewsStockLink.symbol == sym).order_by(desc(NewsArticle.published_at)).limit(10))).scalars()]
    recs = [{"firm": r.firm, "rec_type": r.rec_type, "report_date": clean(r.report_date), "target_price": price_int(r.target_price)}
            for r in (await db.execute(select(BrokerRecommendation).where(BrokerRecommendation.symbol == sym).order_by(desc(BrokerRecommendation.report_date)).limit(6))).scalars()]
    reasons = list(sc.reasons or []) if sc else []
    ai_text = next((r["text"] for r in reasons if r.get("code") == "AI"), None)
    reasons = [r for r in reasons if r.get("code") != "AI"]
    conclusion = ai_text or rule_conclusion({**snap, "rating": sn.rating}, hz)
    # history of signals with outcomes
    hist = []
    sigs = (await db.execute(select(Signal).where(Signal.symbol == sym).order_by(desc(Signal.trade_date)).limit(25))).scalars().all()
    outcomes = {(o.signal_id, o.days): o for o in (await db.execute(select(SignalOutcome).where(SignalOutcome.signal_id.in_([s.id for s in sigs])))).scalars()} if sigs else {}
    wins = total = 0
    for s in sigs:
        o20 = outcomes.get((s.id, 20)) or outcomes.get((s.id, 10)) or outcomes.get((s.id, 5))
        res = o20.result if o20 else "OPEN"
        res_vi = {"TP_HIT": "Đạt chốt lời", "STOP_HIT": "Chạm cắt lỗ", "WIN": "Lãi", "LOSS": "Lỗ", "OPEN": "Đang theo dõi"}.get(res, res)
        if s.signal_type == "BUY" and o20:
            total += 1
            wins += 1 if res in ("TP_HIT", "WIN") else 0
        hist.append({"id": s.id, "date": s.trade_date.isoformat(), "type": s.signal_type, "strategy": s.strategy_code, "title": s.title, "rating": s.rating, "rating_vi": RATING_VI.get(s.rating),
                     "score": clean(s.score), "price": price_int(s.price), "result": res, "result_vi": res_vi, "return_pct": clean(o20.return_pct) if o20 else None})
    return {
        "symbol": sym, "name": st.short_name or st.name_vi, "name_full": st.name_vi, "exchange": st.exchange, "industry": ICB_LV2.get(st.industry_code, ("",))[0] if st.industry_code else None,
        "industry_code": st.industry_code, "in_vn30": st.in_vn30, "date": clean(sn.trade_date), "horizon": hz, "horizon_vi": HZ[hz],
        "price": snap["price"], "change": snap["change"], "change_pct": snap["change_pct"], "ref_price": snap["ref_price"], "ceiling": snap["ceiling"], "floor": snap["floor"],
        "volume": sn.volume, "value": clean(sn.value), "high_52w": snap["high_52w"], "low_52w": snap["low_52w"],
        "scores": {"SHORT": clean(sn.score_short), "MID": clean(sn.score_mid), "LONG": clean(sn.score_long)},
        "ratings": {"SHORT": sn.rating_short, "MID": sn.rating_mid, "LONG": sn.rating_long},
        "rating": snap["rating_hz"], "rating_vi": snap["rating_vi"], "score": snap["score"],
        "trend": {"SHORT": sn.trend_short, "MID": sn.trend_mid, "LONG": sn.trend_long}, "trend3": snap["trend3"], "trend_state": sn.trend_state,
        "conclusion": conclusion, "ai_conclusion": bool(ai_text),
        "plan": {"entry": [price_int(sn.entry_low), price_int(sn.entry_high)], "stop_loss": price_int(sn.stop_loss), "stop_loss_pct": round((sn.stop_loss / sn.price - 1) * 100, 1) if sn.stop_loss and sn.price else None,
                 "take_profit": [price_int(sn.take_profit_1), price_int(sc.take_profit_2) if sc else None], "risk_reward": clean(sc.risk_reward) if sc else None,
                 "price_vs_entry_pct": round((sn.price / sn.entry_high - 1) * 100, 1) if sn.entry_high and sn.price else None},
        "components": {"tech": clean(sc.tech), "tech_trend": clean(sc.tech_trend), "tech_momentum": clean(sc.tech_momentum), "tech_volume": clean(sc.tech_volume), "tech_rs": clean(sc.tech_rs),
                       "tech_pattern": clean(sc.tech_pattern), "fund": clean(sc.fund), "fund_growth": clean(sc.fund_growth), "fund_profitability": clean(sc.fund_profitability),
                       "fund_health": clean(sc.fund_health), "fund_valuation": clean(sc.fund_valuation), "sector": clean(sc.sector), "pattern_ai": clean(sc.pattern_ai)} if sc else None,
        "weights": (await get_config(db, "scoring.weights")).get(hz),
        "reliability": rel,
        "company_risk": {"score": clean(rk.score), "level": rk.level, "level_vi": {"LOW": "Thấp", "MEDIUM": "Trung bình", "HIGH": "Cao"}.get(rk.level), "flags": rk.flags or [],
                         "impact": "Hạ khuyến nghị một bậc" if rk.score >= 60 else None} if rk else None,
        "risk": await _total_risk_block(db, user, sym, sn, hz),
        "is_chase": sn.is_chase, "gain_from_base_pct": clean(sn.gain_from_base_pct),
        "base": row(base, ["start_date", "end_date", "base_high", "base_low", "depth_pct", "length_days", "tightness_pct", "pattern", "status", "breakout_date", "breakout_vol_ratio"]) if base else None,
        "rally_context": {"rally_count": rl.rally_count, "median_gain_pct": clean(rl.median_gain_pct), "p75_gain_pct": clean(rl.p75_gain_pct), "median_days": clean(rl.median_days),
                          "current_gain_pct": clean(sn.gain_from_base_pct), "pct_of_median": clean(sn.rally_gain_vs_median)} if rl else None,
        "indicators": {k: clean(getattr(sn, k)) for k in ("ma10", "ma20", "ma50", "ma200", "rsi14", "macd", "macd_signal", "macd_hist", "adx14", "atr14", "bb_upper", "bb_lower", "bb_width", "mfi14", "cmf20", "stoch_k", "vol_ratio", "value_ma20", "rs_rating", "support_1", "resistance_1", "dist_ma50_pct", "ceiling_streak")},
        "fundamentals": {k: clean(getattr(sn, k)) for k in ("pe", "pb", "ps", "peg", "market_cap", "fair_value", "margin_of_safety", "dividend_yield", "roe", "roa", "gross_margin", "net_margin", "debt_to_equity", "current_ratio", "revenue_yoy", "profit_yoy", "revenue_cagr_3y", "profit_cagr_3y", "cfo_to_profit")},
        "reasons": (reasons + extra_reasons)[:7], "drawbacks": (((sc.drawbacks or []) if sc else []) + extra_draw)[:5],
        "flows": {"foreign_net_today": clean(sn.foreign_net_today), "foreign_net_5d": clean(sn.foreign_net_5d), "foreign_net_20d": clean(sn.foreign_net_20d),
                  "prop_net_5d": clean(sn.prop_net_5d), "foreign_room_pct": clean(sn.foreign_room_pct)},
        "insiders": {"items": insiders, "net_90d": price_int(sn.insider_net_90d), "pending_sell_shares": int(sn.insider_pending_sell or 0)},
        "events": {"upcoming": upcoming, "next": sn.next_event},
        "consensus": {"target": price_int(sn.consensus_target), "upside_pct": clean(sn.consensus_upside_pct), "count": sn.consensus_count or 0, "items": recs},
        "news": {"items": stock_news, "sentiment_7d": clean(sn.news_sentiment_7d), "count_7d": sn.news_count_7d or 0},
        "signals_today": sn.signals_today or [], "history": hist, "history_summary": f"{wins}/{total} tín hiệu mua có lãi sau 20 phiên" if total else None,
        "regime": reg.regime if reg else None, "regime_vi": REGIME_VI.get(reg.regime) if reg else None,
        "status_flags": st.status_flags or [], "disclaimer": DISCLAIMER,
    }


@router.get("/stocks/{symbol}/financials")
async def financials(symbol: str, user: CurrentUser, db: DB, period: str = "Q"):
    sym = symbol.upper()
    q = select(FinancialStatement).where(FinancialStatement.symbol == sym)
    q = q.where(FinancialStatement.quarter <= 4) if period.upper() == "Q" else q.where(FinancialStatement.quarter == 5)
    rows = (await db.execute(q.order_by(desc(FinancialStatement.year), desc(FinancialStatement.quarter)).limit(12))).scalars().all()
    ratio = await db.get(FinancialRatio, sym)
    cols = ["year", "quarter", "public_date", "revenue", "gross_profit", "operating_profit", "pretax_profit", "net_profit", "eps", "total_assets", "total_liabilities", "equity", "short_debt", "long_debt", "cash", "receivables", "inventory", "cfo", "capex", "dividends_paid"]
    return {"symbol": sym, "period": period.upper(), "statements": [row(r, cols) for r in reversed(rows)],
            "ratios": row(ratio, ["as_of", "eps_ttm", "bvps", "pe", "pb", "ps", "peg", "roe", "roa", "gross_margin", "net_margin", "debt_to_equity", "current_ratio", "revenue_yoy", "profit_yoy", "revenue_cagr_3y", "profit_cagr_3y", "cfo_to_profit", "dividend_yield", "market_cap", "fair_value", "fair_value_pe", "fair_value_pb", "fair_value_graham", "margin_of_safety", "latest_year", "latest_quarter"]) if ratio else None}


@router.get("/stocks/{symbol}/valuation")
async def valuation(symbol: str, user: CurrentUser, db: DB):
    r = await db.get(FinancialRatio, symbol.upper())
    if not r:
        raise not_found("Chưa có định giá")
    sn = await db.get(StockSnapshot, symbol.upper())
    return {"symbol": symbol.upper(), "price": price_int(sn.price) if sn else None, "fair_value": price_int(r.fair_value), "fair_value_pe": price_int(r.fair_value_pe), "fair_value_pb": price_int(r.fair_value_pb),
            "fair_value_graham": price_int(r.fair_value_graham), "margin_of_safety": clean(r.margin_of_safety), "pe": clean(r.pe), "pb": clean(r.pb), "peg": clean(r.peg), "eps_ttm": clean(r.eps_ttm), "bvps": clean(r.bvps),
            "label": "Chiết khấu tốt" if (r.margin_of_safety or 0) >= 20 else ("Hợp lý" if (r.margin_of_safety or 0) >= -10 else "Định giá cao")}


@router.get("/stocks/{symbol}/bases")
async def bases(symbol: str, user: CurrentUser, db: DB):
    sym = symbol.upper()
    b = [row(x, ["id", "start_date", "end_date", "base_high", "base_low", "depth_pct", "length_days", "tightness_pct", "vol_dry_ratio", "pattern", "status", "breakout_date", "breakout_vol_ratio"])
         for x in (await db.execute(select(PriceBase).where(PriceBase.symbol == sym).order_by(desc(PriceBase.start_date)).limit(12))).scalars()]
    r = [row(x, ["id", "start_date", "peak_date", "end_date", "base_high", "peak_price", "gain_pct", "days_to_peak", "peak_vol_ratio", "distribution_days", "pullback_pct", "status"])
         for x in (await db.execute(select(Rally).where(Rally.symbol == sym).order_by(desc(Rally.start_date)).limit(12))).scalars()]
    st = await db.get(RallyStat, sym)
    return {"symbol": sym, "bases": b, "rallies": r, "stats": row(st, ["rally_count", "median_gain_pct", "p75_gain_pct", "mean_gain_pct", "median_days", "median_peak_vol_ratio", "median_pullback_pct"]) if st else None}


@router.get("/stocks/{symbol}/signals/history")
async def signal_history(symbol: str, user: CurrentUser, db: DB, limit: int = 30):
    sigs = (await db.execute(select(Signal).where(Signal.symbol == symbol.upper()).order_by(desc(Signal.trade_date)).limit(limit))).scalars().all()
    outcomes: dict = {}
    for o in (await db.execute(select(SignalOutcome).where(SignalOutcome.signal_id.in_([s.id for s in sigs])))).scalars() if sigs else []:
        outcomes.setdefault(o.signal_id, {})[o.days] = row(o, ["return_pct", "max_gain_pct", "max_loss_pct", "hit_tp1", "hit_stop", "result"])
    return [{**row(s, ["id", "trade_date", "strategy_code", "signal_type", "horizon", "rating", "score", "price", "stop_loss", "take_profit_1", "title", "reliability_pct", "stand_aside", "is_chase"]),
             "rating_vi": RATING_VI.get(s.rating), "outcomes": outcomes.get(s.id, {})} for s in sigs]


@router.get("/stocks/{symbol}/risk")
async def stock_risk(symbol: str, user: CurrentUser, db: DB):
    rk = await db.get(CompanyRiskScore, symbol.upper())
    st = await db.get(Stock, symbol.upper())
    if not rk:
        raise not_found("Chưa có điểm rủi ro")
    return {"symbol": symbol.upper(), "score": clean(rk.score), "level": rk.level, "level_vi": {"LOW": "Thấp", "MEDIUM": "Trung bình", "HIGH": "Cao"}.get(rk.level), "as_of": clean(rk.as_of),
            "flags": rk.flags or [], "status_flags": (st.status_flags if st else None) or [],
            "impact": "Hạ khuyến nghị một bậc, không phát tín hiệu mua" if rk.score >= 80 else ("Hạ khuyến nghị một bậc" if rk.score >= 60 else "Không ảnh hưởng khuyến nghị")}


@router.get("/stocks/{symbol}/events")
async def stock_events(symbol: str, user: CurrentUser, db: DB):
    rows = (await db.execute(select(CorporateAction).where(CorporateAction.symbol == symbol.upper()).order_by(desc(CorporateAction.ex_date)).limit(30))).scalars().all()
    return [row(r, ["id", "kind", "ex_date", "record_date", "event_date", "ratio", "cash_per_share", "title"]) for r in rows]


@router.get("/stocks/compare")
async def compare(user: CurrentUser, db: DB, symbols: str = ""):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:5]
    out = []
    for sym in syms:
        sn = await db.get(StockSnapshot, sym)
        st = await db.get(Stock, sym)
        if sn:
            out.append(snapshot_item(sn, st))
    return out


@router.get("/sectors")
async def sectors(user: CurrentUser, db: DB):
    sd = await db.scalar(select(func.max(SectorScore.trade_date)))
    rows = (await db.execute(select(SectorScore).where(SectorScore.trade_date == sd).order_by(desc(SectorScore.score)))).scalars().all() if sd else []
    return [{"code": r.industry_code, "name": ICB_LV2.get(r.industry_code, (r.industry_code,))[0], **row(r, ["score", "perf_1w", "perf_1m", "perf_3m", "money_flow", "breadth", "stock_count", "macro_note"]), "leaders": r.leaders or []} for r in rows]


@router.get("/sectors/{code}")
async def sector_detail(code: str, user: CurrentUser, db: DB, horizon: str = "MID"):
    hz = horizon.upper() if horizon.upper() in HZ else "MID"
    col = {"SHORT": StockSnapshot.score_adj_short, "LONG": StockSnapshot.score_adj_long}.get(hz, StockSnapshot.score_adj_mid)
    rows = (await db.execute(select(Stock, StockSnapshot).join(StockSnapshot, StockSnapshot.symbol == Stock.symbol).where(Stock.industry_code == code, Stock.is_active).order_by(desc(col).nulls_last()).limit(60))).all()
    hist = (await db.execute(select(SectorScore).where(SectorScore.industry_code == code).order_by(desc(SectorScore.trade_date)).limit(60))).scalars().all()
    return {"code": code, "name": ICB_LV2.get(code, (code,))[0], "stocks": [snapshot_item(sn, st, hz) for st, sn in rows],
            "history": [row(h, ["trade_date", "score", "perf_1w", "perf_1m", "perf_3m"]) for h in reversed(hist)]}


@router.get("/calendar")
async def calendar(user: CurrentUser, db: DB, from_: date | None = Query(None, alias="from"), to: date | None = None):
    from_ = from_ or today_vn()
    to = to or from_ + timedelta(days=30)
    rows = (await db.execute(select(CorporateAction).where(or_(CorporateAction.ex_date.between(from_, to), CorporateAction.event_date.between(from_, to))).order_by(CorporateAction.ex_date))).scalars().all()
    return [row(r, ["id", "symbol", "kind", "ex_date", "record_date", "event_date", "ratio", "cash_per_share", "title"]) for r in rows]


@router.get("/opportunities")
async def opportunities(user: CurrentUser, db: DB, horizon: str = "MID", only_buy: bool = False, exclude_high_risk: bool = False, exclude_chase: bool = False,
                        exchange: str | None = None, limit: int = Query(50, le=200), page: int = 1, sort: str = "risk_adjusted"):
    hz = horizon.upper() if horizon.upper() in HZ else "MID"
    col = {"SHORT": StockSnapshot.score_short, "LONG": StockSnapshot.score_long}.get(hz, StockSnapshot.score_mid)
    acol = {"SHORT": StockSnapshot.score_adj_short, "LONG": StockSnapshot.score_adj_long}.get(hz, StockSnapshot.score_adj_mid)
    rcol = {"SHORT": StockSnapshot.rating_short, "LONG": StockSnapshot.rating_long}.get(hz, StockSnapshot.rating_mid)
    min_liq = float(await get_config(db, "market.min_liquidity") or 0)
    stmt = select(Stock, StockSnapshot).join(StockSnapshot, StockSnapshot.symbol == Stock.symbol).where(Stock.is_active, StockSnapshot.value_ma20 >= min_liq, col.isnot(None))
    if only_buy:
        stmt = stmt.where(rcol.in_(["STRONG_BUY", "BUY"]))
    if exclude_high_risk:
        stmt = stmt.where(or_(StockSnapshot.risk_score < 60, StockSnapshot.risk_score.is_(None)))
    if exclude_chase:
        stmt = stmt.where(or_(StockSnapshot.is_chase.is_(False), StockSnapshot.is_chase.is_(None)))
    if exchange:
        stmt = stmt.where(Stock.exchange == exchange.upper())
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    order = desc(col) if sort == "score" else desc(acol).nulls_last()
    rows = (await db.execute(stmt.order_by(order, desc(col)).offset((page - 1) * limit).limit(limit))).all()
    return {"items": [snapshot_item(sn, st, hz) for st, sn in rows], "total": total, "page": page, "size": limit, "horizon": hz, "sort": sort}


@router.get("/signals")
async def signals(user: CurrentUser, db: DB, type: str | None = None, horizon: str | None = None, date_: date | None = Query(None, alias="date"), symbol: str | None = None, limit: int = Query(100, le=500)):
    stmt = select(Signal)
    if date_:
        stmt = stmt.where(Signal.trade_date == date_)
    elif not symbol:
        last = await db.scalar(select(func.max(Signal.trade_date)))
        stmt = stmt.where(Signal.trade_date == last)
    if type:
        stmt = stmt.where(Signal.signal_type == type.upper())
    if horizon:
        stmt = stmt.where(Signal.horizon == horizon.upper())
    if symbol:
        stmt = stmt.where(Signal.symbol == symbol.upper())
    rows = (await db.execute(stmt.order_by(desc(Signal.trade_date), desc(Signal.score)).limit(limit))).scalars().all()
    snaps = {x.symbol: x for x in (await db.execute(select(StockSnapshot).where(StockSnapshot.symbol.in_({s.symbol for s in rows})))).scalars()} if rows else {}
    from app.services.risknumbers import current_regime, numbers_for, ref_order_vnd

    ref_order, regime_now, rel_cache = await ref_order_vnd(db, user), await current_regime(db), {}
    return [{**row(s, ["id", "symbol", "trade_date", "strategy_code", "signal_type", "horizon", "rating", "score", "price", "entry_low", "entry_high", "stop_loss", "take_profit_1", "take_profit_2", "risk_reward", "priority", "reliability_pct", "reliability_samples", "stand_aside", "is_chase", "risk_score", "title", "reasons", "facts"]),
             "rating_vi": RATING_VI.get(s.rating), "risk_total": clean(snaps[s.symbol].risk_total) if s.symbol in snaps else None, "risk_total_level": snaps[s.symbol].risk_total_level if s.symbol in snaps else None,
             "risk_total_vi": RISK_VI_LBL.get(snaps[s.symbol].risk_total_level) if s.symbol in snaps else None,
             "risk_numbers": await numbers_for(db, s.strategy_code, s.regime_at_signal or regime_now, s.horizon, s.price, s.stop_loss, ref_order, getattr(snaps.get(s.symbol), "value_ma20", None), rel_cache)} for s in rows]


@router.get("/signals/{signal_id}")
async def signal_detail(signal_id: int, user: CurrentUser, db: DB):
    s = await db.get(Signal, signal_id)
    if not s:
        raise not_found()
    outs = {o.days: row(o, ["return_pct", "max_gain_pct", "max_loss_pct", "hit_tp1", "hit_stop", "result"]) for o in (await db.execute(select(SignalOutcome).where(SignalOutcome.signal_id == s.id))).scalars()}
    st = await db.get(Strategy, s.strategy_code)
    return {**row(s, ["id", "symbol", "trade_date", "strategy_code", "signal_type", "horizon", "rating", "score", "price", "entry_low", "entry_high", "stop_loss", "take_profit_1", "take_profit_2", "risk_reward", "priority", "regime_at_signal", "reliability_pct", "reliability_samples", "stand_aside", "is_chase", "risk_score", "title", "reasons", "facts"]),
            "rating_vi": RATING_VI.get(s.rating), "strategy": row(st, ["code", "name", "description", "win_rate", "avg_return", "trades"]) if st else None, "outcomes": outs}


@router.get("/signals/{signal_id}/reliability")
async def signal_reliability(signal_id: int, user: CurrentUser, db: DB):
    s = await db.get(Signal, signal_id)
    if not s:
        raise not_found()
    rows = (await db.execute(select(SignalReliability).where(SignalReliability.strategy_code == s.strategy_code, SignalReliability.horizon == s.horizon))).scalars().all()
    return [{**row(r, ["regime", "days", "samples", "win_rate", "avg_return"]), "regime_vi": REGIME_VI.get(r.regime)} for r in rows]

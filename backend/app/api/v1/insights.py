"""News, insider deals, investor flows, corporate events, broker recommendations (free sources, docs/NGUON-DU-LIEU.md)."""

from datetime import date, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import desc, func, or_, select, text

from app.api.deps import DB, CurrentUser
from app.api.presenters import clean, price_int, row
from app.core.vntime import today_vn
from app.models import BrokerRecommendation, CorporateAction, InsiderTransaction, InvestorFlow, NewsArticle, NewsStockLink, Stock, StockSnapshot

router = APIRouter(tags=["insights"])

KIND_VI = {
    "CASH_DIVIDEND": "Cổ tức tiền", "STOCK_DIVIDEND": "Cổ tức cổ phiếu", "BONUS": "Cổ phiếu thưởng", "ISSUE": "Phát hành thêm", "AGM": "Họp ĐHCĐ",
    "AGM_RECORD": "Chốt quyền ĐHCĐ", "POLL": "Lấy ý kiến cổ đông", "LISTED": "Niêm yết / giao dịch bổ sung", "PAY_DATE_CHANGE": "Đổi ngày trả cổ tức",
    "ALERT_CONTROL": "Diện kiểm soát", "ALERT_SPECIAL_CONTROL": "Kiểm soát đặc biệt", "ALERT_WARNING": "Diện cảnh báo", "ALERT_NOTICE": "Nhắc nhở",
    "ALERT_SUSPEND": "Tạm ngừng giao dịch", "ALERT_DELIST": "Hủy niêm yết",
}
SIDE_VI = {"BUY": "Mua", "SELL": "Bán"}
STATUS_VI = {"REGISTERED": "Đăng ký", "DONE": "Đã thực hiện", "CANCELLED": "Hủy"}
REC_VI = {"BUY": "Mua", "STRONG_BUY": "Mua mạnh", "OUTPERFORM": "Khả quan", "ADD": "Tăng tỷ trọng", "ACCUMULATE": "Tích lũy", "HOLD": "Nắm giữ",
          "NEUTRAL": "Trung lập", "UNDERPERFORM": "Kém khả quan", "REDUCE": "Giảm", "SELL": "Bán"}


def news_out(a: NewsArticle) -> dict:
    return {"id": a.id, "title": a.title, "summary": a.ai_summary or (a.summary or "")[:300], "url": a.url, "source": a.source, "image_url": a.image_url,
            "published_at": clean(a.published_at), "symbols": a.symbols or [], "sentiment": clean(a.sentiment), "sentiment_label": a.sentiment_label,
            "ai_summary": bool(a.ai_summary)}


def event_out(e: CorporateAction) -> dict:
    return {**row(e, ["id", "symbol", "kind", "ex_date", "record_date", "event_date", "disclosure_date", "ratio", "cash_per_share", "issue_price", "shares", "title", "note"]),
            "kind_vi": KIND_VI.get(e.kind, e.title), "date": clean(e.ex_date or e.event_date or e.disclosure_date),
            "is_alert": e.kind.startswith("ALERT_")}


def insider_out(i: InsiderTransaction, price: float | None = None) -> dict:
    qty = i.quantity_done if i.status == "DONE" and i.quantity_done else i.quantity
    return {**row(i, ["id", "symbol", "person", "relation", "related_person", "event_code", "side", "quantity", "quantity_done", "shares_before", "shares_after",
                      "ownership_after_pct", "start_date", "end_date", "announce_date", "status", "title", "source_url"]),
            "side_vi": SIDE_VI.get(i.side), "status_vi": STATUS_VI.get(i.status), "value_est": round(qty * price) if qty and price else None,
            "kind_vi": {"DDIND": "Cá nhân nội bộ", "DDINS": "Tổ chức", "DDRP": "Người liên quan"}.get(i.event_code or "", "Nội bộ")}


@router.get("/news")
async def news(user: CurrentUser, db: DB, symbol: str | None = None, market: bool | None = None, sentiment: str | None = None, page: int = 1, size: int = Query(30, le=100)):
    stmt = select(NewsArticle)
    if symbol:
        stmt = stmt.join(NewsStockLink, NewsStockLink.article_id == NewsArticle.id).where(NewsStockLink.symbol == symbol.upper())
    if market:
        stmt = stmt.where(NewsArticle.is_market.is_(True))
    if sentiment:
        stmt = stmt.where(NewsArticle.sentiment_label == sentiment.upper())
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (await db.execute(stmt.order_by(desc(NewsArticle.published_at)).offset((page - 1) * size).limit(size))).scalars().all()
    return {"items": [news_out(a) for a in rows], "total": total, "page": page, "size": size}


@router.get("/stocks/{symbol}/news")
async def stock_news(symbol: str, user: CurrentUser, db: DB, limit: int = Query(20, le=100)):
    rows = (await db.execute(select(NewsArticle).join(NewsStockLink, NewsStockLink.article_id == NewsArticle.id)
                             .where(NewsStockLink.symbol == symbol.upper()).order_by(desc(NewsArticle.published_at)).limit(limit))).scalars().all()
    sn = await db.get(StockSnapshot, symbol.upper())
    return {"items": [news_out(a) for a in rows], "sentiment_7d": clean(sn.news_sentiment_7d) if sn else None, "count_7d": sn.news_count_7d if sn else 0}


@router.get("/stocks/{symbol}/insiders")
async def stock_insiders(symbol: str, user: CurrentUser, db: DB, limit: int = Query(30, le=200)):
    sym = symbol.upper()
    sn = await db.get(StockSnapshot, sym)
    rows = (await db.execute(select(InsiderTransaction).where(InsiderTransaction.symbol == sym)
                             .order_by(desc(func.coalesce(InsiderTransaction.announce_date, InsiderTransaction.start_date))).limit(limit))).scalars().all()
    price = sn.price if sn else None
    return {"items": [insider_out(i, price) for i in rows], "net_90d": price_int(sn.insider_net_90d) if sn else None,
            "pending_sell_shares": int(sn.insider_pending_sell) if sn and sn.insider_pending_sell else 0,
            "note": "Giá trị ước tính theo giá hiện tại; dữ liệu từ công bố giao dịch nội bộ (Vietcap)."}


@router.get("/stocks/{symbol}/flows")
async def stock_flows(symbol: str, user: CurrentUser, db: DB, days: int = Query(60, le=250)):
    sym = symbol.upper()
    rows = (await db.execute(select(InvestorFlow).where(InvestorFlow.symbol == sym).order_by(desc(InvestorFlow.trade_date)).limit(days))).scalars().all()
    sn = await db.get(StockSnapshot, sym)
    return {"symbol": sym, "series": [{"date": clean(r.trade_date), "foreign_net": clean(r.foreign_net_val), "foreign_buy": clean(r.foreign_buy_val), "foreign_sell": clean(r.foreign_sell_val),
                                       "prop_net": clean(r.prop_net_val)} for r in reversed(rows)],
            "foreign_net_today": clean(sn.foreign_net_today) if sn else None, "foreign_net_5d": clean(sn.foreign_net_5d) if sn else None,
            "foreign_net_20d": clean(sn.foreign_net_20d) if sn else None, "prop_net_5d": clean(sn.prop_net_5d) if sn else None,
            "foreign_room_pct": clean(sn.foreign_room_pct) if sn else None}


@router.get("/stocks/{symbol}/recommendations")
async def stock_recommendations(symbol: str, user: CurrentUser, db: DB, limit: int = Query(20, le=100)):
    sym = symbol.upper()
    rows = (await db.execute(select(BrokerRecommendation).where(BrokerRecommendation.symbol == sym).order_by(desc(BrokerRecommendation.report_date)).limit(limit))).scalars().all()
    sn = await db.get(StockSnapshot, sym)
    return {"items": [{**row(r, ["firm", "rec_type", "report_date", "analyst", "source"]), "rec_vi": REC_VI.get((r.rec_type or "").upper(), r.rec_type),
                       "report_price": price_int(r.report_price), "target_price": price_int(r.target_price),
                       "upside_pct": round((r.target_price / sn.price - 1) * 100, 1) if r.target_price and sn and sn.price else None} for r in rows],
            "consensus_target": price_int(sn.consensus_target) if sn else None, "consensus_upside_pct": clean(sn.consensus_upside_pct) if sn else None,
            "consensus_count": sn.consensus_count if sn else 0, "note": "Trung bình giá mục tiêu mới nhất của mỗi công ty trong 180 ngày."}


@router.get("/stocks/{symbol}/corporate-events")
async def stock_events(symbol: str, user: CurrentUser, db: DB, limit: int = Query(30, le=200)):
    sym = symbol.upper()
    today = today_vn()
    rows = (await db.execute(select(CorporateAction).where(CorporateAction.symbol == sym).order_by(desc(func.coalesce(CorporateAction.ex_date, CorporateAction.event_date, CorporateAction.disclosure_date))).limit(limit))).scalars().all()
    items = [event_out(e) for e in rows if e.kind != "LISTED"]
    upcoming = sorted([i for i in items if i["date"] and i["date"] >= today.isoformat() and not i["is_alert"]], key=lambda x: x["date"])
    return {"upcoming": upcoming, "recent": [i for i in items if i not in upcoming][:limit], "alerts": [i for i in items if i["is_alert"]][:10]}


@router.get("/market/flows")
async def market_flows(user: CurrentUser, db: DB, top: int = Query(10, le=30)):
    d = await db.scalar(select(func.max(InvestorFlow.trade_date)))
    if not d:
        return {"date": None, "foreign_net": None, "prop_net": None, "top_buy": [], "top_sell": [], "series": []}
    tot = (await db.execute(select(func.sum(InvestorFlow.foreign_net_val), func.sum(InvestorFlow.prop_net_val), func.sum(InvestorFlow.foreign_buy_val), func.sum(InvestorFlow.foreign_sell_val)).where(InvestorFlow.trade_date == d))).one()
    names = {s.symbol: (s.short_name or s.name_vi) for s in (await db.execute(select(Stock))).scalars()}

    async def tops(order):
        rows = (await db.execute(select(InvestorFlow).where(InvestorFlow.trade_date == d, InvestorFlow.foreign_net_val.isnot(None)).order_by(order).limit(top))).scalars().all()
        return [{"symbol": r.symbol, "name": names.get(r.symbol), "foreign_net": clean(r.foreign_net_val)} for r in rows]

    series = (await db.execute(text("SELECT trade_date, sum(foreign_net_val), sum(prop_net_val) FROM investor_flows WHERE trade_date >= :s GROUP BY 1 ORDER BY 1"), {"s": d - timedelta(days=45)})).all()
    return {"date": clean(d), "foreign_net": clean(tot[0]), "prop_net": clean(tot[1]), "foreign_buy": clean(tot[2]), "foreign_sell": clean(tot[3]),
            "top_buy": await tops(desc(InvestorFlow.foreign_net_val)), "top_sell": await tops(InvestorFlow.foreign_net_val),
            "series": [{"date": clean(a), "foreign_net": clean(b), "prop_net": clean(c)} for a, b, c in series]}


@router.get("/market/insiders")
async def market_insiders(user: CurrentUser, db: DB, days: int = 14, side: str | None = None, limit: int = Query(50, le=200)):
    stmt = select(InsiderTransaction).where(InsiderTransaction.announce_date >= today_vn() - timedelta(days=days))
    if side:
        stmt = stmt.where(InsiderTransaction.side == side.upper())
    rows = (await db.execute(stmt.order_by(desc(InsiderTransaction.announce_date)).limit(limit))).scalars().all()
    prices = {s: p for s, p in (await db.execute(select(StockSnapshot.symbol, StockSnapshot.price).where(StockSnapshot.symbol.in_({r.symbol for r in rows})))).all()} if rows else {}
    return [insider_out(i, prices.get(i.symbol)) for i in rows]


@router.get("/market/events")
async def market_events(user: CurrentUser, db: DB, from_: date | None = Query(None, alias="from"), to: date | None = None, kind: str | None = None, followed_only: bool = False):
    from app.models import Position, Portfolio, Watchlist, WatchlistItem

    from_ = from_ or today_vn()
    to = to or from_ + timedelta(days=30)
    d = func.coalesce(CorporateAction.ex_date, CorporateAction.event_date)
    stmt = select(CorporateAction).where(d.between(from_, to), CorporateAction.kind.notin_(["LISTED"]))
    if kind:
        stmt = stmt.where(CorporateAction.kind == kind.upper())
    if followed_only:
        wl = select(WatchlistItem.symbol).join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id).where(Watchlist.user_id == user.id)
        pos = select(Position.symbol).join(Portfolio, Portfolio.id == Position.portfolio_id).where(Portfolio.user_id == user.id, Position.quantity > 0)
        stmt = stmt.where(or_(CorporateAction.symbol.in_(wl), CorporateAction.symbol.in_(pos)))
    rows = (await db.execute(stmt.order_by(d).limit(300))).scalars().all()
    return [event_out(e) for e in rows]

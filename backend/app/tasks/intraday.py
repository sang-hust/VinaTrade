"""Intraday pass (every 5 min in session): refresh live quotes for followed symbols from SSI, update snapshot price fields,
evaluate URGENT portfolio conditions (stop broken), user INTRADAY rules and plan steps. Phase-3 realtime (15 s) builds on this."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.adapters.ssi import SSIAdapter
from app.models import AlertRule, Portfolio, Position, StockSnapshot, User, Watchlist, WatchlistItem
from app.screener.dsl import evaluate
from app.services.notify import create_alert, dispatch_pending
from app.services.trades import evaluate_plans

log = logging.getLogger(__name__)


async def intraday_pass(db: AsyncSession) -> dict:
    users = (await db.execute(select(User).where(User.status == "ACTIVE"))).scalars().all()
    followed: set[str] = set()
    for (s,) in (await db.execute(select(WatchlistItem.symbol).join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id))).all():
        followed.add(s)
    for (s,) in (await db.execute(select(Position.symbol).where(Position.quantity > 0))).all():
        followed.add(s)
    for (s,) in (await db.execute(select(AlertRule.scope_id).where(AlertRule.scope_type == "SYMBOL", AlertRule.enabled))).all():
        if s:
            followed.add(s)
    if not followed:
        return {"quotes": 0}
    ssi = SSIAdapter(timeout=30)
    try:
        quotes = await ssi.quotes(sorted(followed))
    finally:
        await ssi.close()
    snaps = {s.symbol: s for s in (await db.execute(select(StockSnapshot).where(StockSnapshot.symbol.in_(followed)))).scalars()}
    live: dict[str, dict] = {}
    for q in quotes:
        sn = snaps.get(q.symbol)
        if not sn or not q.price:
            continue
        sn.price, sn.change, sn.change_pct = q.price, q.change, q.change_pct
        if q.ref_price:
            sn.ref_price = q.ref_price
        if q.ceiling:
            sn.ceiling, sn.floor = q.ceiling, q.floor
        if q.volume:
            sn.volume = q.volume
            sn.vol_ratio = (q.volume / (sn.value_ma20 / sn.price) if sn.value_ma20 and sn.price else sn.vol_ratio)
        row = {c.name: getattr(sn, c.name) for c in StockSnapshot.__table__.columns}
        row["price_vs_stop_pct"] = None
        live[q.symbol] = row
    await db.flush()
    n_alerts = 0
    guard_modes = {}
    for u in users:
        from app.models import RiskGuardStatus
        g = await db.get(RiskGuardStatus, u.id)
        guard_modes[u.id] = g.mode if g else "NORMAL"
        # stop broken on positions
        for pf in (await db.execute(select(Portfolio).where(Portfolio.user_id == u.id))).scalars():
            for pos in (await db.execute(select(Position).where(Position.portfolio_id == pf.id, Position.quantity > 0))).scalars():
                row = live.get(pos.symbol)
                stop = pos.stop_loss or (row or {}).get("stop_loss")
                if row and stop and row["price"] and row["price"] <= stop:
                    a = await create_alert(db, u, kind="PORTFOLIO", priority="URGENT", title=f"{pos.symbol} chạm cắt lỗ",
                                           body=f"Giá {row['price']:,.0f} thấp hơn mức cắt lỗ {stop:,.0f} của bạn.".replace(",", "."), symbol=pos.symbol,
                                           deeplink=f"/portfolio/{pf.id}", dedupe_key=f"stop:{pf.id}:{pos.symbol}:{datetime.now(UTC).date()}")
                    n_alerts += 1 if a else 0
        # intraday rules on single symbols / portfolio
        rules = (await db.execute(select(AlertRule).where(AlertRule.user_id == u.id, AlertRule.enabled, AlertRule.timing.in_(["INTRADAY", "BOTH"]), AlertRule.scope_type.in_(["SYMBOL", "PORTFOLIO", "WATCHLIST"])))).scalars().all()
        for r in rules:
            syms = [r.scope_id] if r.scope_type == "SYMBOL" else ([s for (s,) in (await db.execute(select(Position.symbol).where(Position.portfolio_id == r.scope_id, Position.quantity > 0))).all()] if r.scope_type == "PORTFOLIO"
                                                                   else [s for (s,) in (await db.execute(select(WatchlistItem.symbol).where(WatchlistItem.watchlist_id == r.scope_id))).all()])
            for sym in syms:
                row = live.get(sym)
                if not row:
                    continue
                row = dict(row)
                if r.scope_type == "PORTFOLIO":
                    pos = await db.get(Position, (r.scope_id, sym))
                    if pos and pos.avg_cost:
                        row["position_pnl_pct"] = (row["price"] / pos.avg_cost - 1) * 100
                        row["price_vs_stop_pct"] = (row["price"] / pos.stop_loss - 1) * 100 if pos.stop_loss else None
                try:
                    hit = evaluate(r.conditions, row)
                except Exception:  # noqa: BLE001
                    hit = False
                if hit:
                    a = await create_alert(db, u, kind="PRICE", priority=r.priority, title=f"{sym}: {r.name}", body=f"Giá {row['price']:,.0f} ({(row['change_pct'] or 0):+.2f}%) lúc {datetime.now().astimezone().strftime('%H:%M')}".replace(",", "."),
                                           symbol=sym, deeplink=f"/stocks/{sym}", rule_id=r.id, dedupe_key=f"rule:{r.id}:{sym}", dedupe_hours=max(1, r.cooldown_minutes // 60), channels=r.channels)
                    if a:
                        r.last_fired_at = datetime.now(UTC)
                        n_alerts += 1
    triggered = await evaluate_plans(db, live, None, guard_modes)
    for plan, step in triggered:
        u = await db.get(User, plan.user_id)
        if u:
            await create_alert(db, u, kind="PLAN", priority="HIGH", title=f"{plan.symbol}: bước {step.seq} kế hoạch đã tới", body=step.title, symbol=plan.symbol,
                               deeplink=f"/portfolio/{plan.portfolio_id}/plans/{plan.symbol}" if plan.portfolio_id else f"/stocks/{plan.symbol}", dedupe_key=f"plan:{plan.id}:{step.seq}")
            n_alerts += 1
    disp = await dispatch_pending(db)
    try:
        from app.api.v1.system import hub
        for sym, row in live.items():
            await hub.broadcast(f"quotes:{sym}", {"p": row["price"], "chg": row["change"], "chg_pct": row["change_pct"], "vol": row["volume"]})
    except Exception:  # noqa: BLE001
        pass
    return {"quotes": len(live), "alerts": n_alerts, "plans_triggered": len(triggered), "dispatch": disp}

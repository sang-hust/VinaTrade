"""User-facing EOD step: system signals → alerts for followers, rating changes, user rules (EOD), risk guard,
action items, screener notifications, daily report. Then dispatch deliveries."""

from __future__ import annotations

import logging

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engines.scoring import RATING_VI
from app.models import AlertRule, MarketRegime, Portfolio, Position, Screener, Signal, StockSnapshot, User, Watchlist, WatchlistItem
from app.screener.dsl import evaluate, to_sql
from app.services.notify import create_alert, dispatch_pending
from app.services.riskguard import evaluate_guard, refresh_action_items
from app.services.trades import evaluate_plans

log = logging.getLogger(__name__)


def fmt(v: float | None) -> str:
    return "—" if v is None else f"{v:,.0f}".replace(",", ".")


async def _followed_symbols(db: AsyncSession, user: User) -> set[str]:
    wl = {s for (s,) in (await db.execute(select(WatchlistItem.symbol).join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id).where(Watchlist.user_id == user.id))).all()}
    pos = {s for (s,) in (await db.execute(select(Position.symbol).join(Portfolio, Portfolio.id == Position.portfolio_id).where(Portfolio.user_id == user.id, Position.quantity > 0))).all()}
    return wl | pos


async def step_users(db: AsyncSession) -> dict:
    users = (await db.execute(select(User).where(User.status == "ACTIVE"))).scalars().all()
    d = await db.scalar(select(func.max(Signal.trade_date)))
    sigs = (await db.execute(select(Signal).where(Signal.trade_date == d))).scalars().all() if d else []
    by_sym: dict[str, list[Signal]] = {}
    for s in sigs:
        by_sym.setdefault(s.symbol, []).append(s)
    snaps = {r.symbol: r for r in (await db.execute(select(StockSnapshot))).scalars()}
    regime = (await db.execute(select(MarketRegime).order_by(desc(MarketRegime.trade_date)).limit(1))).scalar_one_or_none()
    top = sorted([s for s in sigs if s.signal_type == "BUY" and not s.stand_aside and not s.is_chase], key=lambda s: -(s.score or 0))[:5]
    stats = {"users": len(users), "alerts": 0}
    snap_dicts = {k: {c.name: getattr(v, c.name) for c in StockSnapshot.__table__.columns} for k, v in snaps.items()}
    guard_modes = {}
    for u in users:
        followed = await _followed_symbols(db, u)
        # 1. signals on followed symbols
        for sym in followed:
            for s in by_sym.get(sym, []):
                if s.stand_aside:
                    continue
                body = f"Giá {fmt(s.price)}. " + (f"Vùng mua {fmt(s.entry_low)}–{fmt(s.entry_high)}, cắt lỗ {fmt(s.stop_loss)}, chốt lời {fmt(s.take_profit_1)}. " if s.signal_type == "BUY" else "")
                if s.reliability_pct:
                    body += f"Độ tin cậy: đúng {s.reliability_pct:.0f}% ({s.reliability_samples} lần)."
                a = await create_alert(db, u, kind="SIGNAL", priority=s.priority, title=s.title, body=body.strip(), symbol=sym, deeplink=f"/stocks/{sym}",
                                       signal_id=s.id, dedupe_key=f"sig:{s.dedupe_key}", data={"signal_type": s.signal_type, "score": s.score})
                stats["alerts"] += 1 if a else 0
        # 2. rating changes on followed symbols
        for sym in followed:
            sn = snaps.get(sym)
            if sn and sn.rating_changed and sn.prev_rating and sn.rating:
                a = await create_alert(db, u, kind="RATING_CHANGE", priority="HIGH", title=f"{sym}: {RATING_VI.get(sn.prev_rating)} → {RATING_VI.get(sn.rating)}",
                                       body=f"Điểm trung hạn {sn.score_mid:.0f}/100, giá {fmt(sn.price)}.", symbol=sym, deeplink=f"/stocks/{sym}",
                                       dedupe_key=f"rating:{sym}:{d.isoformat()}")
                stats["alerts"] += 1 if a else 0
        # 3. user EOD rules
        rules = (await db.execute(select(AlertRule).where(AlertRule.user_id == u.id, AlertRule.enabled, AlertRule.timing.in_(["EOD", "BOTH"])))).scalars().all()
        for r in rules:
            try:
                hits = await _rule_hits(db, u, r, snap_dicts)
            except Exception as e:  # noqa: BLE001
                log.warning("rule %s failed: %s", r.id, e)
                continue
            for sym in hits[:10]:
                sn = snaps.get(sym)
                a = await create_alert(db, u, kind="PRICE", priority=r.priority, title=f"{sym}: {r.name}", body=f"Giá {fmt(sn.price if sn else None)} ({sn.change_pct:+.2f}%)." if sn and sn.change_pct is not None else None,
                                       symbol=sym, deeplink=f"/stocks/{sym}", rule_id=r.id, dedupe_key=f"rule:{r.id}:{sym}", dedupe_hours=max(1, r.cooldown_minutes // 60), channels=r.channels)
                stats["alerts"] += 1 if a else 0
        # 4. screeners with notify_new
        for sc in (await db.execute(select(Screener).where(Screener.user_id == u.id, Screener.notify_new))).scalars():
            try:
                syms = [s for (s,) in (await db.execute(select(StockSnapshot.symbol).where(to_sql(sc.conditions)).limit(200))).all()]
            except Exception:  # noqa: BLE001
                continue
            prev = set((sc.last_result or {}).get("symbols") or [])
            new = [s for s in syms if s not in prev]
            sc.last_result = {"count": len(syms), "symbols": syms[:200], "date": d.isoformat() if d else None}
            if new:
                a = await create_alert(db, u, kind="PRICE", priority="INFO", title=f"Bộ lọc “{sc.name}” có {len(new)} mã mới", body=", ".join(new[:12]),
                                       deeplink=f"/screener/{sc.id}", dedupe_key=f"scr:{sc.id}:{d.isoformat() if d else ''}")
                stats["alerts"] += 1 if a else 0
        # 5. risk guard + action items + plans
        g = await evaluate_guard(db, u)
        guard_modes[u.id] = g["mode"]
        for pf in (await db.execute(select(Portfolio).where(Portfolio.user_id == u.id))).scalars():
            await refresh_action_items(db, u, pf)
        # 6. daily report
        if regime:
            lines = [regime.headline or ""]
            if top:
                lines.append("Tín hiệu mua nổi bật: " + ", ".join(f"{s.symbol} ({s.score:.0f})" if s.score else s.symbol for s in top))
            mine = [s for sym in followed for s in by_sym.get(sym, [])]
            if mine:
                lines.append("Mã bạn theo dõi: " + "; ".join(s.title.split("] ", 1)[-1] for s in mine[:5]))
            await create_alert(db, u, kind="REPORT", priority="INFO", title=f"Báo cáo cuối ngày {d.strftime('%d/%m') if d else ''}: thị trường {regime_vi(regime.regime)}",
                               body="\n".join(ln for ln in lines if ln), deeplink="/", dedupe_key=f"report:{d.isoformat() if d else ''}")
    # trade plans (EOD evaluation on snapshots)
    triggered = await evaluate_plans(db, snap_dicts, None, guard_modes)
    for plan, step in triggered:
        u = await db.get(User, plan.user_id)
        if u:
            await create_alert(db, u, kind="PLAN", priority="HIGH", title=f"{plan.symbol}: bước {step.seq} kế hoạch đã tới", body=step.title, symbol=plan.symbol,
                               deeplink=f"/portfolio/{plan.portfolio_id}/plans/{plan.symbol}" if plan.portfolio_id else f"/stocks/{plan.symbol}",
                               dedupe_key=f"plan:{plan.id}:{step.seq}")
    stats["dispatch"] = await dispatch_pending(db)
    return stats


def regime_vi(r: str) -> str:
    return {"UPTREND": "tăng", "PRESSURE": "chịu áp lực", "CORRECTION": "điều chỉnh", "DOWNTREND": "giảm"}.get(r, r)


async def _rule_hits(db: AsyncSession, user: User, r: AlertRule, snap_dicts: dict[str, dict]) -> list[str]:
    if r.scope_type == "SYMBOL" and r.scope_id:
        syms = [r.scope_id.upper()]
    elif r.scope_type == "WATCHLIST" and r.scope_id:
        syms = [s for (s,) in (await db.execute(select(WatchlistItem.symbol).where(WatchlistItem.watchlist_id == r.scope_id))).all()]
    elif r.scope_type == "PORTFOLIO" and r.scope_id:
        syms = [s for (s,) in (await db.execute(select(Position.symbol).where(Position.portfolio_id == r.scope_id, Position.quantity > 0))).all()]
    elif r.scope_type == "SCREENER" and r.scope_id:
        sc = await db.get(Screener, r.scope_id)
        syms = [s for (s,) in (await db.execute(select(StockSnapshot.symbol).where(to_sql(sc.conditions)).limit(300))).all()] if sc else []
    else:
        syms = [s for (s,) in (await db.execute(select(StockSnapshot.symbol).where(to_sql(r.conditions)).limit(300))).all()]
        return syms
    hits = []
    for sym in syms:
        row = snap_dicts.get(sym)
        if not row:
            continue
        row = dict(row)
        if r.scope_type == "PORTFOLIO":
            pos = await db.get(Position, (r.scope_id, sym))
            if pos and pos.quantity > 0:
                row["position_pnl_pct"] = (row["price"] / pos.avg_cost - 1) * 100 if pos.avg_cost else None
                row["price_vs_stop_pct"] = (row["price"] / pos.stop_loss - 1) * 100 if pos.stop_loss else None
        if evaluate(r.conditions, row):
            hits.append(sym)
    return hits

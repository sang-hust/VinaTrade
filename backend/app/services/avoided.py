"""'Rủi ro tránh được' — evidence that the discipline features paid off (least-risk philosophy, plan item 6).
Measures what happened AFTER each guard decision: RED pretrade checks that were not overridden (and the overrides),
circuit-breaker periods, stop-loss action items acted on vs ignored, and user drawdown vs VN-Index. System-wide for
A10 (admin) and per user for the portfolio risk tab and the weekly coach report."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vntime import today_vn
from app.models import (
    ActionItem,
    IndexDaily,
    Portfolio,
    PretradeCheck,
    PriceDaily,
    RiskGuardEvent,
    Transaction,
)

HOLD = 20


async def _forward_return(db: AsyncSession, symbol: str, d: date, sessions: int = HOLD) -> float | None:
    """Close-to-close return (%) from the first session ≥ d to `sessions` sessions later; None when the window is open."""
    rows = (await db.execute(select(PriceDaily.close).where(PriceDaily.symbol == symbol, PriceDaily.trade_date >= d).order_by(PriceDaily.trade_date).limit(sessions + 1))).scalars().all()
    if len(rows) < sessions + 1 or not rows[0]:
        return None
    return round((rows[-1] / rows[0] - 1) * 100, 2)


async def _index_return(db: AsyncSession, d0: date, d1: date | None = None, sessions: int | None = None) -> float | None:
    q = select(IndexDaily.close).where(IndexDaily.index_code == "VNINDEX", IndexDaily.trade_date >= d0).order_by(IndexDaily.trade_date)
    if d1 is not None:
        q = q.where(IndexDaily.trade_date <= d1)
    rows = (await db.execute(q.limit((sessions + 1) if sessions else 400))).scalars().all()
    if len(rows) < 2 or (sessions and len(rows) < sessions + 1):
        return None
    return round((rows[-1] / rows[0] - 1) * 100, 2)


def _summ(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0, "avg_return": None, "pct_fell": None}
    return {"n": len(vals), "avg_return": round(sum(vals) / len(vals), 2), "pct_fell": round(sum(1 for v in vals if v < 0) / len(vals) * 100, 0)}


async def avoided_risk(db: AsyncSession, days: int = 180, user_id: uuid.UUID | None = None) -> dict:
    since = datetime.now(UTC) - timedelta(days=days)

    # 1. RED pretrade checks: blocked (no buy within 2 sessions, no override) vs overridden
    q = select(PretradeCheck).where(PretradeCheck.result == "RED", PretradeCheck.created_at >= since)
    if user_id:
        q = q.where(PretradeCheck.user_id == user_id)
    checks = (await db.execute(q.order_by(PretradeCheck.created_at))).scalars().all()
    blocked, overridden, avoided_vnd, blocked_items = [], [], 0.0, []
    for c in checks:
        d0 = c.created_at.date()
        bought = (await db.execute(select(Transaction.id).join(Portfolio, Portfolio.id == Transaction.portfolio_id)
                                    .where(Portfolio.user_id == c.user_id, Transaction.symbol == c.symbol, Transaction.side == "BUY", Transaction.trade_date.between(d0, d0 + timedelta(days=4))).limit(1))).scalar_one_or_none()
        r = await _forward_return(db, c.symbol, d0)
        if r is None:
            continue
        if bought or c.override_reason:
            overridden.append(r)
        else:
            blocked.append(r)
            if r < 0 and c.quantity and c.price:
                avoided_vnd += -r / 100 * c.quantity * float(c.price)
            blocked_items.append({"symbol": c.symbol, "date": d0.isoformat(), "return_20": r, "order_value": round(float(c.price) * c.quantity) if c.quantity and c.price else None,
                                  "reasons": [it.get("name") for it in (c.items or []) if it.get("level") == "RED"][:3]})
    blocked_items.sort(key=lambda x: x["return_20"])

    # 2. circuit breaker: VN-Index during the cooldown and 20 sessions after
    q = select(RiskGuardEvent).where(RiskGuardEvent.kind == "GUARD_ON", RiskGuardEvent.created_at >= since)
    if user_id:
        q = q.where(RiskGuardEvent.user_id == user_id)
    guard = []
    for e in (await db.execute(q)).scalars():
        d0 = e.created_at.date()
        rel = (e.detail or {}).get("release_at")
        during = await _index_return(db, d0, date.fromisoformat(rel)) if rel else None
        after20 = await _index_return(db, d0, sessions=HOLD)
        guard.append({"date": d0.isoformat(), "reason": e.note, "index_during": during, "index_20": after20})
    g_vals = [g["index_during"] for g in guard if g["index_during"] is not None]

    # 3. drawdown cap events: index 20 sessions after
    q = select(RiskGuardEvent).where(RiskGuardEvent.kind == "DRAWDOWN_CAP", RiskGuardEvent.created_at >= since)
    if user_id:
        q = q.where(RiskGuardEvent.user_id == user_id)
    caps = [await _index_return(db, e.created_at.date(), sessions=HOLD) for e in (await db.execute(q)).scalars()]
    caps = [c for c in caps if c is not None]

    # 4. stop-loss discipline: STOP_BROKEN items acted on (sold) vs ignored — price 20 sessions after the breach
    q = select(ActionItem).where(ActionItem.kind == "STOP_BROKEN", ActionItem.created_at >= since)
    if user_id:
        q = q.where(ActionItem.user_id == user_id)
    sold, held = [], []
    for a in (await db.execute(q)).scalars():
        if not a.symbol:
            continue
        r = await _forward_return(db, a.symbol, a.created_at.date())
        if r is None:
            continue
        (sold if a.status == "DONE" and (a.result_text or "").startswith("Đã ghi bán") else held).append(r)

    out = {"days": days, "hold_sessions": HOLD,
           "red_blocked": {**_summ(blocked), "avoided_vnd": round(avoided_vnd), "items": blocked_items[:8]},
           "red_overridden": _summ(overridden),
           "guard": {"n": len(guard), "avg_index_during": round(sum(g_vals) / len(g_vals), 2) if g_vals else None, "pct_index_fell": round(sum(1 for v in g_vals if v < 0) / len(g_vals) * 100, 0) if g_vals else None, "items": guard[-6:]},
           "drawdown_cap": _summ(caps),
           "stop_sold": _summ(sold), "stop_held": _summ(held)}
    out["headline"] = _headline(out)
    return out


def _headline(o: dict) -> str:
    parts = []
    b = o["red_blocked"]
    if b["n"]:
        parts.append(f"Kiểm tra Đỏ đã chặn {b['n']} lệnh; các mã đó sau {o['hold_sessions']} phiên trung bình {b['avg_return']:+.1f}%, {b['pct_fell']:.0f}% giảm"
                     + (f", tránh được khoảng {b['avoided_vnd'] / 1e6:,.0f} triệu".replace(",", ".") if b["avoided_vnd"] >= 1e6 else "") + ".")
    ov = o["red_overridden"]
    if ov["n"]:
        parts.append(f"{ov['n']} lần vượt rào Đỏ: trung bình {ov['avg_return']:+.1f}% sau đó.")
    g = o["guard"]
    if g["n"] and g["avg_index_during"] is not None:
        parts.append(f"Cầu dao bật {g['n']} lần; VN-Index trong thời gian nghỉ trung bình {g['avg_index_during']:+.1f}%.")
    if o["stop_sold"]["n"] or o["stop_held"]["n"]:
        s, h = o["stop_sold"], o["stop_held"]
        parts.append("Thủng cắt lỗ: " + (f"bán đúng hạn {s['n']} lần (mã sau đó {s['avg_return']:+.1f}%)" if s["n"] else "") + (" · " if s["n"] and h["n"] else "")
                     + (f"giữ lại {h['n']} lần (mã sau đó {h['avg_return']:+.1f}%)" if h["n"] else "") + ".")
    return " ".join(parts) or "Chưa có tình huống nào để đo (kiểm tra Đỏ, cầu dao, thủng cắt lỗ) trong kỳ."


async def user_drawdown_vs_index(db: AsyncSession, user_id: uuid.UUID, days: int = 90) -> dict | None:
    """Worst drawdown of the user's real portfolios vs VN-Index over the same window."""
    from app.services.portfolio import nav_history

    pfs = (await db.execute(select(Portfolio).where(Portfolio.user_id == user_id, Portfolio.is_paper.is_(False)))).scalars().all()
    if not pfs:
        return None
    start = today_vn() - timedelta(days=days)
    series: dict[date, float] = {}
    for pf in pfs:
        for d, v in await nav_history(db, pf, start):
            series[d] = series.get(d, 0.0) + v
    navs = [v for _, v in sorted(series.items())]
    if len(navs) < 5:
        return None

    def mdd(xs):
        peak, worst = xs[0], 0.0
        for x in xs:
            peak = max(peak, x)
            worst = min(worst, (x / peak - 1) * 100 if peak else 0.0)
        return round(worst, 2)

    idx = (await db.execute(select(IndexDaily.close).where(IndexDaily.index_code == "VNINDEX", IndexDaily.trade_date >= start).order_by(IndexDaily.trade_date))).scalars().all()
    return {"days": days, "portfolio_mdd": mdd(navs), "vnindex_mdd": mdd(list(idx)) if len(idx) > 5 else None}

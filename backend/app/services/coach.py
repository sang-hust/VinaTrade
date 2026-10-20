"""Weekly AI coach (4.6l): behaviour metrics from the user's own trades, 3 insights with evidence, 1 rule."""

import logging
from datetime import timedelta

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vntime import today_vn, week_start
from app.models import (
    CoachReport,
    IndexDaily,
    Portfolio,
    PretradeCheck,
    RiskGuardEvent,
    Transaction,
    User,
)
from app.services import ai
from app.services.portfolio import nav_history

log = logging.getLogger(__name__)


async def trade_metrics(db: AsyncSession, user: User, weeks: int = 12) -> dict:
    since = today_vn() - timedelta(weeks=weeks)
    pfs = (await db.execute(select(Portfolio).where(Portfolio.user_id == user.id, Portfolio.is_paper.is_(False)))).scalars().all()
    txs = []
    for pf in pfs:
        txs += (await db.execute(select(Transaction).where(Transaction.portfolio_id == pf.id, Transaction.side.in_(["BUY", "SELL"])).order_by(Transaction.trade_date, Transaction.created_at))).scalars().all()
    txs.sort(key=lambda t: (t.trade_date, t.created_at))
    # FIFO round trips
    lots: dict[str, list] = {}
    trips = []
    for t in txs:
        if t.side == "BUY":
            lots.setdefault(t.symbol, []).append([t.quantity, float(t.price), t.trade_date, t])
        else:
            q = t.quantity
            while q > 0 and lots.get(t.symbol):
                lot = lots[t.symbol][0]
                take = min(q, lot[0])
                pnl = (float(t.price) - lot[1]) * take - float(t.fee or 0) * take / max(t.quantity, 1) - float(t.tax or 0) * take / max(t.quantity, 1)
                trips.append({"symbol": t.symbol, "qty": take, "buy": lot[1], "sell": float(t.price), "pnl": pnl, "pnl_pct": (float(t.price) / lot[1] - 1) * 100,
                              "hold_days": (t.trade_date - lot[2]).days, "buy_date": lot[2], "sell_date": t.trade_date, "buy_tx": lot[3]})
                lot[0] -= take
                q -= take
                if lot[0] == 0:
                    lots[t.symbol].pop(0)
    recent = [x for x in trips if x["sell_date"] >= since]
    wins = [x for x in recent if x["pnl"] > 0]
    losses = [x for x in recent if x["pnl"] <= 0]
    events = (await db.execute(select(RiskGuardEvent).where(RiskGuardEvent.user_id == user.id, RiskGuardEvent.created_at >= since))).scalars().all()
    checks = (await db.execute(select(PretradeCheck).where(PretradeCheck.user_id == user.id, PretradeCheck.created_at >= since))).scalars().all()
    red_over = [c for c in checks if c.result == "RED" and c.override_reason]
    red_results = []
    for c in red_over:
        for x in recent:
            if x["buy_tx"].pretrade_check_id == c.id:
                red_results.append(x["pnl"])
    m = {
        "weeks": weeks, "trades": len(recent), "wins": len(wins), "losses": len(losses), "win_rate": round(len(wins) / len(recent) * 100, 1) if recent else None,
        "avg_win_pct": round(sum(x["pnl_pct"] for x in wins) / len(wins), 2) if wins else None, "avg_loss_pct": round(sum(x["pnl_pct"] for x in losses) / len(losses), 2) if losses else None,
        "avg_hold_win": round(sum(x["hold_days"] for x in wins) / len(wins), 1) if wins else None, "avg_hold_loss": round(sum(x["hold_days"] for x in losses) / len(losses), 1) if losses else None,
        "total_pnl": round(sum(x["pnl"] for x in recent)), "biggest_loss": min((x["pnl"] for x in recent), default=0), "biggest_loss_symbol": min(recent, key=lambda x: x["pnl"])["symbol"] if recent else None,
        "stop_lowered": sum(1 for e in events if e.kind == "STOP_LOWERED"), "average_down": sum(1 for e in events if e.kind == "AVERAGE_DOWN"), "guard_on": sum(1 for e in events if e.kind == "GUARD_ON"),
        "red_overrides": len(red_over), "red_override_losses": sum(1 for p in red_results if p < 0), "pretrade_checks": len(checks),
        "yellow_checks": sum(1 for c in checks if c.result == "YELLOW"), "green_checks": sum(1 for c in checks if c.result == "GREEN"),
        "by_symbol": {},
    }
    for x in recent:
        d = m["by_symbol"].setdefault(x["symbol"], {"trades": 0, "pnl": 0.0})
        d["trades"] += 1
        d["pnl"] += x["pnl"]
    m["by_symbol"] = {k: {"trades": v["trades"], "pnl": round(v["pnl"])} for k, v in sorted(m["by_symbol"].items(), key=lambda kv: kv[1]["pnl"])[:8]}
    return m


def _insights(m: dict) -> tuple[list[dict], str]:
    ins = []
    rule = ""
    if m["avg_hold_loss"] and m["avg_hold_win"] and m["avg_hold_loss"] > m["avg_hold_win"] * 1.5:
        ins.append({"code": "HOLD_LOSS", "text": f"Lệnh lỗ bạn giữ trung bình {m['avg_hold_loss']:.0f} ngày, lệnh lãi chỉ {m['avg_hold_win']:.0f} ngày — cắt lỗ chậm, chốt lãi sớm.", "impact": abs(m["avg_loss_pct"] or 0)})
        rule = rule or "Cắt lỗ đúng mức đã đặt, không chờ thêm phiên nào."
    if m["red_overrides"]:
        ins.append({"code": "RED_OVERRIDE", "text": f"{m['red_overrides']} lần vượt rào kiểm tra Đỏ, {m['red_override_losses']} lần trong số đó lỗ.", "impact": m["red_overrides"] * 5})
        rule = rule or "Không mua khi kiểm tra trước khi mua báo Đỏ."
    if m["average_down"]:
        ins.append({"code": "AVERAGE_DOWN", "text": f"Bạn đã bình quân giá xuống {m['average_down']} lần ở mã đang lỗ.", "impact": m["average_down"] * 4})
        rule = rule or "Chỉ mua thêm khi vị thế đang lãi và có điểm mua mới."
    if m["stop_lowered"]:
        ins.append({"code": "STOP_LOWERED", "text": f"{m['stop_lowered']} lần hạ mức cắt lỗ thấp hơn kế hoạch ban đầu.", "impact": m["stop_lowered"] * 3})
        rule = rule or "Không hạ mức cắt lỗ sau khi đã vào lệnh."
    if m["win_rate"] is not None and m["trades"] >= 5:
        ins.append({"code": "WIN_RATE", "text": f"Tỷ lệ thắng {m['win_rate']:.0f}% trên {m['trades']} lệnh; lãi trung bình {m['avg_win_pct'] or 0:+.1f}%, lỗ trung bình {m['avg_loss_pct'] or 0:+.1f}%.", "impact": 1})
    if m["biggest_loss_symbol"] and m["biggest_loss"] < 0:
        ins.append({"code": "BIGGEST_LOSS", "text": f"Khoản lỗ lớn nhất: {m['biggest_loss_symbol']} ({m['biggest_loss']:,.0f} đồng).".replace(",", "."), "impact": 2})
    if not ins:
        ins.append({"code": "NO_DATA", "text": "Chưa có đủ giao dịch đã đóng trong 12 tuần để đánh giá. Hãy ghi lại mọi giao dịch để huấn luyện viên có dữ liệu.", "impact": 0})
    ins.sort(key=lambda i: -i["impact"])
    return ins[:3], rule or "Ghi lý do vào lệnh trước khi mua, kể cả khi kiểm tra báo Xanh."


async def build_report(db: AsyncSession, user: User) -> CoachReport:
    from app.services.avoided import avoided_risk

    m = await trade_metrics(db, user)
    insights, rule = _insights(m)
    # evidence that the guards paid off (plan item 6) — shown as the first insight when there is any
    try:
        av = await avoided_risk(db, 90, user.id)
        m["avoided"] = {k: v for k, v in av.items() if k != "red_blocked"} | {"red_blocked": {k: v for k, v in av["red_blocked"].items() if k != "items"}}
        if av["red_blocked"]["n"] or av["guard"]["n"] or av["stop_sold"]["n"] or av["stop_held"]["n"]:
            insights = [{"code": "AVOIDED", "text": av["headline"], "impact": 99}, *insights][:3]
    except Exception as e:  # noqa: BLE001 — never let the evidence block the report
        log.warning("avoided-risk evidence skipped: %s", e)
    # benchmark since start of year
    pfs = (await db.execute(select(Portfolio).where(Portfolio.user_id == user.id, Portfolio.is_paper.is_(False)))).scalars().all()
    bench = {}
    if pfs:
        start = today_vn() - timedelta(weeks=12)
        tot_start = tot_now = 0.0
        for pf in pfs:
            s = await nav_history(db, pf, start)
            if len(s) >= 2:
                tot_start += s[0][1]
                tot_now += s[-1][1]
        idx = (await db.execute(select(IndexDaily).where(IndexDaily.index_code == "VNINDEX", IndexDaily.trade_date >= start).order_by(IndexDaily.trade_date))).scalars().all()
        bench = {"portfolio_pct": round((tot_now / tot_start - 1) * 100, 2) if tot_start else None, "vnindex_pct": round((idx[-1].close / idx[0].close - 1) * 100, 2) if len(idx) > 1 else None,
                 "savings_pct": round(6.0 * 12 / 52, 2), "weeks": 12}
    summary = await ai.coach_summary(m, insights, rule)
    ws = week_start(today_vn())
    existing = (await db.execute(select(CoachReport).where(CoachReport.user_id == user.id, CoachReport.week_start == ws))).scalar_one_or_none()
    if existing:
        existing.metrics, existing.insights, existing.rule, existing.summary, existing.benchmark = m, insights, rule, summary, bench
        await db.flush()
        return existing
    r = CoachReport(user_id=user.id, week_start=ws, metrics=m, insights=insights, rule=rule, summary=summary, benchmark=bench)
    db.add(r)
    await db.flush()
    return r


async def weekly_reports(db: AsyncSession) -> int:
    from app.services.notify import create_alert

    users = (await db.execute(select(User).where(User.status == "ACTIVE"))).scalars().all()
    n = 0
    for u in users:
        has_tx = await db.scalar(select(Transaction.id).join(Portfolio, Portfolio.id == Transaction.portfolio_id).where(Portfolio.user_id == u.id).limit(1))
        if not has_tx:
            continue
        r = await build_report(db, u)
        await create_alert(db, u, kind="REPORT", priority="INFO", title="Huấn luyện viên tuần: 3 điều cần chú ý", body="\n".join(i["text"] for i in (r.insights or [])),
                           deeplink=f"/account/coach/{r.week_start.isoformat()}", dedupe_key=f"coach:{r.week_start.isoformat()}")
        n += 1
    return n


_ = desc

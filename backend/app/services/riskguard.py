"""Risk guard (cầu dao giới hạn lỗ, UC-07 / BR-15) and action items (Cần xử lý, 4.6m / BR-24)."""

from datetime import UTC, datetime, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vntime import add_sessions, today_vn
from app.engines.risk import correlated_groups, guard_decision
from app.engines.scoring import RATING_VI
from app.models import ActionItem, Portfolio, PriceDaily, RiskGuardEvent, RiskGuardStatus, TradePlan, TradePlanStep, User, UserRiskLimit
from app.services.notify import create_alert
from app.services.portfolio import period_pnl, portfolio_view, user_real_portfolios


def fmt_vnd(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.0f}".replace(",", ".")


async def ensure_user_defaults(db: AsyncSession, user: User, defaults: dict | None = None) -> tuple[UserRiskLimit, RiskGuardStatus]:
    lim = await db.get(UserRiskLimit, user.id)
    if lim is None:
        lim = UserRiskLimit(user_id=user.id, **{k: v for k, v in (defaults or {}).items() if hasattr(UserRiskLimit, k)})
        db.add(lim)
    g = await db.get(RiskGuardStatus, user.id)
    if g is None:
        g = RiskGuardStatus(user_id=user.id)
        db.add(g)
    await db.flush()
    return lim, g


async def evaluate_guard(db: AsyncSession, user: User) -> dict:
    lim, g = await ensure_user_defaults(db, user)
    pfs = await user_real_portfolios(db, user.id)
    week_pct = month_pct = week_vnd = month_vnd = nav = 0.0
    for pf in pfs:
        p = await period_pnl(db, pf)
        week_vnd += p["week_pnl_vnd"]
        month_vnd += p["month_pnl_vnd"]
        nav += p["nav"]
    if nav > 0:
        week_pct, month_pct = week_vnd / nav * 100, month_vnd / nav * 100
    g.week_pnl_pct, g.month_pnl_pct, g.week_pnl_vnd, g.month_pnl_vnd = round(week_pct, 3), round(month_pct, 3), week_vnd, month_vnd
    g.evaluated_at = datetime.now(UTC)
    today = today_vn()
    decision = guard_decision(g.mode, week_pct, month_pct, float(lim.weekly_loss_limit_pct), float(lim.monthly_loss_limit_pct),
                              today, g.release_at, is_new_month=(today.day == 1 and g.triggered_at and g.triggered_at.date() < today.replace(day=1)))
    if decision == "ON" and nav > 0:
        g.mode, g.triggered_at = "DEFENSIVE", datetime.now(UTC)
        g.release_at = add_sessions(today, lim.cooldown_sessions or 5)
        which = f"Lỗ tuần này {week_pct:+.1f}%, vượt giới hạn −{float(lim.weekly_loss_limit_pct):.1f}%" if week_pct <= -float(lim.weekly_loss_limit_pct) \
            else f"Lỗ tháng này {month_pct:+.1f}%, vượt giới hạn −{float(lim.monthly_loss_limit_pct):.1f}%"
        g.reason = which
        db.add(RiskGuardEvent(user_id=user.id, kind="GUARD_ON", detail={"week_pnl_pct": week_pct, "month_pnl_pct": month_pct, "release_at": g.release_at.isoformat()}, note=which))
        await create_alert(db, user, kind="GUARD", priority="URGENT", title="Đã bật chế độ phòng thủ",
                           body=f"{which}. Ứng dụng tạm dừng gợi ý mua đến {g.release_at.strftime('%d/%m')}.", deeplink="/portfolio",
                           dedupe_key=f"guard_on:{today.isoformat()}")
    elif decision == "OFF":
        g.mode, g.release_at, g.reason = "NORMAL", None, None
        db.add(RiskGuardEvent(user_id=user.id, kind="GUARD_OFF", detail={"week_pnl_pct": week_pct, "month_pnl_pct": month_pct}))
        await create_alert(db, user, kind="GUARD", priority="HIGH", title="Đã tắt chế độ phòng thủ",
                           body="Thời gian nghỉ đã hết. Hãy xem lại các khoản lỗ trước khi mở vị thế mới.", deeplink="/portfolio",
                           dedupe_key=f"guard_off:{today.isoformat()}")
    await db.flush()
    return {"mode": g.mode, "week_pnl_pct": week_pct, "month_pnl_pct": month_pct, "release_at": g.release_at, "nav": nav}


async def _returns_frame(db: AsyncSession, symbols: list[str], sessions: int = 60) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame()
    start = today_vn() - timedelta(days=int(sessions * 1.6) + 10)
    rows = (await db.execute(select(PriceDaily.symbol, PriceDaily.trade_date, PriceDaily.close)
                             .where(PriceDaily.symbol.in_(symbols), PriceDaily.trade_date >= start))).all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["symbol", "d", "c"]).pivot(index="d", columns="symbol", values="c").sort_index()
    return df.pct_change().iloc[-sessions:]


async def refresh_action_items(db: AsyncSession, user: User, pf: Portfolio, notify_urgent: bool = True) -> list[ActionItem]:
    lim, g = await ensure_user_defaults(db, user)
    view = await portfolio_view(db, pf)
    nav = view["nav"] or 1.0
    items: list[dict] = []

    def add(priority, kind, title, detail, actions, impact=0.0, symbol=None, key=None):
        items.append({"priority": priority, "kind": kind, "symbol": symbol, "title": title, "detail": detail, "actions": actions[:2],
                      "impact_vnd": impact, "rank_score": 100 * impact / nav, "dedupe_key": key or f"{kind}:{symbol or ''}"})

    if g.mode == "DEFENSIVE" and not pf.is_paper:
        add("URGENT", "GUARD_ON", f"Chế độ phòng thủ đang bật đến {g.release_at.strftime('%d/%m') if g.release_at else '—'}.",
            g.reason or "Lỗ vượt giới hạn tuần/tháng.", [{"code": "OPEN", "label": "Xem vị thế đang lỗ", "params": {"route": "/portfolio?tab=risk"}},
                                                        {"code": "OPEN", "label": "Giới hạn rủi ro", "params": {"route": "/account"}}],
            impact=abs(float(g.week_pnl_vnd or 0)))
    if view["open_risk_pct"] > float(lim.monthly_loss_limit_pct) and view["positions"]:
        add("URGENT", "MAX_LOSS", f"Nếu mọi mã cùng chạm cắt lỗ, bạn mất {view['open_risk_pct']:.1f}% tài sản, vượt giới hạn tháng {float(lim.monthly_loss_limit_pct):.0f}%.",
            "Giảm khối lượng hoặc nâng mức cắt lỗ ở các mã đang lãi.",
            [{"code": "OPEN", "label": "Xem kịch bản xấu", "params": {"route": "/portfolio?tab=risk"}}, {"code": "OPEN", "label": "Giới hạn rủi ro", "params": {"route": "/account"}}],
            impact=view["open_risk"])
    plans = {p.symbol: p for p in (await db.execute(select(TradePlan).where(TradePlan.portfolio_id == pf.id, TradePlan.status == "ACTIVE"))).scalars()}
    for v in view["positions"]:
        stop = v.stop_loss or v.extra.get("sys_stop")
        if stop and v.price <= stop:
            add("URGENT", "STOP_BROKEN", f"{v.symbol} đã thủng mức cắt lỗ {fmt_vnd(stop)} của bạn.",
                f"Giá {fmt_vnd(v.price)}, khuyến nghị hiện tại là {RATING_VI.get(v.rating, '—')}" + (f" ({v.score:.0f})." if v.score else "."),
                [{"code": "RECORD_SELL", "label": "Ghi nhận đã bán", "params": {"symbol": v.symbol, "quantity": v.quantity, "price": v.price}},
                 {"code": "EDIT_STOP", "label": "Sửa cắt lỗ", "params": {"symbol": v.symbol}}],
                impact=abs(v.price - stop) * v.quantity + v.value * 0.02, symbol=v.symbol)
        gfb, cs = v.extra.get("gain_from_base_pct"), v.extra.get("ceiling_streak") or 0
        if (gfb is not None and gfb > 20) or cs >= 2:
            if v.pnl_pct > 0 and v.weight_pct > 5:
                add("RISK", "CHASE", f"{v.symbol} đã tăng {gfb:.0f}% từ điểm phá nền — vùng mua đuổi, không mua thêm." if gfb else f"{v.symbol} đã trần {cs} phiên liên tiếp — không mua đuổi.",
                    "Nâng cắt lỗ lên để bảo vệ lãi thay vì mua thêm.",
                    [{"code": "ACK", "label": "Đã hiểu", "params": {}}, {"code": "OPEN", "label": "Xem phân tích", "params": {"route": f"/stocks/{v.symbol}"}}],
                    impact=v.value * 0.05, symbol=v.symbol)
        tp1 = v.take_profit_1 or v.extra.get("sys_tp1")
        if tp1 and v.price >= tp1 and v.pnl_pct > 0:
            new_stop = max(v.avg_cost, (v.extra.get("ma20") or 0))
            add("SUGGEST", "TAKE_PROFIT", f"{v.symbol} đã đạt chốt lời 1 ({fmt_vnd(tp1)}).",
                f"Theo kế hoạch: chốt một phần và nâng cắt lỗ lên {fmt_vnd(new_stop)}.",
                [{"code": "MOVE_STOP", "label": f"Dời cắt lỗ lên {fmt_vnd(new_stop)}", "params": {"symbol": v.symbol, "stop_loss": new_stop}},
                 {"code": "OPEN", "label": "Mở kế hoạch", "params": {"route": f"/portfolio/{pf.id}/plans/{v.symbol}"}}],
                impact=v.pnl, symbol=v.symbol)
        if v.weight_pct > float(lim.max_position_pct):
            add("RISK", "CONCENTRATION", f"{v.symbol} chiếm {v.weight_pct:.1f}% tài sản, vượt giới hạn {float(lim.max_position_pct):.0f}%.",
                "Cân nhắc giảm bớt hoặc không mua thêm mã này.",
                [{"code": "ACK", "label": "Đã hiểu", "params": {}}, {"code": "OPEN", "label": "Xem phân tích", "params": {"route": f"/stocks/{v.symbol}"}}],
                impact=(v.weight_pct - float(lim.max_position_pct)) / 100 * nav, symbol=v.symbol)
        # plan steps triggered
        plan = plans.get(v.symbol)
        if plan:
            step = await db.scalar(select(TradePlanStep).where(TradePlanStep.plan_id == plan.id, TradePlanStep.status == "TRIGGERED").order_by(TradePlanStep.seq))
            if step:
                first = {"code": "MOVE_STOP", "label": f"Dời cắt lỗ lên {fmt_vnd(step.new_stop)}", "params": {"symbol": v.symbol, "stop_loss": step.new_stop}} if step.action == "MOVE_STOP" \
                    else ({"code": "PRETRADE", "label": "Kiểm tra trước khi mua", "params": {"symbol": v.symbol, "fraction": step.fraction}} if step.action == "BUY"
                          else {"code": "RECORD_SELL", "label": "Ghi nhận đã bán", "params": {"symbol": v.symbol, "quantity": int(v.quantity * (step.fraction or 1)), "price": v.price}})
                add("SUGGEST", "PLAN_STEP", f"{v.symbol}: bước {step.seq} kế hoạch đã tới — {step.title}.", "Điều kiện của bước đã xảy ra trong phiên.",
                    [first, {"code": "OPEN", "label": "Mở kế hoạch", "params": {"route": f"/portfolio/{pf.id}/plans/{v.symbol}"}}],
                    impact=v.value * (step.fraction or 0.3), symbol=v.symbol, key=f"PLAN_STEP:{plan.id}:{step.seq}")
        # add-on when winning and a new entry appears (4.6, feature 7), only in NORMAL mode
        if g.mode == "NORMAL" and v.pnl_pct >= 5 and v.rating in ("STRONG_BUY", "BUY") and v.extra.get("entry_low") and v.extra["entry_low"] <= v.price <= (v.extra.get("entry_high") or 0) and (v.extra.get("vol_ratio") or 1) < 1.2:
            add("SUGGEST", "ADD_ON", f"{v.symbol} đang lãi {v.pnl_pct:.1f}% và có điểm mua mới ({fmt_vnd(v.extra['entry_low'])}–{fmt_vnd(v.extra['entry_high'])}).",
                "Mua thêm nhỏ hơn lần đầu (tối đa 50%) và luôn qua kiểm tra trước khi mua.",
                [{"code": "PRETRADE", "label": "Kiểm tra trước khi mua", "params": {"symbol": v.symbol, "fraction": 0.5}},
                 {"code": "SET_ALERT", "label": "Báo khi vào vùng mua", "params": {"symbol": v.symbol, "price": v.extra["entry_low"]}}],
                impact=v.value * 0.5, symbol=v.symbol)
    # correlation groups
    syms = [v.symbol for v in view["positions"]]
    if len(syms) >= 2:
        rets = await _returns_frame(db, syms)
        if not rets.empty:
            groups, _ = correlated_groups(rets, {v.symbol: v.weight_pct for v in view["positions"]})
            for grp in groups:
                if grp["weight_pct"] > float(lim.max_correlated_group_pct):
                    add("RISK", "CORRELATED", f"{', '.join(grp['symbols'])} thường tăng giảm cùng nhau và chiếm {grp['weight_pct']:.1f}% tài sản.",
                        f"Hệ số tương quan trung bình {grp['avg_corr']:.2f}. Danh mục thực chất chỉ là một khoản cược.",
                        [{"code": "ACK", "label": "Đã hiểu", "params": {}}, {"code": "OPEN", "label": "Xem tương quan", "params": {"route": "/portfolio?tab=risk"}}],
                        impact=grp["weight_pct"] / 100 * nav, key=f"CORRELATED:{'-'.join(grp['symbols'])}")
    if g.mode == "DEFENSIVE":
        items = [i for i in items if i["kind"] not in ("ADD_ON",)]

    # upsert by dedupe key
    now = datetime.now(UTC)
    existing = {a.dedupe_key: a for a in (await db.execute(select(ActionItem).where(ActionItem.portfolio_id == pf.id, ActionItem.status.in_(["OPEN", "DISMISSED"])))).scalars()}
    order = {"URGENT": 0, "RISK": 1, "SUGGEST": 2}
    items.sort(key=lambda i: (order[i["priority"]], -i["rank_score"]))
    new_urgent: list[ActionItem] = []
    kept = set()
    for it in items[:12]:
        kept.add(it["dedupe_key"])
        a = existing.get(it["dedupe_key"])
        if a:
            if a.status == "DISMISSED" and a.hide_until and a.hide_until > now:
                continue
            if a.status == "DISMISSED":
                a.status = "OPEN"
            a.title, a.detail, a.actions, a.rank_score, a.impact_vnd, a.priority = it["title"], it["detail"], it["actions"], it["rank_score"], it["impact_vnd"], it["priority"]
        else:
            a = ActionItem(user_id=user.id, portfolio_id=pf.id, expires_at=(now + timedelta(hours=72)) if it["priority"] == "SUGGEST" else None, **it)
            db.add(a)
            if it["priority"] == "URGENT":
                new_urgent.append(a)
    for key, a in existing.items():
        if key not in kept and a.status == "OPEN":
            a.status = "EXPIRED"
    await db.flush()
    if notify_urgent:
        for a in new_urgent:
            if a.kind == "GUARD_ON":
                continue  # already alerted by the guard
            await create_alert(db, user, kind="PORTFOLIO", priority="URGENT", title=a.title, body=a.detail, symbol=a.symbol,
                               deeplink=f"/portfolio/{pf.id}", dedupe_key=f"ai:{a.dedupe_key}", dedupe_hours=48)
    open_items = (await db.execute(select(ActionItem).where(ActionItem.portfolio_id == pf.id, ActionItem.status == "OPEN"))).scalars().all()
    return sorted(open_items, key=lambda a: (order[a.priority], -a.rank_score))


async def refresh_all_action_items(db: AsyncSession, users: list[User]) -> int:
    n = 0
    for u in users:
        for pf in (await db.execute(select(Portfolio).where(Portfolio.user_id == u.id))).scalars():
            n += len(await refresh_action_items(db, u, pf))
    return n


async def resolve_action(db: AsyncSession, user: User, item: ActionItem, action_code: str, params: dict) -> str:
    """Executes one of the item's buttons. Returns the result sentence. BUY-type actions never execute here (go through pretrade)."""
    from app.services.trades import record_transaction, set_stop_loss  # local import to avoid cycles

    allowed = {a["code"] for a in (item.actions or [])}
    if action_code not in allowed:
        from app.core.errors import bad_request
        raise bad_request("ACTION_NOT_ALLOWED", "Hành động không thuộc việc này")
    p = {**next((a.get("params") or {} for a in item.actions if a["code"] == action_code), {}), **(params or {})}
    pf = await db.get(Portfolio, item.portfolio_id)
    now = datetime.now(UTC)
    if action_code == "ACK":
        item.status, item.hide_until, item.resolved_at = "DISMISSED", now + timedelta(days=3), now
        item.result_text = "Đã ghi nhận"
    elif action_code == "RECORD_SELL":
        qty = int(p.get("quantity") or 0)
        price = float(p.get("price") or 0)
        await record_transaction(db, pf, side="SELL", symbol=p["symbol"], quantity=qty, price=price, trade_date=today_vn(), note="Từ thẻ Cần xử lý")
        item.status, item.resolved_at, item.result_text = "DONE", now, f"Đã ghi bán {qty:,} {p['symbol']}".replace(",", ".")
    elif action_code == "MOVE_STOP" or action_code == "EDIT_STOP":
        new_stop = float(p.get("stop_loss") or 0)
        if new_stop <= 0:
            from app.core.errors import bad_request
            raise bad_request("STOP_REQUIRED", "Cần mức cắt lỗ mới")
        await set_stop_loss(db, user, pf, p["symbol"], new_stop, reason=p.get("reason"))
        item.status, item.resolved_at, item.result_text = "DONE", now, f"Đã dời cắt lỗ {p['symbol']} lên {fmt_vnd(new_stop)}"
    elif action_code == "SET_ALERT":
        from app.models import AlertRule
        db.add(AlertRule(user_id=user.id, name=f"{p['symbol']} vào vùng mua", scope_type="SYMBOL", scope_id=p["symbol"], template="PRICE",
                         conditions={"field": "price", "op": "<=", "value": float(p.get("price") or 0)}, timing="BOTH", priority="HIGH",
                         channels=["push", "telegram"]))
        item.status, item.resolved_at, item.result_text = "DONE", now, f"Đã đặt cảnh báo {p['symbol']} về {fmt_vnd(p.get('price'))}"
    elif action_code in ("OPEN", "PRETRADE"):
        return "open"  # client navigates; item stays open
    else:
        item.status, item.resolved_at, item.result_text = "DONE", now, "Đã xử lý"
    await db.flush()
    return item.result_text or "Đã xử lý"

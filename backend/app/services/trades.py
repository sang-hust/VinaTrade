"""Transactions, stop-loss discipline (BR-16), trade plans."""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import bad_request
from app.core.vntime import today_vn
from app.models import Portfolio, Position, RiskGuardEvent, TradePlan, TradePlanStep, Transaction, User
from app.services.portfolio import recompute_positions


async def record_transaction(db: AsyncSession, pf: Portfolio, *, side: str, symbol: str | None, quantity: int, price: float,
                             trade_date: date, fee: float | None = None, tax: float | None = None, stop_loss: float | None = None,
                             take_profit: float | None = None, note: str | None = None, reason: str | None = None, emotion: str | None = None,
                             pretrade_check_id: uuid.UUID | None = None, amount: float | None = None) -> Transaction:
    side = side.upper()
    if side in ("BUY", "SELL"):
        if not symbol or quantity <= 0 or price <= 0:
            raise bad_request("TX_INVALID", "Cần mã, khối lượng và giá hợp lệ")
        symbol = symbol.upper()
        gross = quantity * price
        fee = gross * float(pf.fee_pct) / 100 if fee is None else fee
        tax = (gross * float(pf.tax_pct) / 100 if side == "SELL" else 0.0) if tax is None else tax
        amount = -(gross + fee) if side == "BUY" else gross - fee - tax
        if side == "SELL":
            pos = await db.get(Position, (pf.id, symbol))
            if not pos or pos.quantity < quantity:
                raise bad_request("TX_QTY", f"Danh mục chỉ có {pos.quantity if pos else 0} {symbol}")
    elif side in ("DEPOSIT", "WITHDRAW", "DIVIDEND"):
        if amount is None:
            raise bad_request("TX_INVALID", "Cần số tiền")
        amount = abs(amount) if side != "WITHDRAW" else -abs(amount)
        fee, tax, quantity, price = 0.0, 0.0, 0, 0.0
    else:
        raise bad_request("TX_SIDE", "Loại giao dịch không hợp lệ")
    tx = Transaction(portfolio_id=pf.id, symbol=symbol, side=side, quantity=quantity, price=price, fee=fee or 0, tax=tax or 0, amount=amount,
                     trade_date=trade_date, stop_loss=stop_loss, take_profit=take_profit, note=note, reason=reason, emotion=emotion,
                     pretrade_check_id=pretrade_check_id)
    db.add(tx)
    await db.flush()
    await recompute_positions(db, pf.id)
    if side == "BUY" and stop_loss:
        pos = await db.get(Position, (pf.id, symbol))
        if pos:
            pos.stop_loss = stop_loss
            pos.initial_stop_loss = pos.initial_stop_loss or stop_loss
            if take_profit:
                pos.take_profit_1 = take_profit
    return tx


async def set_stop_loss(db: AsyncSession, user: User, pf: Portfolio, symbol: str, new_stop: float, reason: str | None = None) -> Position:
    pos = await db.get(Position, (pf.id, symbol.upper()))
    if not pos or pos.quantity <= 0:
        raise bad_request("NO_POSITION", f"Không có vị thế {symbol}")
    old = pos.stop_loss
    lowering = old is not None and new_stop < old
    if lowering and not (reason and len(reason.strip()) >= 10):
        raise bad_request("STOP_LOWER_REASON", f"Bạn đang hạ cắt lỗ {symbol} từ {old:,.0f} xuống {new_stop:,.0f}, thấp hơn kế hoạch ban đầu. Ghi lý do (≥ 10 ký tự) để tiếp tục.".replace(",", "."))
    if lowering:
        db.add(RiskGuardEvent(user_id=user.id, kind="STOP_LOWERED", symbol=symbol, detail={"from": old, "to": new_stop}, note=reason))
    pos.stop_loss = new_stop
    if pos.initial_stop_loss is None:
        pos.initial_stop_loss = new_stop
    await db.flush()
    return pos


def _vnd(v: float) -> str:
    return f"{v:,.0f}".replace(",", ".")


PLAN_TEMPLATES = {
    "BREAKOUT_3": {
        "name": "Phá nền 3 bước",
        "steps": lambda p: [
            {"title": f"Nếu giá phá {_vnd(p['breakout'])} với KL ≥ 1,5 lần TB20 → mua 1/3", "action": "BUY", "fraction": 1 / 3, "price": p["breakout"],
             "condition": {"all": [{"field": "price", "op": ">", "value": p["breakout"]}, {"field": "vol_ratio", "op": ">=", "value": 1.5}]}},
            {"title": f"Nếu giá về {_vnd(p['pullback'])} và giữ trên MA20 → mua thêm 1/3", "action": "BUY", "fraction": 1 / 3, "price": p["pullback"],
             "condition": {"all": [{"field": "price", "op": "<=", "value": p["pullback"]}, {"field": "price", "op": ">", "value": {"field": "ma20"}}]}},
            {"title": f"Nếu lãi 10% → chốt 1/3, nâng cắt lỗ về giá vốn", "action": "TAKE_PROFIT", "fraction": 1 / 3, "new_stop": p["entry"],
             "condition": {"field": "position_pnl_pct", "op": ">=", "value": 10}},
            {"title": f"Nếu thủng {_vnd(p['stop'])} → bán hết", "action": "STOP_LOSS", "fraction": 1.0, "price": p["stop"],
             "condition": {"field": "price", "op": "<", "value": p["stop"]}},
        ],
    },
    "BUY_SUPPORT": {
        "name": "Mua tại hỗ trợ",
        "steps": lambda p: [
            {"title": f"Nếu giá về vùng hỗ trợ {_vnd(p['support'])} với KL thấp → mua 1/2", "action": "BUY", "fraction": 0.5, "price": p["support"],
             "condition": {"all": [{"field": "price", "op": "near", "value": p["support"], "lookback": 1}, {"field": "vol_ratio", "op": "<", "value": 1.0}]}},
            {"title": f"Nếu bật lên trên MA20 → mua nốt 1/2", "action": "BUY", "fraction": 0.5, "price": None,
             "condition": {"field": "price", "op": "cross_above", "value": {"field": "ma20"}, "lookback": 3}},
            {"title": f"Nếu thủng {_vnd(p['stop'])} → bán hết", "action": "STOP_LOSS", "fraction": 1.0, "price": p["stop"],
             "condition": {"field": "price", "op": "<", "value": p["stop"]}},
        ],
    },
    "SCALE_OUT": {
        "name": "Chốt lời từng phần",
        "steps": lambda p: [
            {"title": f"Nếu đạt {_vnd(p['tp1'])} → chốt 1/3, nâng cắt lỗ về giá vốn", "action": "TAKE_PROFIT", "fraction": 1 / 3, "price": p["tp1"], "new_stop": p["entry"],
             "condition": {"field": "price", "op": ">=", "value": p["tp1"]}},
            {"title": f"Nếu đạt {_vnd(p['tp2'])} → chốt thêm 1/3", "action": "TAKE_PROFIT", "fraction": 1 / 3, "price": p["tp2"],
             "condition": {"field": "price", "op": ">=", "value": p["tp2"]}},
            {"title": "Phần còn lại: dừng lỗ động theo MA20", "action": "SELL", "fraction": 1.0, "price": None,
             "condition": {"field": "price", "op": "<", "value": {"field": "ma20"}}},
        ],
    },
}


async def create_plan(db: AsyncSession, user: User, pf: Portfolio | None, symbol: str, template: str | None, params: dict,
                      name: str | None = None, steps: list[dict] | None = None) -> TradePlan:
    from app.screener.dsl import ensure_valid

    symbol = symbol.upper()
    if template:
        t = PLAN_TEMPLATES.get(template)
        if not t:
            raise bad_request("PLAN_TEMPLATE", "Mẫu kế hoạch không tồn tại")
        steps = t["steps"]({k: float(v) for k, v in params.items() if v is not None})
        name = name or t["name"]
    if not steps:
        raise bad_request("PLAN_STEPS", "Kế hoạch cần ít nhất một bước")
    plan = TradePlan(user_id=user.id, portfolio_id=pf.id if pf else None, symbol=symbol, name=name or f"Kế hoạch {symbol}", template=template)
    db.add(plan)
    await db.flush()
    for i, s in enumerate(steps, start=1):
        ensure_valid(s["condition"])
        db.add(TradePlanStep(plan_id=plan.id, seq=i, title=s["title"], condition=s["condition"], action=s["action"], fraction=s.get("fraction"),
                             price=s.get("price"), new_stop=s.get("new_stop")))
    await db.flush()
    return plan


async def evaluate_plans(db: AsyncSession, snapshots: dict[str, dict], histories: dict[str, dict] | None = None,
                         guard_modes: dict[uuid.UUID, str] | None = None) -> list[tuple[TradePlan, TradePlanStep]]:
    """Advance WAITING steps whose condition holds. Returns newly TRIGGERED (plan, step) pairs. Only the first WAITING step per plan."""
    from app.screener.dsl import evaluate

    plans = (await db.execute(select(TradePlan).where(TradePlan.status == "ACTIVE"))).scalars().all()
    out = []
    for plan in plans:
        snap = snapshots.get(plan.symbol)
        if not snap:
            continue
        steps = (await db.execute(select(TradePlanStep).where(TradePlanStep.plan_id == plan.id).order_by(TradePlanStep.seq))).scalars().all()
        if all(s.status == "DONE" for s in steps):
            plan.status = "DONE"
            continue
        if any(s.status == "TRIGGERED" for s in steps):
            continue
        step = next((s for s in steps if s.status == "WAITING"), None)
        if not step:
            continue
        row = dict(snap)
        if plan.portfolio_id:
            pos = await db.get(Position, (plan.portfolio_id, plan.symbol))
            if pos and pos.quantity > 0 and pos.avg_cost:
                row["position_pnl_pct"] = (float(snap.get("price") or 0) / pos.avg_cost - 1) * 100
        if step.action == "BUY" and guard_modes and guard_modes.get(plan.user_id) == "DEFENSIVE":
            continue  # BR-15: buy steps paused while defensive
        if evaluate(step.condition, row, (histories or {}).get(plan.symbol)):
            step.status, step.triggered_at = "TRIGGERED", datetime.now(UTC)
            out.append((plan, step))
    await db.flush()
    return out


async def complete_step(db: AsyncSession, plan: TradePlan, seq: int, transaction_id: uuid.UUID | None = None, skip: bool = False) -> TradePlanStep:
    step = await db.get(TradePlanStep, (plan.id, seq))
    if not step:
        raise bad_request("STEP_NOT_FOUND", "Không có bước này")
    step.status = "SKIPPED" if skip else "DONE"
    step.done_at = datetime.now(UTC)
    step.transaction_id = transaction_id
    steps = (await db.execute(select(TradePlanStep).where(TradePlanStep.plan_id == plan.id))).scalars().all()
    if all(s.status in ("DONE", "SKIPPED") for s in steps):
        plan.status = "DONE"
    await db.flush()
    return step


def _today() -> date:
    return today_vn()

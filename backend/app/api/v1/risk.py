import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import desc, select

from app.api.deps import DB, CurrentUser
from app.api.presenters import clean
from app.core.errors import bad_request, not_found
from app.core.vntime import floor_lot, round_tick
from app.engines.risk import PretradeInput, pretrade_check
from app.models import (
    MarketRegime,
    Portfolio,
    PretradeCheck,
    RiskGuardEvent,
    SignalReliability,
    Stock,
    StockSnapshot,
    UserSettings,
)
from app.services.portfolio import portfolio_view
from app.services.riskguard import ensure_user_defaults
from app.services.sysconfig import get_config

router = APIRouter(tags=["risk"])


class PretradeIn(BaseModel):
    symbol: str
    portfolio_id: uuid.UUID | None = None
    quantity: int | None = None
    price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    horizon: str | None = None
    override_reason: str | None = None
    save: bool = True


class SizingIn(BaseModel):
    symbol: str
    portfolio_id: uuid.UUID | None = None
    price: float | None = None
    stop_loss: float | None = None
    equity: float | None = None


@router.post("/pretrade-check")
async def pretrade(body: PretradeIn, user: CurrentUser, db: DB):
    sym = body.symbol.upper()
    st = await db.get(Stock, sym)
    sn = await db.get(StockSnapshot, sym)
    if not st or not sn or not sn.price:
        raise not_found("Chưa có dữ liệu mã này")
    lim, g = await ensure_user_defaults(db, user)
    us = await db.get(UserSettings, user.id)
    hz = (body.horizon or (us.default_horizon if us else None) or "MID").upper()
    pf = None
    if body.portfolio_id:
        pf = await db.get(Portfolio, body.portfolio_id)
        if not pf or pf.user_id != user.id:
            raise not_found("Danh mục không tồn tại")
    else:
        pf = (await db.execute(select(Portfolio).where(Portfolio.user_id == user.id, Portfolio.is_paper.is_(False)).order_by(Portfolio.created_at))).scalars().first()
    view = await portfolio_view(db, pf) if pf else None
    equity = view["nav"] if view and view["nav"] > 0 else float((us.capital_vnd if us and us.capital_vnd else 0) or 0)
    if equity <= 0:
        equity = 500_000_000.0  # no capital info → illustrative default, flagged in the response
    price = float(body.price or sn.price)
    stop = float(body.stop_loss) if body.stop_loss else (sn.stop_loss or round_tick(price * (1 - float(lim.stop_loss_pct) / 100), st.exchange, "down"))
    tp = float(body.take_profit) if body.take_profit else (sn.take_profit_1 or round_tick(price + 2 * (price - stop), st.exchange, "up"))
    qty = body.quantity
    if not qty:
        qty = floor_lot(equity * float(lim.max_risk_per_trade_pct) / 100 / max(price - stop, 1))
        qty = min(qty, floor_lot(equity * float(lim.max_position_pct) / 100 / price)) or 100
    pos_value = sector_value = 0.0
    if view:
        for v in view["positions"]:
            if v.symbol == sym:
                pos_value = v.value
            if v.industry_code and v.industry_code == st.industry_code:
                sector_value += v.value
    reg = (await db.execute(select(MarketRegime).order_by(desc(MarketRegime.trade_date)).limit(1))).scalar_one_or_none()
    regime = reg.regime if reg else "UPTREND"
    chase = await get_config(db, "risk.chase")
    rel = None
    sig_codes = [s.get("code") for s in (sn.signals_today or []) if isinstance(s, dict)]
    for code in sig_codes:
        r = await db.get(SignalReliability, (code, regime, hz, 20))
        if r and r.samples >= 30:
            rel = r
            break
    res = pretrade_check(PretradeInput(
        symbol=sym, quantity=int(qty), price=price, stop_loss=stop, take_profit=tp, horizon=hz, equity=equity, position_value=pos_value, sector_value=sector_value,
        regime=regime, guard_mode=g.mode if pf is None or not pf.is_paper else "NORMAL", status_flags=st.status_flags or [], value_ma20=sn.value_ma20,
        gain_from_base_pct=sn.gain_from_base_pct, ceiling_streak=sn.ceiling_streak, earnings_in_days=sn.earnings_in_days,
        limits={"max_risk_per_trade_pct": float(lim.max_risk_per_trade_pct), "max_position_pct": float(lim.max_position_pct), "max_sector_pct": float(lim.max_sector_pct), "min_risk_reward": float(lim.min_risk_reward)},
        reliability_pct=rel.win_rate if rel else None, reliability_samples=rel.samples if rel else None, chase_limits=(int(chase.get("SHORT", 15)), int(chase.get("MID", 20))),
    ))
    check_id = None
    if body.save:
        if res["result"] == "RED" and body.override_reason is not None and len(body.override_reason.strip()) < 10:
            raise bad_request("OVERRIDE_REASON", "Lý do vượt rào cần ít nhất 10 ký tự")
        pc = PretradeCheck(user_id=user.id, portfolio_id=pf.id if pf else None, symbol=sym, horizon=hz, quantity=int(qty), price=price, stop_loss=stop, take_profit=tp,
                           result=res["result"], items=res["items"], suggested_qty=res["suggested_qty"], override_reason=body.override_reason)
        db.add(pc)
        await db.flush()
        check_id = pc.id
        if res["result"] == "RED" and body.override_reason:
            db.add(RiskGuardEvent(user_id=user.id, kind="RED_OVERRIDE", symbol=sym, detail={"check_id": str(pc.id), "items": [i["code"] for i in res["items"] if i["level"] == "RED"]}, note=body.override_reason))
        await db.commit()
    from app.engines.risk import buy_options, risk_numbers
    from app.services.risknumbers import rel_dict

    options = buy_options(price, stop, int(qty), sn.value_ma20, equity)
    numbers = risk_numbers(rel_dict(rel), price, stop, int(qty) * price, sn.value_ma20)
    return {**res, "options": options, "risk_numbers": numbers, "check_id": str(check_id) if check_id else None, "symbol": sym, "name": st.short_name or st.name_vi, "horizon": hz, "quantity": int(qty), "price": round_tick(price, st.exchange),
            "stop_loss": round_tick(stop, st.exchange, "down"), "take_profit": round_tick(tp, st.exchange, "up"), "equity": round(equity), "equity_is_default": not (view and view["nav"] > 0) and not (us and us.capital_vnd),
            "portfolio_id": str(pf.id) if pf else None, "regime": regime, "guard_mode": g.mode, "tick": round_tick(price, st.exchange) - round_tick(price - 1, st.exchange, "down"),
            "ceiling": clean(sn.ceiling), "floor": clean(sn.floor), "can_override": res["result"] == "RED" and g.mode != "DEFENSIVE"}


@router.post("/position-sizing")
async def sizing(body: SizingIn, user: CurrentUser, db: DB):
    sym = body.symbol.upper()
    sn = await db.get(StockSnapshot, sym)
    st = await db.get(Stock, sym)
    if not sn:
        raise not_found()
    lim, _ = await ensure_user_defaults(db, user)
    equity = body.equity
    if not equity and body.portfolio_id:
        pf = await db.get(Portfolio, body.portfolio_id)
        if pf and pf.user_id == user.id:
            equity = (await portfolio_view(db, pf))["nav"]
    if not equity:
        us = await db.get(UserSettings, user.id)
        equity = float(us.capital_vnd or 0) if us else 0
    price = float(body.price or sn.price)
    stop = float(body.stop_loss or sn.stop_loss or price * 0.93)
    risk_vnd = equity * float(lim.max_risk_per_trade_pct) / 100
    qty = floor_lot(risk_vnd / max(price - stop, 1)) if equity else 0
    cap_qty = floor_lot(equity * float(lim.max_position_pct) / 100 / price) if equity else 0
    return {"symbol": sym, "price": round_tick(price, st.exchange if st else "HOSE"), "stop_loss": round_tick(stop, st.exchange if st else "HOSE", "down"), "equity": round(equity), "risk_vnd": round(risk_vnd),
            "risk_pct": clean(lim.max_risk_per_trade_pct), "quantity": min(qty, cap_qty) if cap_qty else qty, "qty_by_risk": qty, "qty_by_position_limit": cap_qty,
            "order_value": round(min(qty, cap_qty or qty) * price), "max_loss": round(min(qty, cap_qty or qty) * (price - stop))}

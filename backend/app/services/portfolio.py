"""Portfolio math: positions from transactions (avg cost, T+2 availability), NAV, PnL, weights, week/month PnL."""

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vntime import add_sessions, month_start, today_vn, week_start
from app.models import Portfolio, Position, PriceDaily, Stock, StockSnapshot, Transaction


@dataclass
class PositionView:
    symbol: str
    quantity: int
    available_qty: int
    avg_cost: float
    price: float
    value: float
    pnl: float
    pnl_pct: float
    weight_pct: float
    stop_loss: float | None
    initial_stop_loss: float | None
    take_profit_1: float | None
    take_profit_2: float | None
    industry_code: str | None
    name: str | None
    rating: str | None
    score: float | None
    change_pct: float | None
    beta: float | None
    extra: dict = field(default_factory=dict)


async def recompute_positions(db: AsyncSession, portfolio_id: uuid.UUID) -> None:
    """Rebuild positions + cash from the transaction log (source of truth)."""
    pf = await db.get(Portfolio, portfolio_id)
    txs = (await db.execute(select(Transaction).where(Transaction.portfolio_id == portfolio_id).order_by(Transaction.trade_date, Transaction.created_at))).scalars().all()
    existing = {p.symbol: p for p in (await db.execute(select(Position).where(Position.portfolio_id == portfolio_id))).scalars()}
    state: dict[str, dict] = {}
    cash = float(pf.initial_capital or 0)
    today = today_vn()
    for t in txs:
        if t.side in ("DEPOSIT", "WITHDRAW", "DIVIDEND"):
            cash += float(t.amount)
            continue
        s = state.setdefault(t.symbol, {"qty": 0, "cost": 0.0, "realized": 0.0, "opened": None, "last_buy": None, "lots": [],
                                        "stop": None, "init_stop": None, "tp1": None, "tp2": None})
        if t.side == "BUY":
            total_cost = s["cost"] * s["qty"] + float(t.price) * t.quantity + float(t.fee)
            s["qty"] += t.quantity
            s["cost"] = total_cost / s["qty"] if s["qty"] else 0.0
            s["opened"] = s["opened"] or t.trade_date
            s["last_buy"] = t.trade_date
            s["lots"].append((t.trade_date, t.quantity))
            if t.stop_loss:
                s["stop"] = t.stop_loss
                s["init_stop"] = s["init_stop"] or t.stop_loss
            if t.take_profit:
                s["tp1"] = t.take_profit
            cash -= float(t.price) * t.quantity + float(t.fee)
        elif t.side == "SELL":
            qty = min(t.quantity, s["qty"])
            proceeds = float(t.price) * qty - float(t.fee) - float(t.tax)
            s["realized"] += proceeds - s["cost"] * qty
            s["qty"] -= qty
            cash += proceeds
            if s["qty"] == 0:
                s["cost"], s["opened"], s["lots"], s["stop"], s["init_stop"], s["tp1"], s["tp2"] = 0.0, None, [], None, None, None, None
    pf.cash = cash
    for sym, s in state.items():
        avail = sum(q for d, q in s["lots"] if add_sessions(d, 2) <= today) if s["qty"] else 0
        avail = min(avail, s["qty"])
        p = existing.get(sym)
        if p is None:
            p = Position(portfolio_id=portfolio_id, symbol=sym)
            db.add(p)
        p.quantity, p.available_qty, p.avg_cost, p.realized_pnl = s["qty"], avail, s["cost"], s["realized"]
        p.opened_at, p.last_buy_at = s["opened"], s["last_buy"]
        if s["qty"] > 0:
            if p.stop_loss is None and s["stop"]:
                p.stop_loss = s["stop"]
            if p.initial_stop_loss is None and s["init_stop"]:
                p.initial_stop_loss = s["init_stop"]
            if p.take_profit_1 is None and s["tp1"]:
                p.take_profit_1 = s["tp1"]
    for sym, p in existing.items():
        if sym not in state:
            p.quantity, p.available_qty = 0, 0
    await db.flush()


async def portfolio_view(db: AsyncSession, pf: Portfolio) -> dict:
    positions = [p for p in (await db.execute(select(Position).where(Position.portfolio_id == pf.id, Position.quantity > 0))).scalars()]
    syms = [p.symbol for p in positions]
    snaps = {s.symbol: s for s in (await db.execute(select(StockSnapshot).where(StockSnapshot.symbol.in_(syms)))).scalars()} if syms else {}
    stocks = {s.symbol: s for s in (await db.execute(select(Stock).where(Stock.symbol.in_(syms)))).scalars()} if syms else {}
    views: list[PositionView] = []
    mv = 0.0
    for p in positions:
        sn = snaps.get(p.symbol)
        price = float(sn.price) if sn and sn.price else p.avg_cost
        value = price * p.quantity
        mv += value
        views.append(PositionView(
            symbol=p.symbol, quantity=p.quantity, available_qty=p.available_qty, avg_cost=p.avg_cost, price=price, value=value,
            pnl=(price - p.avg_cost) * p.quantity, pnl_pct=(price / p.avg_cost - 1) * 100 if p.avg_cost else 0.0, weight_pct=0.0,
            stop_loss=p.stop_loss, initial_stop_loss=p.initial_stop_loss, take_profit_1=p.take_profit_1, take_profit_2=p.take_profit_2,
            industry_code=(stocks.get(p.symbol).industry_code if stocks.get(p.symbol) else None),
            name=(stocks.get(p.symbol).short_name or stocks.get(p.symbol).name_vi) if stocks.get(p.symbol) else None,
            rating=sn.rating if sn else None, score=sn.score_mid if sn else None, change_pct=sn.change_pct if sn else None,
            beta=sn.beta_60 if sn else None,
            extra={"gain_from_base_pct": sn.gain_from_base_pct if sn else None, "ceiling_streak": sn.ceiling_streak if sn else None,
                   "risk_score": sn.risk_score if sn else None, "entry_low": sn.entry_low if sn else None, "entry_high": sn.entry_high if sn else None,
                   "sys_stop": sn.stop_loss if sn else None, "sys_tp1": sn.take_profit_1 if sn else None,
                   "ma20": sn.ma20 if sn else None, "vol_ratio": sn.vol_ratio if sn else None},
        ))
    cash = float(pf.cash or 0)
    nav = mv + cash
    for v in views:
        v.weight_pct = v.value / nav * 100 if nav else 0.0
    views.sort(key=lambda v: -v.value)
    unrealized = sum(v.pnl for v in views)
    sector: dict[str, float] = {}
    for v in views:
        sector[v.industry_code or "OTHER"] = sector.get(v.industry_code or "OTHER", 0.0) + v.weight_pct
    open_risk = sum(max(v.price - (v.stop_loss or v.extra.get("sys_stop") or v.price * 0.92), 0) * v.quantity for v in views)
    return {"portfolio": pf, "positions": views, "market_value": mv, "cash": cash, "nav": nav, "unrealized_pnl": unrealized,
            "sector_weights": sector, "open_risk": open_risk, "open_risk_pct": open_risk / nav * 100 if nav else 0.0}


async def nav_history(db: AsyncSession, pf: Portfolio, start: date, end: date | None = None) -> list[tuple[date, float]]:
    """Daily NAV series rebuilt from transactions and close prices (for benchmark / performance)."""
    end = end or today_vn()
    txs = (await db.execute(select(Transaction).where(Transaction.portfolio_id == pf.id, Transaction.trade_date <= end).order_by(Transaction.trade_date))).scalars().all()
    syms = sorted({t.symbol for t in txs if t.symbol})
    prices: dict[str, dict[date, float]] = {}
    if syms:
        rows = (await db.execute(select(PriceDaily.symbol, PriceDaily.trade_date, PriceDaily.close)
                                 .where(PriceDaily.symbol.in_(syms), PriceDaily.trade_date >= start - timedelta(days=10), PriceDaily.trade_date <= end))).all()
        for s, d, c in rows:
            prices.setdefault(s, {})[d] = c
    dates = sorted({d for p in prices.values() for d in p} | {t.trade_date for t in txs}) if prices else sorted({t.trade_date for t in txs})
    dates = [d for d in dates if start <= d <= end] or [end]
    out = []
    ti = 0
    cash = float(pf.initial_capital or 0)
    qty: dict[str, int] = {}
    last_px: dict[str, float] = {}
    for d in dates:
        while ti < len(txs) and txs[ti].trade_date <= d:
            t = txs[ti]
            if t.side == "BUY":
                qty[t.symbol] = qty.get(t.symbol, 0) + t.quantity
                cash -= float(t.price) * t.quantity + float(t.fee)
            elif t.side == "SELL":
                qty[t.symbol] = qty.get(t.symbol, 0) - t.quantity
                cash += float(t.price) * t.quantity - float(t.fee) - float(t.tax)
            else:
                cash += float(t.amount)
            ti += 1
        for s in qty:
            if s in prices and d in prices[s]:
                last_px[s] = prices[s][d]
        mv = sum(q * last_px.get(s, 0.0) for s, q in qty.items() if q > 0)
        out.append((d, mv + cash))
    return out


async def period_pnl(db: AsyncSession, pf: Portfolio) -> dict:
    """Week / month PnL (realized + unrealized, net of cash flows) as % of NAV — for the risk guard."""
    today = today_vn()
    ws, ms = week_start(today), month_start(today)
    series = await nav_history(db, pf, ms - timedelta(days=7), today)
    if not series:
        return {"week_pnl_pct": 0.0, "month_pnl_pct": 0.0, "week_pnl_vnd": 0.0, "month_pnl_vnd": 0.0, "nav": 0.0}
    nav_now = series[-1][1]

    def nav_before(d: date) -> float:
        prior = [v for dd, v in series if dd < d]
        return prior[-1] if prior else series[0][1]

    flows = (await db.execute(select(Transaction).where(Transaction.portfolio_id == pf.id, Transaction.side.in_(["DEPOSIT", "WITHDRAW"]), Transaction.trade_date >= ms - timedelta(days=7)))).scalars().all()
    flow_week = sum(float(t.amount) for t in flows if t.trade_date >= ws)
    flow_month = sum(float(t.amount) for t in flows if t.trade_date >= ms)
    nav_w, nav_m = nav_before(ws), nav_before(ms)
    week = nav_now - nav_w - flow_week
    month = nav_now - nav_m - flow_month
    return {"week_pnl_pct": week / nav_w * 100 if nav_w else 0.0, "month_pnl_pct": month / nav_m * 100 if nav_m else 0.0,
            "week_pnl_vnd": week, "month_pnl_vnd": month, "nav": nav_now}


async def user_real_portfolios(db: AsyncSession, user_id: uuid.UUID) -> list[Portfolio]:
    return list((await db.execute(select(Portfolio).where(Portfolio.user_id == user_id, Portfolio.is_paper.is_(False)))).scalars())

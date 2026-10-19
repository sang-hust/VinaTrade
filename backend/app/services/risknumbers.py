"""Three risk numbers for suggestions (least-risk philosophy): stop-hit odds, tail loss and money at risk for the
user's reference order size. Reads signal_reliability (strategy × market state × horizon, 20 sessions)."""

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engines.risk import risk_numbers
from app.models import MarketRegime, Portfolio, SignalReliability, User, UserRiskLimit, UserSettings

DEFAULT_REF_ORDER = 50_000_000.0


async def ref_order_vnd(db: AsyncSession, user: User) -> float:
    """Reference order = equity × max position %, equity from the real portfolio NAV, else declared capital, else 50 triệu."""
    from app.services.portfolio import portfolio_view

    lim = await db.get(UserRiskLimit, user.id)
    pos_pct = float(lim.max_position_pct) if lim and lim.max_position_pct else 20.0
    pf = (await db.execute(select(Portfolio).where(Portfolio.user_id == user.id, Portfolio.is_paper.is_(False)).order_by(Portfolio.created_at))).scalars().first()
    equity = 0.0
    if pf:
        view = await portfolio_view(db, pf)
        equity = float(view["nav"]) if view and view["nav"] > 0 else 0.0
    if equity <= 0:
        us = await db.get(UserSettings, user.id)
        equity = float(us.capital_vnd or 0) if us else 0.0
    return round(equity * pos_pct / 100) if equity > 0 else DEFAULT_REF_ORDER


async def current_regime(db: AsyncSession) -> str:
    reg = (await db.execute(select(MarketRegime).order_by(desc(MarketRegime.trade_date)).limit(1))).scalar_one_or_none()
    return reg.regime if reg else "UPTREND"


def rel_dict(r: SignalReliability | None) -> dict | None:
    if r is None:
        return None
    return {"samples": r.samples, "win_rate": r.win_rate, "stop_rate": r.stop_rate, "tp1_rate": r.tp1_rate, "p05_return": r.p05_return, "worst_return": r.worst_return,
            "avg_gain": r.avg_gain, "avg_loss": r.avg_loss}


async def numbers_for(db: AsyncSession, strategy_code: str | None, regime: str, horizon: str, price: float | None, stop_loss: float | None, order_value: float,
                      value_ma20: float | None, cache: dict | None = None) -> dict | None:
    if not strategy_code:
        return None
    key = (strategy_code, regime, horizon, 20)
    if cache is not None and key in cache:
        r = cache[key]
    else:
        r = await db.get(SignalReliability, key)
        if cache is not None:
            cache[key] = r
    return risk_numbers(rel_dict(r), price, stop_loss, order_value, value_ma20)

from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class IndicatorDaily(Base):
    __tablename__ = "indicators_daily"
    __table_args__ = (Index("ix_indicators_daily_date", "trade_date"),)

    symbol: Mapped[str] = mapped_column(String(12), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[float | None] = mapped_column(Float)
    change_pct: Mapped[float | None] = mapped_column(Float)
    ma10: Mapped[float | None] = mapped_column(Float)
    ma20: Mapped[float | None] = mapped_column(Float)
    ma50: Mapped[float | None] = mapped_column(Float)
    ma200: Mapped[float | None] = mapped_column(Float)
    ema12: Mapped[float | None] = mapped_column(Float)
    ema26: Mapped[float | None] = mapped_column(Float)
    rsi14: Mapped[float | None] = mapped_column(Float)
    macd: Mapped[float | None] = mapped_column(Float)
    macd_signal: Mapped[float | None] = mapped_column(Float)
    macd_hist: Mapped[float | None] = mapped_column(Float)
    adx14: Mapped[float | None] = mapped_column(Float)
    atr14: Mapped[float | None] = mapped_column(Float)
    bb_upper: Mapped[float | None] = mapped_column(Float)
    bb_lower: Mapped[float | None] = mapped_column(Float)
    bb_width: Mapped[float | None] = mapped_column(Float)
    obv: Mapped[float | None] = mapped_column(Float)
    mfi14: Mapped[float | None] = mapped_column(Float)
    cmf20: Mapped[float | None] = mapped_column(Float)
    stoch_k: Mapped[float | None] = mapped_column(Float)
    stoch_d: Mapped[float | None] = mapped_column(Float)
    vol_ma20: Mapped[float | None] = mapped_column(Float)
    vol_ratio: Mapped[float | None] = mapped_column(Float)
    value_ma20: Mapped[float | None] = mapped_column(Float)
    rs_rating: Mapped[float | None] = mapped_column(Float)
    trend_state: Mapped[str | None] = mapped_column(String(12))
    support_1: Mapped[float | None] = mapped_column(Float)
    resistance_1: Mapped[float | None] = mapped_column(Float)
    high_52w: Mapped[float | None] = mapped_column(Float)
    low_52w: Mapped[float | None] = mapped_column(Float)
    dist_ma50_pct: Mapped[float | None] = mapped_column(Float)
    ma50_slope: Mapped[float | None] = mapped_column(Float)
    ma200_slope: Mapped[float | None] = mapped_column(Float)
    ceiling_streak: Mapped[int | None] = mapped_column(Integer)
    distribution_days: Mapped[int | None] = mapped_column(Integer)


class PriceBase(Base):
    __tablename__ = "price_bases"
    __table_args__ = (Index("ix_price_bases_symbol_status", "symbol", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(12))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    base_high: Mapped[float] = mapped_column(Float)
    base_low: Mapped[float] = mapped_column(Float)
    depth_pct: Mapped[float] = mapped_column(Float)
    length_days: Mapped[int] = mapped_column(Integer)
    tightness_pct: Mapped[float | None] = mapped_column(Float)
    vol_dry_ratio: Mapped[float | None] = mapped_column(Float)
    avg_volume: Mapped[float | None] = mapped_column(Float)
    pattern: Mapped[str | None] = mapped_column(String(16))  # FLAT | CUP_HANDLE | DOUBLE_BOTTOM | VCP
    status: Mapped[str] = mapped_column(String(12), default="FORMING")  # FORMING | BROKEN_OUT | FAILED
    breakout_date: Mapped[date | None] = mapped_column(Date)
    breakout_vol_ratio: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Rally(Base):
    __tablename__ = "rallies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    base_id: Mapped[int | None] = mapped_column(ForeignKey("price_bases.id", ondelete="SET NULL"))
    start_date: Mapped[date] = mapped_column(Date)
    peak_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    base_high: Mapped[float] = mapped_column(Float)
    peak_price: Mapped[float | None] = mapped_column(Float)
    gain_pct: Mapped[float | None] = mapped_column(Float)
    days_to_peak: Mapped[int | None] = mapped_column(Integer)
    peak_vol_ratio: Mapped[float | None] = mapped_column(Float)
    distribution_days: Mapped[int | None] = mapped_column(Integer)
    pullback_pct: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), default="ONGOING")  # ONGOING | COMPLETED


class RallyStat(Base):
    __tablename__ = "rally_stats"

    symbol: Mapped[str] = mapped_column(String(12), primary_key=True)
    rally_count: Mapped[int] = mapped_column(Integer, default=0)
    median_gain_pct: Mapped[float | None] = mapped_column(Float)
    p75_gain_pct: Mapped[float | None] = mapped_column(Float)
    mean_gain_pct: Mapped[float | None] = mapped_column(Float)
    median_days: Mapped[float | None] = mapped_column(Float)
    median_peak_vol_ratio: Mapped[float | None] = mapped_column(Float)
    median_pullback_pct: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MarketRegime(Base):
    __tablename__ = "market_regime"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    regime: Mapped[str] = mapped_column(String(16))  # UPTREND | PRESSURE | CORRECTION | DOWNTREND
    max_equity_pct: Mapped[int] = mapped_column(Integer, default=80)
    vnindex: Mapped[float | None] = mapped_column(Float)
    vnindex_change_pct: Mapped[float | None] = mapped_column(Float)
    pct_above_ma50: Mapped[float | None] = mapped_column(Float)
    pct_above_ma200: Mapped[float | None] = mapped_column(Float)
    advances: Mapped[int | None] = mapped_column(Integer)
    declines: Mapped[int | None] = mapped_column(Integer)
    distribution_days: Mapped[int | None] = mapped_column(Integer)
    liquidity_ratio: Mapped[float | None] = mapped_column(Float)  # value / value_ma20
    headline: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)
    facts: Mapped[dict | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class StockScore(Base):
    __tablename__ = "stock_scores"
    __table_args__ = (Index("ix_stock_scores_date", "trade_date"),)

    symbol: Mapped[str] = mapped_column(String(12), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    tech: Mapped[float | None] = mapped_column(Float)
    tech_trend: Mapped[float | None] = mapped_column(Float)
    tech_momentum: Mapped[float | None] = mapped_column(Float)
    tech_volume: Mapped[float | None] = mapped_column(Float)
    tech_rs: Mapped[float | None] = mapped_column(Float)
    tech_pattern: Mapped[float | None] = mapped_column(Float)
    fund: Mapped[float | None] = mapped_column(Float)
    fund_growth: Mapped[float | None] = mapped_column(Float)
    fund_profitability: Mapped[float | None] = mapped_column(Float)
    fund_health: Mapped[float | None] = mapped_column(Float)
    fund_valuation: Mapped[float | None] = mapped_column(Float)
    sector: Mapped[float | None] = mapped_column(Float)
    pattern_ai: Mapped[float | None] = mapped_column(Float)
    score_short: Mapped[float | None] = mapped_column(Float)
    score_mid: Mapped[float | None] = mapped_column(Float)
    score_long: Mapped[float | None] = mapped_column(Float)
    rating_short: Mapped[str | None] = mapped_column(String(12))
    rating_mid: Mapped[str | None] = mapped_column(String(12))
    rating_long: Mapped[str | None] = mapped_column(String(12))
    trend_short: Mapped[str | None] = mapped_column(String(4))  # UP | FLAT | DOWN
    trend_mid: Mapped[str | None] = mapped_column(String(4))
    trend_long: Mapped[str | None] = mapped_column(String(4))
    entry_low: Mapped[float | None] = mapped_column(Float)
    entry_high: Mapped[float | None] = mapped_column(Float)
    stop_loss: Mapped[float | None] = mapped_column(Float)
    take_profit_1: Mapped[float | None] = mapped_column(Float)
    take_profit_2: Mapped[float | None] = mapped_column(Float)
    risk_reward: Mapped[float | None] = mapped_column(Float)
    reasons: Mapped[list | None] = mapped_column(JSON)
    drawbacks: Mapped[list | None] = mapped_column(JSON)
    # total risk (6 components, engines.risk.total_risk) and risk-adjusted ranking scores
    risk_total: Mapped[float | None] = mapped_column(Float)
    risk_total_level: Mapped[str | None] = mapped_column(String(8))  # LOW | MEDIUM | HIGH
    risk_components: Mapped[list | None] = mapped_column(JSON)
    score_adj_short: Mapped[float | None] = mapped_column(Float)
    score_adj_mid: Mapped[float | None] = mapped_column(Float)
    score_adj_long: Mapped[float | None] = mapped_column(Float)


class Strategy(Base):
    __tablename__ = "strategies"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    signal_type: Mapped[str] = mapped_column(String(16))  # BUY | SELL | STOP_LOSS | TAKE_PROFIT | WATCH
    horizon: Mapped[str] = mapped_column(String(8))  # SHORT | MID | LONG
    description: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict | None] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    backtest_years: Mapped[float | None] = mapped_column(Float)
    win_rate: Mapped[float | None] = mapped_column(Float)
    avg_return: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    trades: Mapped[int | None] = mapped_column(Integer)
    # Draft version (A03): params being edited + backtest comparison; becomes live via /admin/strategies/{code}/activate-draft
    draft_params: Mapped[dict | None] = mapped_column(JSON)
    draft_backtest: Mapped[dict | None] = mapped_column(JSON)
    draft_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        Index("ix_signals_symbol_date", "symbol", "trade_date"),
        Index("ix_signals_date", "trade_date"),
        Index("ux_signals_dedupe", "dedupe_key", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(12))
    trade_date: Mapped[date] = mapped_column(Date)
    strategy_code: Mapped[str] = mapped_column(ForeignKey("strategies.code"))
    signal_type: Mapped[str] = mapped_column(String(16))
    horizon: Mapped[str] = mapped_column(String(8))
    rating: Mapped[str | None] = mapped_column(String(12))
    score: Mapped[float | None] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    entry_low: Mapped[float | None] = mapped_column(Float)
    entry_high: Mapped[float | None] = mapped_column(Float)
    stop_loss: Mapped[float | None] = mapped_column(Float)
    take_profit_1: Mapped[float | None] = mapped_column(Float)
    take_profit_2: Mapped[float | None] = mapped_column(Float)
    risk_reward: Mapped[float | None] = mapped_column(Float)
    priority: Mapped[str] = mapped_column(String(8), default="HIGH")  # URGENT | HIGH | INFO
    regime_at_signal: Mapped[str | None] = mapped_column(String(16))
    reliability_pct: Mapped[float | None] = mapped_column(Float)
    reliability_samples: Mapped[int | None] = mapped_column(Integer)
    stand_aside: Mapped[bool] = mapped_column(Boolean, default=False)
    is_chase: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_score: Mapped[float | None] = mapped_column(Float)
    title: Mapped[str] = mapped_column(String(255))
    reasons: Mapped[list | None] = mapped_column(JSON)
    facts: Mapped[dict | None] = mapped_column(JSON)
    dedupe_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SignalOutcome(Base):
    __tablename__ = "signal_outcomes"

    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id", ondelete="CASCADE"), primary_key=True)
    days: Mapped[int] = mapped_column(Integer, primary_key=True)  # 5 | 10 | 20 | 60
    return_pct: Mapped[float | None] = mapped_column(Float)
    max_gain_pct: Mapped[float | None] = mapped_column(Float)
    max_loss_pct: Mapped[float | None] = mapped_column(Float)
    hit_tp1: Mapped[bool | None] = mapped_column(Boolean)
    hit_stop: Mapped[bool | None] = mapped_column(Boolean)
    result: Mapped[str | None] = mapped_column(String(12))  # TP_HIT | STOP_HIT | WIN | LOSS | OPEN
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SignalReliability(Base):
    __tablename__ = "signal_reliability"

    strategy_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    regime: Mapped[str] = mapped_column(String(16), primary_key=True)
    horizon: Mapped[str] = mapped_column(String(8), primary_key=True)
    days: Mapped[int] = mapped_column(Integer, primary_key=True)
    samples: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[float | None] = mapped_column(Float)
    avg_return: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CompanyRiskScore(Base):
    __tablename__ = "company_risk_scores"

    symbol: Mapped[str] = mapped_column(String(12), primary_key=True)
    as_of: Mapped[date] = mapped_column(Date)
    score: Mapped[float] = mapped_column(Float, default=0)
    level: Mapped[str] = mapped_column(String(8), default="LOW")  # LOW | MEDIUM | HIGH
    flags: Mapped[list | None] = mapped_column(JSON)  # [{code, text, points, source}]
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SectorScore(Base):
    __tablename__ = "sector_scores"

    industry_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    score: Mapped[float | None] = mapped_column(Float)
    perf_1w: Mapped[float | None] = mapped_column(Float)
    perf_1m: Mapped[float | None] = mapped_column(Float)
    perf_3m: Mapped[float | None] = mapped_column(Float)
    money_flow: Mapped[float | None] = mapped_column(Float)
    breadth: Mapped[float | None] = mapped_column(Float)
    stock_count: Mapped[int | None] = mapped_column(Integer)
    leaders: Mapped[list | None] = mapped_column(JSON)
    macro_note: Mapped[str | None] = mapped_column(Text)


class StockSnapshot(Base):
    """One row per symbol with the latest values of every screener/alert DSL field (spec: v_stock_snapshot)."""

    __tablename__ = "stock_snapshots"
    __table_args__ = (
        Index("ix_snap_exchange", "exchange"),
        Index("ix_snap_industry", "industry_code"),
        Index("ix_snap_score_mid", "score_mid"),
        Index("ix_snap_score_adj_mid", "score_adj_mid"),
    )

    symbol: Mapped[str] = mapped_column(String(12), primary_key=True)
    trade_date: Mapped[date | None] = mapped_column(Date)
    exchange: Mapped[str | None] = mapped_column(String(8))
    industry_code: Mapped[str | None] = mapped_column(String(8))
    in_vn30: Mapped[bool | None] = mapped_column(Boolean)
    price: Mapped[float | None] = mapped_column(Float)
    change: Mapped[float | None] = mapped_column(Float)
    change_pct: Mapped[float | None] = mapped_column(Float)
    ref_price: Mapped[float | None] = mapped_column(Float)
    ceiling: Mapped[float | None] = mapped_column(Float)
    floor: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    value: Mapped[float | None] = mapped_column(Float)
    vol_ratio: Mapped[float | None] = mapped_column(Float)
    value_ma20: Mapped[float | None] = mapped_column(Float)
    high_52w: Mapped[float | None] = mapped_column(Float)
    low_52w: Mapped[float | None] = mapped_column(Float)
    ma10: Mapped[float | None] = mapped_column(Float)
    ma20: Mapped[float | None] = mapped_column(Float)
    ma50: Mapped[float | None] = mapped_column(Float)
    ma200: Mapped[float | None] = mapped_column(Float)
    rsi14: Mapped[float | None] = mapped_column(Float)
    macd: Mapped[float | None] = mapped_column(Float)
    macd_signal: Mapped[float | None] = mapped_column(Float)
    macd_hist: Mapped[float | None] = mapped_column(Float)
    adx14: Mapped[float | None] = mapped_column(Float)
    atr14: Mapped[float | None] = mapped_column(Float)
    bb_upper: Mapped[float | None] = mapped_column(Float)
    bb_lower: Mapped[float | None] = mapped_column(Float)
    bb_width: Mapped[float | None] = mapped_column(Float)
    mfi14: Mapped[float | None] = mapped_column(Float)
    cmf20: Mapped[float | None] = mapped_column(Float)
    stoch_k: Mapped[float | None] = mapped_column(Float)
    rs_rating: Mapped[float | None] = mapped_column(Float)
    trend_state: Mapped[str | None] = mapped_column(String(12))
    support_1: Mapped[float | None] = mapped_column(Float)
    resistance_1: Mapped[float | None] = mapped_column(Float)
    dist_ma50_pct: Mapped[float | None] = mapped_column(Float)
    ma50_slope: Mapped[float | None] = mapped_column(Float)
    ceiling_streak: Mapped[int | None] = mapped_column(Integer)
    golden_cross_days: Mapped[int | None] = mapped_column(Integer)  # sessions since MA50 crossed above MA200 (null if none)
    death_cross_days: Mapped[int | None] = mapped_column(Integer)
    pe: Mapped[float | None] = mapped_column(Float)
    pb: Mapped[float | None] = mapped_column(Float)
    ps: Mapped[float | None] = mapped_column(Float)
    peg: Mapped[float | None] = mapped_column(Float)
    market_cap: Mapped[float | None] = mapped_column(Float)
    fair_value: Mapped[float | None] = mapped_column(Float)
    margin_of_safety: Mapped[float | None] = mapped_column(Float)
    dividend_yield: Mapped[float | None] = mapped_column(Float)
    roe: Mapped[float | None] = mapped_column(Float)
    roa: Mapped[float | None] = mapped_column(Float)
    gross_margin: Mapped[float | None] = mapped_column(Float)
    net_margin: Mapped[float | None] = mapped_column(Float)
    debt_to_equity: Mapped[float | None] = mapped_column(Float)
    current_ratio: Mapped[float | None] = mapped_column(Float)
    revenue_yoy: Mapped[float | None] = mapped_column(Float)
    profit_yoy: Mapped[float | None] = mapped_column(Float)
    revenue_cagr_3y: Mapped[float | None] = mapped_column(Float)
    profit_cagr_3y: Mapped[float | None] = mapped_column(Float)
    cfo_to_profit: Mapped[float | None] = mapped_column(Float)
    score_short: Mapped[float | None] = mapped_column(Float)
    score_mid: Mapped[float | None] = mapped_column(Float)
    score_long: Mapped[float | None] = mapped_column(Float)
    rating_short: Mapped[str | None] = mapped_column(String(12))
    rating_mid: Mapped[str | None] = mapped_column(String(12))
    rating_long: Mapped[str | None] = mapped_column(String(12))
    rating: Mapped[str | None] = mapped_column(String(12))  # = rating_mid (default horizon)
    trend_short: Mapped[str | None] = mapped_column(String(4))
    trend_mid: Mapped[str | None] = mapped_column(String(4))
    trend_long: Mapped[str | None] = mapped_column(String(4))
    base_status: Mapped[str | None] = mapped_column(String(12))
    base_length_days: Mapped[int | None] = mapped_column(Integer)
    base_tightness: Mapped[float | None] = mapped_column(Float)
    base_high: Mapped[float | None] = mapped_column(Float)
    gain_from_base_pct: Mapped[float | None] = mapped_column(Float)
    rally_gain_vs_median: Mapped[float | None] = mapped_column(Float)
    risk_score: Mapped[float | None] = mapped_column(Float)
    risk_level: Mapped[str | None] = mapped_column(String(8))
    beta_60: Mapped[float | None] = mapped_column(Float)
    earnings_in_days: Mapped[int | None] = mapped_column(Integer)
    is_chase: Mapped[bool | None] = mapped_column(Boolean)
    signals_today: Mapped[list | None] = mapped_column(JSON)  # [{"code","type"}] signals in last 3 sessions
    entry_low: Mapped[float | None] = mapped_column(Float)
    entry_high: Mapped[float | None] = mapped_column(Float)
    stop_loss: Mapped[float | None] = mapped_column(Float)
    take_profit_1: Mapped[float | None] = mapped_column(Float)
    foreign_net_5d: Mapped[float | None] = mapped_column(Float)  # VND
    foreign_net_20d: Mapped[float | None] = mapped_column(Float)
    foreign_net_today: Mapped[float | None] = mapped_column(Float)
    prop_net_5d: Mapped[float | None] = mapped_column(Float)
    foreign_room_pct: Mapped[float | None] = mapped_column(Float)
    insider_net_90d: Mapped[float | None] = mapped_column(Float)  # VND, negative = net selling
    insider_pending_sell: Mapped[float | None] = mapped_column(Float)  # registered sells not yet done, shares
    consensus_target: Mapped[float | None] = mapped_column(Float)
    consensus_upside_pct: Mapped[float | None] = mapped_column(Float)
    consensus_count: Mapped[int | None] = mapped_column(Integer)
    news_sentiment_7d: Mapped[float | None] = mapped_column(Float)
    news_count_7d: Mapped[int | None] = mapped_column(Integer)
    next_event: Mapped[dict | None] = mapped_column(JSON)
    risk_total: Mapped[float | None] = mapped_column(Float)
    risk_total_level: Mapped[str | None] = mapped_column(String(8))
    risk_components: Mapped[list | None] = mapped_column(JSON)
    score_adj_short: Mapped[float | None] = mapped_column(Float)
    score_adj_mid: Mapped[float | None] = mapped_column(Float)
    score_adj_long: Mapped[float | None] = mapped_column(Float)
    rating_changed: Mapped[bool | None] = mapped_column(Boolean)
    prev_rating: Mapped[str | None] = mapped_column(String(12))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

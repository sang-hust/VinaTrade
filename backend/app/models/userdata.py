import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    watchlist_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12), primary_key=True)
    note: Mapped[str | None] = mapped_column(String(255))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Screener(Base):
    __tablename__ = "screeners"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code: Mapped[str | None] = mapped_column(String(32), unique=True)  # system presets only
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(255))
    group: Mapped[str | None] = mapped_column(String(12))  # TECH | FUND | AVOID (presets)
    horizon: Mapped[str] = mapped_column(String(8), default="MID")
    conditions: Mapped[dict] = mapped_column(JSON)
    form_state: Mapped[dict | None] = mapped_column(JSON)
    is_preset: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_new: Mapped[bool] = mapped_column(Boolean, default=False)
    last_result: Mapped[dict | None] = mapped_column(JSON)  # {"count": n, "symbols": [...], "date": "..."}
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    scope_type: Mapped[str] = mapped_column(String(12))  # SYMBOL | WATCHLIST | PORTFOLIO | SCREENER | MARKET
    scope_id: Mapped[str | None] = mapped_column(String(64))
    conditions: Mapped[dict] = mapped_column(JSON)
    template: Mapped[str | None] = mapped_column(String(32))  # ENTRY_ZONE | RATING_CHANGE | STOP_OR_TP | BREAKOUT | RSI | PRICE
    timing: Mapped[str] = mapped_column(String(8), default="EOD")  # INTRADAY | EOD | BOTH
    priority: Mapped[str] = mapped_column(String(8), default="HIGH")
    channels: Mapped[list] = mapped_column(JSON, default=list)  # ["push","telegram","email"]
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=1440)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    rule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("alert_rules.id", ondelete="SET NULL"))
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id", ondelete="SET NULL"))
    symbol: Mapped[str | None] = mapped_column(String(12))
    kind: Mapped[str] = mapped_column(String(20))  # SIGNAL | RATING_CHANGE | PRICE | PORTFOLIO | GUARD | PLAN | SYSTEM | REPORT
    priority: Mapped[str] = mapped_column(String(8), default="HIGH")  # URGENT | HIGH | INFO
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str | None] = mapped_column(Text)
    deeplink: Mapped[str | None] = mapped_column(String(255))
    data: Mapped[dict | None] = mapped_column(JSON)
    dedupe_key: Mapped[str | None] = mapped_column(String(96), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(12))  # push | telegram | email | inapp
    status: Mapped[str] = mapped_column(String(12), default="PENDING")  # PENDING | SENT | FAILED | SKIPPED
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(255))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    broker: Mapped[str | None] = mapped_column(String(32))
    is_paper: Mapped[bool] = mapped_column(Boolean, default=False)
    uses_margin: Mapped[bool] = mapped_column(Boolean, default=False)
    cash: Mapped[float] = mapped_column(Numeric(18, 0), default=0)
    initial_capital: Mapped[float] = mapped_column(Numeric(18, 0), default=0)
    fee_pct: Mapped[float] = mapped_column(Numeric(6, 4), default=0.15)
    tax_pct: Mapped[float] = mapped_column(Numeric(6, 4), default=0.1)
    position_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (Index("ix_tx_portfolio_date", "portfolio_id", "trade_date"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"))
    symbol: Mapped[str | None] = mapped_column(String(12))
    side: Mapped[str] = mapped_column(String(10))  # BUY | SELL | DIVIDEND | DEPOSIT | WITHDRAW
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    fee: Mapped[float] = mapped_column(Numeric(14, 0), default=0)
    tax: Mapped[float] = mapped_column(Numeric(14, 0), default=0)
    amount: Mapped[float] = mapped_column(Numeric(18, 0), default=0)  # cash effect (+ in, − out)
    trade_date: Mapped[date] = mapped_column(Date)
    stop_loss: Mapped[float | None] = mapped_column(Float)
    take_profit: Mapped[float | None] = mapped_column(Float)
    pretrade_check_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pretrade_checks.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    emotion: Mapped[str | None] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Position(Base):
    __tablename__ = "positions"

    portfolio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12), primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    available_qty: Mapped[int] = mapped_column(Integer, default=0)  # T+2
    avg_cost: Mapped[float] = mapped_column(Float, default=0)
    stop_loss: Mapped[float | None] = mapped_column(Float)
    initial_stop_loss: Mapped[float | None] = mapped_column(Float)
    take_profit_1: Mapped[float | None] = mapped_column(Float)
    take_profit_2: Mapped[float | None] = mapped_column(Float)
    opened_at: Mapped[date | None] = mapped_column(Date)
    last_buy_at: Mapped[date | None] = mapped_column(Date)
    realized_pnl: Mapped[float] = mapped_column(Numeric(18, 0), default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PortfolioMargin(Base):
    __tablename__ = "portfolio_margin"

    portfolio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), primary_key=True)
    loan: Mapped[float] = mapped_column(Numeric(18, 0), default=0)
    call_ratio: Mapped[float] = mapped_column(Float, default=0.35)
    force_sell_ratio: Mapped[float] = mapped_column(Float, default=0.30)
    interest_pct: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TradeJournal(Base):
    __tablename__ = "trade_journal"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("transactions.id", ondelete="SET NULL"))
    symbol: Mapped[str | None] = mapped_column(String(12))
    entry_reason: Mapped[str | None] = mapped_column(Text)
    emotion: Mapped[str | None] = mapped_column(String(24))
    lesson: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PretradeCheck(Base):
    __tablename__ = "pretrade_checks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    portfolio_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(12))
    horizon: Mapped[str] = mapped_column(String(8), default="MID")
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float | None] = mapped_column(Float)
    take_profit: Mapped[float | None] = mapped_column(Float)
    result: Mapped[str] = mapped_column(String(8))  # GREEN | YELLOW | RED
    items: Mapped[list] = mapped_column(JSON)
    suggested_qty: Mapped[int | None] = mapped_column(Integer)
    override_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TradePlan(Base):
    __tablename__ = "trade_plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    portfolio_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(12))
    name: Mapped[str] = mapped_column(String(120))
    template: Mapped[str | None] = mapped_column(String(32))  # BREAKOUT_3 | BUY_SUPPORT | SCALE_OUT
    status: Mapped[str] = mapped_column(String(12), default="ACTIVE")  # ACTIVE | PAUSED | DONE | CANCELLED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TradePlanStep(Base):
    __tablename__ = "trade_plan_steps"

    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trade_plans.id", ondelete="CASCADE"), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    condition: Mapped[dict] = mapped_column(JSON)  # DSL
    action: Mapped[str] = mapped_column(String(16))  # BUY | SELL | TAKE_PROFIT | MOVE_STOP | STOP_LOSS
    fraction: Mapped[float | None] = mapped_column(Float)  # 1/3 etc.
    price: Mapped[float | None] = mapped_column(Float)
    new_stop: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), default="WAITING")  # WAITING | TRIGGERED | DONE | SKIPPED
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("transactions.id", ondelete="SET NULL"))


class ActionItem(Base):
    __tablename__ = "action_items"
    __table_args__ = (Index("ix_action_items_pf_status", "portfolio_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"))
    priority: Mapped[str] = mapped_column(String(8))  # URGENT | RISK | SUGGEST
    kind: Mapped[str] = mapped_column(String(20))  # GUARD_ON | MAX_LOSS | STOP_BROKEN | CHASE | TAKE_PROFIT | PLAN_STEP | ADD_ON | CORRELATED | CONCENTRATION
    symbol: Mapped[str | None] = mapped_column(String(12))
    title: Mapped[str] = mapped_column(String(255))
    detail: Mapped[str | None] = mapped_column(Text)
    actions: Mapped[list] = mapped_column(JSON)  # [{"code","label","params"}] max 2
    rank_score: Mapped[float] = mapped_column(Float, default=0)
    impact_vnd: Mapped[float | None] = mapped_column(Float)
    dedupe_key: Mapped[str] = mapped_column(String(96))
    status: Mapped[str] = mapped_column(String(12), default="OPEN")  # OPEN | DONE | DISMISSED | EXPIRED
    result_text: Mapped[str | None] = mapped_column(String(255))
    hide_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CoachReport(Base):
    __tablename__ = "coach_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    week_start: Mapped[date] = mapped_column(Date)
    metrics: Mapped[dict | None] = mapped_column(JSON)
    insights: Mapped[list | None] = mapped_column(JSON)
    rule: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    benchmark: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiConversation(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str | None] = mapped_column(String(160))
    context: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AiMessage(Base):
    __tablename__ = "ai_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(12))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[list | None] = mapped_column(JSON)
    data_cards: Mapped[list | None] = mapped_column(JSON)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

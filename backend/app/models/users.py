import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

# User status: PENDING (chờ kích hoạt) | ACTIVE | LOCKED | REJECTED | EXPIRED
# Roles: ADMIN | MEMBER


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20))
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="MEMBER")
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_devices: Mapped[int] = mapped_column(Integer, default=3)
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(32))
    telegram_link_code: Mapped[str | None] = mapped_column(String(16))
    invited_by_code: Mapped[str | None] = mapped_column(String(16))
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reset_token_hash: Mapped[str | None] = mapped_column(String(64))
    reset_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    settings: Mapped["UserSettings"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    risk_limits: Mapped["UserRiskLimit"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    guard: Mapped["RiskGuardStatus"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")

    @property
    def is_active(self) -> bool:
        if self.status != "ACTIVE":
            return False
        if self.expires_at and self.expires_at < datetime.now(self.expires_at.tzinfo):
            return False
        return True


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    ui_detail: Mapped[str] = mapped_column(String(12), default="STANDARD")  # SIMPLE | STANDARD | FULL
    theme: Mapped[str] = mapped_column(String(8), default="dark")  # dark | light | system
    default_horizon: Mapped[str] = mapped_column(String(8), default="MID")  # SHORT | MID | LONG
    experience_level: Mapped[str | None] = mapped_column(String(12))  # NEW | MID | PRO
    holding_period: Mapped[str | None] = mapped_column(String(12))  # DAYS | WEEKS | YEARS
    capital_band: Mapped[str | None] = mapped_column(String(12))  # LT200M | 200M_1B | 1B_3B | GT3B
    capital_vnd: Mapped[int | None] = mapped_column(Numeric(18, 0))
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    onboarding_skips: Mapped[int] = mapped_column(Integer, default=0)
    notify_push: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_telegram: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_email: Mapped[bool] = mapped_column(Boolean, default=False)
    quiet_start: Mapped[str | None] = mapped_column(String(5), default="22:00")
    quiet_end: Mapped[str | None] = mapped_column(String(5), default="07:00")
    max_alerts_per_day: Mapped[int] = mapped_column(Integer, default=40)
    brokers: Mapped[list | None] = mapped_column(JSON, default=list)  # ["VCBS", "Pinetree"]
    reduce_motion: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="settings")


class UserRiskLimit(Base):
    __tablename__ = "user_risk_limits"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    max_risk_per_trade_pct: Mapped[float] = mapped_column(Numeric(6, 3), default=1.5)
    stop_loss_pct: Mapped[float] = mapped_column(Numeric(6, 3), default=8.0)
    max_position_pct: Mapped[float] = mapped_column(Numeric(6, 3), default=20.0)
    max_sector_pct: Mapped[float] = mapped_column(Numeric(6, 3), default=40.0)
    max_correlated_group_pct: Mapped[float] = mapped_column(Numeric(6, 3), default=40.0)
    weekly_loss_limit_pct: Mapped[float] = mapped_column(Numeric(6, 3), default=3.0)
    monthly_loss_limit_pct: Mapped[float] = mapped_column(Numeric(6, 3), default=6.0)
    cooldown_sessions: Mapped[int] = mapped_column(Integer, default=5)
    min_risk_reward: Mapped[float] = mapped_column(Numeric(5, 2), default=2.0)
    max_open_risk_pct: Mapped[float] = mapped_column(Numeric(6, 3), default=6.0)  # portfolio heat: sum of (price − stop) × qty ≤ this % of NAV
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="risk_limits")


class RiskGuardStatus(Base):
    __tablename__ = "risk_guard_status"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    mode: Mapped[str] = mapped_column(String(12), default="NORMAL")  # NORMAL | DEFENSIVE
    week_pnl_pct: Mapped[float] = mapped_column(Numeric(8, 3), default=0)
    month_pnl_pct: Mapped[float] = mapped_column(Numeric(8, 3), default=0)
    week_pnl_vnd: Mapped[float] = mapped_column(Numeric(18, 0), default=0)
    month_pnl_vnd: Mapped[float] = mapped_column(Numeric(18, 0), default=0)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release_at: Mapped[date | None] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # drawdown de-risking: NAV vs 180-day peak; equity_cap_pct caps stock exposure (None = no cap)
    drawdown_pct: Mapped[float | None] = mapped_column(Numeric(8, 3))
    peak_nav: Mapped[float | None] = mapped_column(Numeric(18, 0))
    equity_cap_pct: Mapped[float | None] = mapped_column(Numeric(6, 2))

    user: Mapped[User] = relationship(back_populates="guard")


class RiskGuardEvent(Base):
    __tablename__ = "risk_guard_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24))  # GUARD_ON | GUARD_OFF | STOP_LOWERED | AVERAGE_DOWN | RED_OVERRIDE | CHASE_BUY
    symbol: Mapped[str | None] = mapped_column(String(12))
    detail: Mapped[dict | None] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserDevice(Base):
    __tablename__ = "user_devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(16), default="web")  # web | windows | ios | android | macos
    name: Mapped[str | None] = mapped_column(String(120))
    push_token: Mapped[str | None] = mapped_column(String(512))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    admin_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # last admin-console request (30-minute idle lock, UI 15)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user_devices.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Invitation(Base):
    __tablename__ = "invitations"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    email: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(String(255))
    auto_activate: Mapped[bool] = mapped_column(Boolean, default=False)
    valid_months: Mapped[int | None] = mapped_column(Integer)  # account validity after activation
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_email: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(48), index=True)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORM


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=120)
    phone: str | None = None
    invite_code: str | None = None
    platform: str = "web"
    device_name: str | None = None


class LoginIn(BaseModel):
    email: str = Field(min_length=1, max_length=255)  # email, or a short username → <username>@vinatrade.vn
    password: str
    totp: str | None = None
    platform: str = "web"
    device_name: str | None = None


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: "UserOut"


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)


class TotpVerifyIn(BaseModel):
    code: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class SettingsOut(ORM):
    ui_detail: str
    theme: str
    default_horizon: str
    experience_level: str | None
    holding_period: str | None
    capital_band: str | None
    capital_vnd: float | None
    onboarded_at: datetime | None
    notify_push: bool
    notify_telegram: bool
    notify_email: bool
    quiet_start: str | None
    quiet_end: str | None
    max_alerts_per_day: int
    brokers: list | None
    reduce_motion: bool


class SettingsIn(BaseModel):
    ui_detail: str | None = None
    theme: str | None = None
    default_horizon: str | None = None
    notify_push: bool | None = None
    notify_telegram: bool | None = None
    notify_email: bool | None = None
    quiet_start: str | None = None
    quiet_end: str | None = None
    max_alerts_per_day: int | None = None
    brokers: list[str] | None = None
    reduce_motion: bool | None = None
    capital_vnd: float | None = None


class RiskLimitsOut(ORM):
    max_risk_per_trade_pct: float
    stop_loss_pct: float
    max_position_pct: float
    max_sector_pct: float
    max_correlated_group_pct: float
    weekly_loss_limit_pct: float
    monthly_loss_limit_pct: float
    cooldown_sessions: int
    min_risk_reward: float
    max_open_risk_pct: float = 6.0


class RiskLimitsIn(BaseModel):
    max_risk_per_trade_pct: float | None = None
    stop_loss_pct: float | None = None
    max_position_pct: float | None = None
    max_sector_pct: float | None = None
    max_correlated_group_pct: float | None = None
    weekly_loss_limit_pct: float | None = None
    monthly_loss_limit_pct: float | None = None
    cooldown_sessions: int | None = None
    min_risk_reward: float | None = None
    max_open_risk_pct: float | None = None


class GuardOut(ORM):
    mode: str
    week_pnl_pct: float
    month_pnl_pct: float
    week_pnl_vnd: float
    month_pnl_vnd: float
    triggered_at: datetime | None
    release_at: datetime | None
    reason: str | None
    evaluated_at: datetime | None
    drawdown_pct: float | None = None
    peak_nav: float | None = None
    equity_cap_pct: float | None = None


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str
    phone: str | None
    role: str
    status: str
    expires_at: datetime | None
    totp_enabled: bool
    telegram_chat_id: str | None
    created_at: datetime
    last_login_at: datetime | None


class MeOut(BaseModel):
    user: UserOut
    settings: SettingsOut | None
    risk_limits: RiskLimitsOut | None
    guard: GuardOut | None
    needs_onboarding: bool
    ai_questions_left: int
    unread_alerts: int


class OnboardingIn(BaseModel):
    experience: str  # NEW | MID | PRO
    holding: str  # DAYS | WEEKS | YEARS
    max_loss: str  # P5 | P8 | P10
    symbols: list[str] = []
    capital_band: str | None = None  # LT200M | 200M_1B | 1B_3B | GT3B | SKIP


class DeviceOut(ORM):
    id: uuid.UUID
    platform: str
    name: str | None
    last_seen_at: datetime
    created_at: datetime


class PushTokenIn(BaseModel):
    token: str
    platform: str = "android"


TokenOut.model_rebuild()

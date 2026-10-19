import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import DB, AnyUser, CurrentUser, audit
from app.core.config import settings
from app.core.errors import bad_request, not_found
from app.models import Alert, Stock, UserDevice, UserSettings, Watchlist, WatchlistItem
from app.schemas.auth import (
    DeviceOut,
    GuardOut,
    MeOut,
    OnboardingIn,
    PushTokenIn,
    RiskLimitsIn,
    RiskLimitsOut,
    SettingsIn,
    SettingsOut,
    UserOut,
)
from app.schemas.common import Ok
from app.services.ai import daily_usage
from app.services.riskguard import ensure_user_defaults
from app.services.sysconfig import get_config

router = APIRouter(prefix="/me", tags=["me"])

EXPERIENCE_DETAIL = {"NEW": "SIMPLE", "MID": "STANDARD", "PRO": "FULL"}
HOLDING_HORIZON = {"DAYS": "SHORT", "WEEKS": "MID", "YEARS": "LONG"}
LOSS_PCT = {"P5": (5.0, 1.0), "P8": (8.0, 1.5), "P10": (10.0, 2.0)}  # stop %, risk per trade %
CAPITAL = {"LT200M": 150_000_000, "200M_1B": 500_000_000, "1B_3B": 2_000_000_000, "GT3B": 5_000_000_000}


@router.get("", response_model=MeOut)
async def me(user: AnyUser, db: DB):
    s = await db.get(UserSettings, user.id)
    if s is None:
        s = UserSettings(user_id=user.id)
        db.add(s)
        await db.flush()
    lim, g = await ensure_user_defaults(db, user, await get_config(db, "risk.defaults"))
    unread = await db.scalar(select(func.count(Alert.id)).where(Alert.user_id == user.id, Alert.read_at.is_(None))) or 0
    used = await daily_usage(db, user)
    await db.commit()
    return MeOut(user=UserOut.model_validate(user), settings=SettingsOut.model_validate(s), risk_limits=RiskLimitsOut.model_validate(lim), guard=GuardOut.model_validate(g),
                 needs_onboarding=user.status == "ACTIVE" and s.onboarded_at is None and (s.onboarding_skips or 0) < 3,
                 ai_questions_left=max(0, settings.ai_daily_limit - used), unread_alerts=unread)


@router.patch("/settings", response_model=SettingsOut)
async def update_settings(body: SettingsIn, user: CurrentUser, db: DB):
    s = await db.get(UserSettings, user.id)
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == "ui_detail" and v not in ("SIMPLE", "STANDARD", "FULL"):
            raise bad_request("UI_DETAIL", "Mức chi tiết không hợp lệ")
        if k == "default_horizon" and v not in ("SHORT", "MID", "LONG"):
            raise bad_request("HORIZON", "Khung đầu tư không hợp lệ")
        setattr(s, k, v)
    await db.commit()
    return SettingsOut.model_validate(s)


@router.put("/onboarding", response_model=MeOut)
async def onboarding(body: OnboardingIn, user: CurrentUser, db: DB):
    s = await db.get(UserSettings, user.id)
    lim, _ = await ensure_user_defaults(db, user, await get_config(db, "risk.defaults"))
    defaults = await get_config(db, "risk.defaults")
    s.experience_level = body.experience if body.experience in EXPERIENCE_DETAIL else "MID"
    s.ui_detail = EXPERIENCE_DETAIL.get(body.experience, "STANDARD")
    s.holding_period = body.holding if body.holding in HOLDING_HORIZON else "WEEKS"
    s.default_horizon = HOLDING_HORIZON.get(body.holding, "MID")
    stop, risk = LOSS_PCT.get(body.max_loss, (8.0, 1.5))
    # BR-25: never looser than admin defaults
    lim.stop_loss_pct = min(stop, float(defaults.get("stop_loss_pct", 8.0)))
    lim.max_risk_per_trade_pct = min(risk, float(defaults.get("max_risk_per_trade_pct", 1.5)))
    if body.capital_band and body.capital_band in CAPITAL:
        s.capital_band, s.capital_vnd = body.capital_band, CAPITAL[body.capital_band]
    else:
        s.capital_band = "SKIP"
    syms = [x.upper() for x in body.symbols if x]
    if syms:
        valid = {x for (x,) in (await db.execute(select(Stock.symbol).where(Stock.symbol.in_(syms), Stock.is_active))).all()}
        wl = (await db.execute(select(Watchlist).where(Watchlist.user_id == user.id).order_by(Watchlist.position))).scalars().first()
        if wl is None:
            wl = Watchlist(user_id=user.id, name="Theo dõi")
            db.add(wl)
            await db.flush()
        for sym in syms:
            if sym in valid and await db.get(WatchlistItem, (wl.id, sym)) is None:
                db.add(WatchlistItem(watchlist_id=wl.id, symbol=sym))
    s.onboarded_at = datetime.now(UTC)
    await audit(db, user, "ONBOARDING", "user", str(user.id), after=body.model_dump())
    await db.commit()
    return await me(user, db)


@router.post("/onboarding/skip", response_model=Ok)
async def skip_onboarding(user: CurrentUser, db: DB):
    s = await db.get(UserSettings, user.id)
    s.onboarding_skips = (s.onboarding_skips or 0) + 1
    await db.commit()
    return Ok()


@router.get("/risk-limits", response_model=RiskLimitsOut)
async def risk_limits(user: CurrentUser, db: DB):
    lim, _ = await ensure_user_defaults(db, user, await get_config(db, "risk.defaults"))
    await db.commit()
    return RiskLimitsOut.model_validate(lim)


@router.put("/risk-limits", response_model=RiskLimitsOut)
async def set_risk_limits(body: RiskLimitsIn, user: CurrentUser, db: DB):
    lim, _ = await ensure_user_defaults(db, user, await get_config(db, "risk.defaults"))
    defaults = await get_config(db, "risk.defaults")
    data = body.model_dump(exclude_unset=True)
    # BR-25: members may only tighten the admin defaults; admin can set anything
    tighten_max = {"max_risk_per_trade_pct", "stop_loss_pct", "max_position_pct", "max_sector_pct", "max_correlated_group_pct", "weekly_loss_limit_pct", "monthly_loss_limit_pct", "max_open_risk_pct"}
    for k, v in data.items():
        if v is None:
            continue
        if user.role != "ADMIN":
            if k in tighten_max and float(v) > float(defaults.get(k, v)):
                raise bad_request("LIMIT_LOOSER", f"Giới hạn {k} không được lỏng hơn mặc định ({defaults.get(k)})")
            if k == "cooldown_sessions" and int(v) < int(defaults.get(k, 5)):
                raise bad_request("LIMIT_LOOSER", "Thời gian nghỉ không được ngắn hơn mặc định")
            if k == "min_risk_reward" and float(v) < float(defaults.get(k, 2.0)):
                raise bad_request("LIMIT_LOOSER", "Tỷ lệ lợi nhuận/rủi ro tối thiểu không được thấp hơn mặc định")
        setattr(lim, k, v)
    await audit(db, user, "RISK_LIMITS", "user", str(user.id), after=data)
    await db.commit()
    return RiskLimitsOut.model_validate(lim)


@router.get("/risk-guard", response_model=GuardOut)
async def risk_guard(user: CurrentUser, db: DB):
    _, g = await ensure_user_defaults(db, user)
    await db.commit()
    return GuardOut.model_validate(g)


@router.get("/discipline-events")
async def discipline_events(user: CurrentUser, db: DB, limit: int = 50):
    from app.models import RiskGuardEvent

    rows = (await db.execute(select(RiskGuardEvent).where(RiskGuardEvent.user_id == user.id).order_by(RiskGuardEvent.created_at.desc()).limit(limit))).scalars().all()
    return [{"id": r.id, "kind": r.kind, "symbol": r.symbol, "detail": r.detail, "note": r.note, "created_at": r.created_at} for r in rows]


@router.get("/devices", response_model=list[DeviceOut])
async def devices(user: CurrentUser, db: DB):
    return (await db.execute(select(UserDevice).where(UserDevice.user_id == user.id).order_by(UserDevice.last_seen_at.desc()))).scalars().all()


@router.delete("/devices/{device_id}", response_model=Ok)
async def remove_device(device_id: uuid.UUID, user: CurrentUser, db: DB):
    dev = await db.get(UserDevice, device_id)
    if not dev or dev.user_id != user.id:
        raise not_found()
    await db.delete(dev)
    await db.commit()
    return Ok(message="Đã đăng xuất thiết bị")


@router.post("/push-token", response_model=Ok)
async def push_token(body: PushTokenIn, user: AnyUser, db: DB):
    from app.api.deps import get_token_payload  # noqa: F401

    dev = (await db.execute(select(UserDevice).where(UserDevice.user_id == user.id, UserDevice.push_token == body.token))).scalar_one_or_none()
    if dev is None:
        dev = (await db.execute(select(UserDevice).where(UserDevice.user_id == user.id).order_by(UserDevice.last_seen_at.desc()))).scalars().first()
    if dev is None:
        dev = UserDevice(user_id=user.id, platform=body.platform)
        db.add(dev)
    dev.push_token, dev.platform = body.token, body.platform
    await db.commit()
    return Ok()


@router.post("/telegram/link", response_model=Ok)
async def telegram_link(user: CurrentUser, db: DB):
    code = secrets.token_hex(4).upper()
    user.telegram_link_code = code
    await db.commit()
    bot = None
    if settings.telegram_bot_token:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"https://api.telegram.org/bot{settings.telegram_bot_token}/getMe")
                bot = (r.json().get("result") or {}).get("username")
        except Exception:  # noqa: BLE001
            bot = None
    return Ok(data={"code": code, "bot_username": bot, "deep_link": f"https://t.me/{bot}?start={code}" if bot else None,
                    "instructions": f"Mở Telegram, tìm bot {('@' + bot) if bot else 'Vinatrade'} và gửi: /start {code}"})


@router.delete("/telegram/link", response_model=Ok)
async def telegram_unlink(user: CurrentUser, db: DB):
    user.telegram_chat_id, user.telegram_link_code = None, None
    await db.commit()
    return Ok(message="Đã hủy liên kết Telegram")

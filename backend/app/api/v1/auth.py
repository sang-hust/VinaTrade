import logging
import uuid
from datetime import UTC, datetime, timedelta

import pyotp
from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.deps import DB, AnyUser, CurrentUser, audit
from app.core.config import settings
from app.core.errors import ApiError, bad_request
from app.core.security import create_access_token, hash_password, hash_token, new_refresh_token, verify_password
from app.models import Invitation, RefreshToken, User, UserDevice, UserSettings
from app.schemas.auth import (
    ChangePasswordIn,
    ForgotIn,
    LoginIn,
    RefreshIn,
    RegisterIn,
    ResetIn,
    TokenOut,
    TotpVerifyIn,
    UserOut,
)
from app.schemas.common import Ok
from app.services.notify import send_email
from app.services.riskguard import ensure_user_defaults
from app.services.sysconfig import get_config

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger(__name__)


async def _issue(db, user: User, platform: str, device_name: str | None, request: Request | None) -> TokenOut:
    # device limit (FR-04): evict the oldest device when over the limit
    devices = (await db.execute(select(UserDevice).where(UserDevice.user_id == user.id).order_by(UserDevice.last_seen_at))).scalars().all()
    limit = user.max_devices or settings.max_devices
    while len(devices) >= limit:
        old = devices.pop(0)
        await db.delete(old)
    dev = UserDevice(user_id=user.id, platform=platform, name=device_name or (request.headers.get("user-agent", "")[:120] if request else None))
    db.add(dev)
    await db.flush()
    raw, h = new_refresh_token()
    db.add(RefreshToken(user_id=user.id, device_id=dev.id, token_hash=h, expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days)))
    user.last_login_at = datetime.now(UTC)
    await db.commit()
    return TokenOut(access_token=create_access_token(str(user.id), user.role, user.status, str(dev.id)), refresh_token=raw,
                    expires_in=settings.access_token_minutes * 60, user=UserOut.model_validate(user))


@router.post("/register", response_model=TokenOut)
async def register(body: RegisterIn, db: DB, request: Request):
    email = body.email.lower()
    if await db.scalar(select(User.id).where(User.email == email)):
        raise ApiError(409, "EMAIL_EXISTS", "Email này đã được đăng ký")
    inv = None
    if body.invite_code:
        inv = await db.get(Invitation, body.invite_code.strip().upper())
        if not inv or inv.used_at or (inv.expires_at and inv.expires_at < datetime.now(UTC)):
            raise bad_request("INVITE_INVALID", "Mã mời không hợp lệ hoặc đã dùng")
        if inv.email and inv.email.lower() != email:
            raise bad_request("INVITE_EMAIL", "Mã mời này dành cho email khác")
    user = User(email=email, full_name=body.full_name.strip(), phone=body.phone, password_hash=hash_password(body.password), status="PENDING",
                invited_by_code=inv.code if inv else None)
    if inv and inv.auto_activate:
        user.status, user.activated_at = "ACTIVE", datetime.now(UTC)
        if inv.valid_months:
            user.expires_at = datetime.now(UTC) + timedelta(days=30 * inv.valid_months)
    db.add(user)
    await db.flush()
    db.add(UserSettings(user_id=user.id))
    await ensure_user_defaults(db, user, await get_config(db, "risk.defaults"))
    if inv:
        inv.used_by, inv.used_at = user.id, datetime.now(UTC)
    await audit(db, user, "REGISTER", "user", str(user.id), request=request)
    return await _issue(db, user, body.platform, body.device_name, request)


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, db: DB, request: Request):
    user = (await db.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    if user and user.locked_until and user.locked_until > datetime.now(UTC):
        raise ApiError(423, "LOGIN_LOCKED", f"Đăng nhập sai quá 5 lần. Thử lại sau {int((user.locked_until - datetime.now(UTC)).total_seconds() // 60) + 1} phút.")
    if not user or not verify_password(body.password, user.password_hash):
        if user:
            user.failed_logins = (user.failed_logins or 0) + 1
            if user.failed_logins >= 5:
                user.locked_until = datetime.now(UTC) + timedelta(minutes=15)
                user.failed_logins = 0
            await db.commit()
        raise ApiError(401, "BAD_CREDENTIALS", "Email hoặc mật khẩu không đúng")
    if user.totp_enabled:
        if not body.totp:
            raise ApiError(401, "TOTP_REQUIRED", "Nhập mã xác thực 2 lớp", {"totp_required": True})
        if not pyotp.TOTP(user.totp_secret).verify(body.totp, valid_window=1):
            raise ApiError(401, "TOTP_INVALID", "Mã xác thực không đúng")
    user.failed_logins, user.locked_until = 0, None
    await audit(db, user, "LOGIN", "user", str(user.id), request=request)
    return await _issue(db, user, body.platform, body.device_name, request)


@router.post("/refresh", response_model=TokenOut)
async def refresh(body: RefreshIn, db: DB, request: Request):
    h = hash_token(body.refresh_token)
    rt = (await db.execute(select(RefreshToken).where(RefreshToken.token_hash == h))).scalar_one_or_none()
    if not rt or rt.expires_at < datetime.now(UTC):
        raise ApiError(401, "REFRESH_INVALID", "Phiên đăng nhập không hợp lệ")
    if rt.revoked_at:
        # token reuse → revoke the whole device session (8.1)
        await db.execute(RefreshToken.__table__.update().where(RefreshToken.device_id == rt.device_id).values(revoked_at=datetime.now(UTC)))
        await db.commit()
        raise ApiError(401, "REFRESH_REUSED", "Phiên đăng nhập đã bị thu hồi, hãy đăng nhập lại")
    user = await db.get(User, rt.user_id)
    dev = await db.get(UserDevice, rt.device_id) if rt.device_id else None
    if not user or (rt.device_id and not dev):
        raise ApiError(401, "SESSION_REVOKED", "Thiết bị này đã bị đăng xuất")
    rt.revoked_at = datetime.now(UTC)
    raw, nh = new_refresh_token()
    db.add(RefreshToken(user_id=user.id, device_id=rt.device_id, token_hash=nh, expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days)))
    if dev:
        dev.last_seen_at = datetime.now(UTC)
    await db.commit()
    return TokenOut(access_token=create_access_token(str(user.id), user.role, user.status, str(rt.device_id) if rt.device_id else None), refresh_token=raw,
                    expires_in=settings.access_token_minutes * 60, user=UserOut.model_validate(user))


@router.post("/logout", response_model=Ok)
async def logout(user: AnyUser, db: DB, request: Request):
    from app.api.deps import get_token_payload

    payload = await get_token_payload(request.headers.get("authorization"), request)
    if payload.get("dev"):
        dev = await db.get(UserDevice, uuid.UUID(payload["dev"]))
        if dev:
            await db.delete(dev)
    await db.commit()
    return Ok(message="Đã đăng xuất")


@router.post("/password/forgot", response_model=Ok)
async def forgot(body: ForgotIn, db: DB):
    user = (await db.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    if user:
        raw, h = new_refresh_token()
        user.reset_token_hash, user.reset_expires_at = h, datetime.now(UTC) + timedelta(hours=2)
        await db.commit()
        link = f"{settings.public_web_url}/reset-password?token={raw}"
        sent = send_email(user.email, "Vinatrade – đặt lại mật khẩu", f"Bấm vào liên kết để đặt lại mật khẩu (hiệu lực 2 giờ):\n{link}")
        if sent is None:
            log.info("[reset link] %s", link)
            if settings.debug:
                return Ok(message="Email chưa cấu hình, liên kết ghi vào log", data={"debug_token": raw})
    return Ok(message="Nếu email tồn tại, liên kết đặt lại mật khẩu đã được gửi")


@router.post("/password/reset", response_model=Ok)
async def reset(body: ResetIn, db: DB):
    h = hash_token(body.token)
    user = (await db.execute(select(User).where(User.reset_token_hash == h))).scalar_one_or_none()
    if not user or not user.reset_expires_at or user.reset_expires_at < datetime.now(UTC):
        raise bad_request("RESET_INVALID", "Liên kết không hợp lệ hoặc đã hết hạn")
    user.password_hash, user.reset_token_hash, user.reset_expires_at = hash_password(body.password), None, None
    await db.execute(RefreshToken.__table__.update().where(RefreshToken.user_id == user.id).values(revoked_at=datetime.now(UTC)))
    await audit(db, user, "PASSWORD_RESET", "user", str(user.id))
    await db.commit()
    return Ok(message="Đã đổi mật khẩu, hãy đăng nhập lại")


@router.post("/password/change", response_model=Ok)
async def change_password(body: ChangePasswordIn, user: CurrentUser, db: DB):
    if not verify_password(body.current_password, user.password_hash):
        raise bad_request("BAD_PASSWORD", "Mật khẩu hiện tại không đúng")
    user.password_hash = hash_password(body.new_password)
    await audit(db, user, "PASSWORD_CHANGE", "user", str(user.id))
    await db.commit()
    return Ok(message="Đã đổi mật khẩu")


@router.post("/2fa/setup", response_model=Ok)
async def totp_setup(user: CurrentUser, db: DB):
    secret = pyotp.random_base32()
    user.totp_secret, user.totp_enabled = secret, False
    await db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="Vinatrade")
    return Ok(data={"secret": secret, "otpauth_uri": uri})


@router.post("/2fa/verify", response_model=Ok)
async def totp_verify(body: TotpVerifyIn, user: CurrentUser, db: DB):
    if not user.totp_secret or not pyotp.TOTP(user.totp_secret).verify(body.code, valid_window=1):
        raise bad_request("TOTP_INVALID", "Mã xác thực không đúng")
    user.totp_enabled = True
    await audit(db, user, "TOTP_ENABLED", "user", str(user.id))
    await db.commit()
    return Ok(message="Đã bật xác thực 2 lớp")


@router.post("/2fa/disable", response_model=Ok)
async def totp_disable(body: TotpVerifyIn, user: CurrentUser, db: DB):
    if not user.totp_enabled or not pyotp.TOTP(user.totp_secret).verify(body.code, valid_window=1):
        raise bad_request("TOTP_INVALID", "Mã xác thực không đúng")
    user.totp_enabled, user.totp_secret = False, None
    await db.commit()
    return Ok(message="Đã tắt xác thực 2 lớp")

import uuid
from datetime import UTC, datetime
from typing import Annotated

import jwt
from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.errors import ApiError
from app.core.security import decode_access_token
from app.models import AuditLog, User, UserDevice

DB = Annotated[AsyncSession, Depends(get_db)]


async def get_token_payload(authorization: Annotated[str | None, Header()] = None, request: Request = None) -> dict:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif request is not None and request.query_params.get("token"):
        token = request.query_params["token"]
    if not token:
        raise ApiError(401, "UNAUTHENTICATED", "Bạn cần đăng nhập")
    try:
        return decode_access_token(token)
    except jwt.ExpiredSignatureError as e:
        raise ApiError(401, "TOKEN_EXPIRED", "Phiên đăng nhập đã hết hạn") from e
    except jwt.PyJWTError as e:
        raise ApiError(401, "TOKEN_INVALID", "Mã đăng nhập không hợp lệ") from e


async def current_user_any(db: DB, payload: Annotated[dict, Depends(get_token_payload)], request: Request = None) -> User:
    """Any authenticated user, including PENDING (for /me status polling)."""
    user = await db.get(User, uuid.UUID(payload["sub"]))
    if not user:
        raise ApiError(401, "USER_NOT_FOUND", "Tài khoản không tồn tại")
    if payload.get("dev"):
        dev = await db.get(UserDevice, uuid.UUID(payload["dev"]))
        if dev is None:
            raise ApiError(401, "SESSION_REVOKED", "Thiết bị này đã bị đăng xuất")
        dev.last_seen_at = datetime.now(UTC)
        if request is not None:
            request.state.device = dev
    return user


async def current_user(user: Annotated[User, Depends(current_user_any)]) -> User:
    """ACTIVE and not expired (BR-01) — checked on every request."""
    if user.status == "LOCKED":
        raise ApiError(403, "ACCOUNT_LOCKED", "Tài khoản của bạn đang bị khóa. Liên hệ quản trị viên để mở lại.")
    if user.status == "PENDING":
        raise ApiError(403, "ACCOUNT_PENDING", "Tài khoản đang chờ kích hoạt")
    if user.status == "REJECTED":
        raise ApiError(403, "ACCOUNT_REJECTED", "Yêu cầu đăng ký đã bị từ chối")
    if user.status == "EXPIRED" or (user.expires_at and user.expires_at < datetime.now(UTC)):
        raise ApiError(403, "ACCOUNT_EXPIRED", "Tài khoản đã hết hạn. Liên hệ quản trị viên để gia hạn.")
    return user


def admin_2fa_required() -> bool:
    return settings.admin_require_2fa if settings.admin_require_2fa is not None else not settings.debug


async def admin_user(user: Annotated[User, Depends(current_user)], request: Request, db: DB) -> User:
    """ADMIN role + mandatory 2FA + 30-minute idle lock on the admin console (UI spec 15). The lock is per device:
    the first admin request after login (or after /admin/session/unlock) opens the console; a gap longer than
    ADMIN_IDLE_MINUTES between admin requests closes it until the admin re-enters the password (and TOTP)."""
    if user.role != "ADMIN":
        raise ApiError(403, "ADMIN_ONLY", "Chỉ quản trị viên được phép")
    if admin_2fa_required() and not user.totp_enabled:
        raise ApiError(403, "ADMIN_2FA_REQUIRED", "Trang quản trị yêu cầu bật xác thực 2 lớp", {"setup": "/account"})
    dev: UserDevice | None = getattr(request.state, "device", None)
    if dev is not None:
        now = datetime.now(UTC)
        if dev.admin_seen_at and (now - dev.admin_seen_at).total_seconds() > settings.admin_idle_minutes * 60:
            raise ApiError(403, "ADMIN_SESSION_EXPIRED", f"Phiên quản trị đã khóa sau {settings.admin_idle_minutes} phút không thao tác. Nhập lại mật khẩu để tiếp tục.")
        dev.admin_seen_at = now
        await db.commit()  # the request session only commits on writes; the idle clock must persist on reads too
    return user


CurrentUser = Annotated[User, Depends(current_user)]
AnyUser = Annotated[User, Depends(current_user_any)]
AdminUser = Annotated[User, Depends(admin_user)]


async def audit(db: AsyncSession, actor: User | None, action: str, target_type: str | None = None, target_id: str | None = None,
                before: dict | None = None, after: dict | None = None, request: Request | None = None) -> None:
    db.add(AuditLog(actor_id=actor.id if actor else None, actor_email=actor.email if actor else None, action=action, target_type=target_type,
                    target_id=str(target_id) if target_id else None, before=before, after=after,
                    ip=(request.headers.get("x-forwarded-for", request.client.host if request.client else None) if request else None)))

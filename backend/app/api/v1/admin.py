"""Admin console API (UI spec part IV, A01–A10). Every mutating call is audited; dangerous ones confirm client-side."""

import asyncio
import io
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import pyotp
from fastapi import APIRouter, BackgroundTasks, File, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import desc, func, select, text

from app.api.deps import DB, AdminUser, CurrentUser, admin_2fa_required, audit
from app.api.presenters import clean, row
from app.core.config import settings
from app.core.errors import ApiError, bad_request, not_found
from app.core.security import hash_password, new_invite_code, verify_password
from app.core.vntime import is_market_open, is_trading_day, now_vn, today_vn
from app.engines.scoring import composite, downgrade, rating_for
from app.engines.strategies import DEFAULT_PARAMS, STRATEGY_PARAM_KEYS
from app.ingestion.file_import import commit_import, preview_file
from app.models import (
    AiMessage,
    AuditLog,
    Broadcast,
    CompanyRiskScore,
    DataSource,
    Invitation,
    JobRun,
    MarketRegime,
    NotificationDelivery,
    PretradeCheck,
    RiskGuardEvent,
    Stock,
    StockScore,
    Strategy,
    User,
    UserDevice,
    UserSettings,
)
from app.schemas.auth import UserOut
from app.schemas.common import Ok
from app.services.jobs import JOB_INFO, RUNNING, cancel_job, recent_jobs
from app.services.notify import create_alert, dispatch_pending, send_email
from app.services.riskguard import ensure_user_defaults
from app.services.sysconfig import CONFIG_META, DEFAULTS, all_config, get_config, set_config

router = APIRouter(prefix="/admin", tags=["admin"])


class ActivateIn(BaseModel):
    valid_months: int | None = None
    max_devices: int | None = 3
    role: str | None = None
    message: str | None = None


class BulkActivateIn(ActivateIn):
    ids: list[uuid.UUID]


class UserCreateIn(BaseModel):
    email: str
    full_name: str
    phone: str | None = None
    role: str = "MEMBER"
    valid_months: int | None = None
    max_devices: int = 3


class UserPatch(BaseModel):
    role: str | None = None
    expires_at: datetime | None = None
    max_devices: int | None = None
    full_name: str | None = None
    reset_password: bool = False


class InviteIn(BaseModel):
    email: str | None = None
    note: str | None = None
    auto_activate: bool = False
    valid_months: int | None = None
    expires_days: int = 30


class ConfigIn(BaseModel):
    value: object


class StrategyIn(BaseModel):
    enabled: bool | None = None
    params: dict | None = None
    name: str | None = None


class DraftIn(BaseModel):
    params: dict


class BroadcastIn(BaseModel):
    title: str
    body: str
    channels: list[str] = ["push", "telegram"]


class UnlockIn(BaseModel):
    password: str
    totp: str | None = None


# ---------------------------------------------------------------- session (UI 15: 2FA + 30-minute idle lock)
def _session_state() -> dict:
    n = now_vn()
    if not is_trading_day(n.date()):
        return {"state": "HOLIDAY", "label": "Phiên: nghỉ giao dịch"}
    if is_market_open(n):
        return {"state": "OPEN", "label": "Phiên: đang giao dịch"}
    return {"state": "CLOSED", "label": "Phiên: đã đóng cửa" if n.hour >= 15 else "Phiên: chưa mở cửa"}


@router.post("/session/unlock")
async def unlock_session(body: UnlockIn, user: CurrentUser, db: DB, request: Request):
    """Re-authenticates the admin console on this device after the idle lock (password + TOTP when enabled)."""
    if user.role != "ADMIN":
        raise ApiError(403, "ADMIN_ONLY", "Chỉ quản trị viên được phép")
    if not verify_password(body.password, user.password_hash):
        raise ApiError(401, "BAD_CREDENTIALS", "Mật khẩu không đúng")
    if user.totp_enabled:
        if not body.totp:
            raise ApiError(401, "TOTP_REQUIRED", "Nhập mã xác thực 2 lớp", {"totp_required": True})
        if not pyotp.TOTP(user.totp_secret).verify(body.totp, valid_window=1):
            raise ApiError(401, "TOTP_INVALID", "Mã xác thực không đúng")
    dev: UserDevice | None = getattr(request.state, "device", None)
    if dev is not None:
        dev.admin_seen_at = datetime.now(UTC)
    await audit(db, user, "ADMIN_UNLOCK", "user", str(user.id), request=request)
    await db.commit()
    return Ok(message="Đã mở lại phiên quản trị")


async def _health(db) -> tuple[str, list, list, int, int]:
    now = datetime.now(UTC)
    users_pending = await db.scalar(select(func.count(User.id)).where(User.status == "PENDING"))
    jobs = await recent_jobs(db, 60)
    failed_jobs = [j for j in jobs if j.status == "FAILED" and j.started_at >= now - timedelta(days=1)]
    sources = [row(s, ["code", "name", "role", "priority", "enabled", "status", "last_ok_at", "last_error", "latency_ms", "consecutive_failures"])
               for s in (await db.execute(select(DataSource).order_by(DataSource.priority))).scalars()]
    health = "RED" if failed_jobs or any(s["status"] == "DOWN" and s["enabled"] for s in sources) else ("YELLOW" if users_pending or any(s["status"] == "DEGRADED" for s in sources) else "GREEN")
    return health, jobs, sources, users_pending, len(failed_jobs)


async def _todo(db, jobs, sources, users_pending: int, failed_jobs: int) -> list[dict]:
    todo = []
    if users_pending:
        oldest = await db.scalar(select(func.min(User.created_at)).where(User.status == "PENDING"))
        todo.append({"kind": "PENDING_USERS", "text": f"{users_pending} tài khoản chờ kích hoạt", "detail": f"Yêu cầu sớm nhất từ {oldest.astimezone().strftime('%d/%m %H:%M') if oldest else '—'}.",
                     "action": "Duyệt", "route": "/admin/users"})
    if failed_jobs:
        names = sorted({j.name for j in jobs if j.status == "FAILED"})[:3]
        todo.append({"kind": "FAILED_JOBS", "text": f"{failed_jobs} tác vụ lỗi trong 24 giờ", "detail": ", ".join(names), "action": "Xem", "route": "/admin/jobs"})
    for s in sources:
        if s["status"] == "DOWN" and s["enabled"]:
            todo.append({"kind": "SOURCE_DOWN", "text": f"Nguồn {s['name']} không phản hồi", "detail": s.get("last_error") or "", "action": "Xem", "route": "/admin/jobs"})
        elif s["status"] == "DEGRADED":
            todo.append({"kind": "SOURCE_SLOW", "text": f"Nguồn {s['name']} chậm", "detail": f"Thời gian phản hồi {((s.get('latency_ms') or 0) / 1000):.1f} giây.", "action": "Xem", "route": "/admin/jobs"})
    for st in (await db.execute(select(Strategy).where(Strategy.draft_backtest.isnot(None)))).scalars():
        bt = st.draft_backtest or {}
        d, live = bt.get("draft", {}), bt.get("live", {})
        todo.append({"kind": "DRAFT_READY", "text": f"Chiến lược {st.name} v{st.version + 1} đã backtest xong",
                     "detail": f"Tỷ lệ đúng {d.get('win_rate')}% (v{st.version}: {live.get('win_rate')}%). Chờ bạn bật.", "action": "So sánh", "route": f"/admin/strategies?code={st.code}"})
    return todo


@router.get("/status")
async def status(admin: AdminUser, db: DB):
    """Lightweight payload for the admin frame: health badge, session, pending count, bell items."""
    health, jobs, sources, pending, failed = await _health(db)
    todo = await _todo(db, jobs, sources, pending, failed)
    return {"health": health, "session": _session_state(), "users_pending": pending, "todo": todo, "require_2fa": admin_2fa_required(), "idle_minutes": settings.admin_idle_minutes}


# ---------------------------------------------------------------- overview (A01)
@router.get("/overview")
async def overview(admin: AdminUser, db: DB):
    now = datetime.now(UTC)
    users_active = await db.scalar(select(func.count(User.id)).where(User.status == "ACTIVE"))
    users_total = await db.scalar(select(func.count(User.id)))
    active_today = await db.scalar(select(func.count(func.distinct(UserDevice.user_id))).where(UserDevice.last_seen_at >= now - timedelta(days=1)))
    active_7d = await db.scalar(select(func.count(func.distinct(UserDevice.user_id))).where(UserDevice.last_seen_at >= now - timedelta(days=7)))
    d24 = now - timedelta(hours=24)
    sent = await db.scalar(select(func.count(NotificationDelivery.id)).where(NotificationDelivery.sent_at >= d24, NotificationDelivery.status == "SENT"))
    failed = await db.scalar(select(func.count(NotificationDelivery.id)).where(NotificationDelivery.sent_at >= d24, NotificationDelivery.status == "FAILED"))
    p95 = (await db.execute(text("SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) FROM notification_deliveries WHERE sent_at >= :d AND channel <> 'inapp'"), {"d": d24})).scalar()
    win = (await db.execute(text("""SELECT avg(case when o.result in ('TP_HIT','WIN') then 1.0 else 0.0 end)*100, avg(o.return_pct) FROM signals s JOIN signal_outcomes o ON o.signal_id=s.id AND o.days=20
                                    WHERE s.signal_type='BUY' AND s.trade_date >= :d"""), {"d": today_vn() - timedelta(days=120)})).one()
    ai_tokens = (await db.execute(select(func.coalesce(func.sum(AiMessage.input_tokens), 0), func.coalesce(func.sum(AiMessage.output_tokens), 0)).where(AiMessage.created_at >= now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)))).one()
    ai_cost = ai_tokens[0] / 1e6 * 5 + ai_tokens[1] / 1e6 * 25
    budget = (await get_config(db, "ai.limits")).get("monthly_budget_usd", 50)
    health, jobs, sources, users_pending, failed_jobs = await _health(db)
    from app.tasks.eod import EOD_STEP_INFO, EOD_STEPS

    chain = {}
    for j in jobs:
        if j.name.startswith("eod.") and j.name not in chain:
            chain[j.name] = {"name": j.name, "status": j.status, "summary": j.summary, "started_at": clean(j.started_at), "duration_ms": j.duration_ms, "id": j.id, "error": (j.error or "")[-600:] or None}
    steps = []
    for n, _ in EOD_STEPS:
        label, at = EOD_STEP_INFO.get(n, (n, ""))
        st = chain.get(n, {"name": n, "status": "PENDING"})
        if n in RUNNING:
            st["status"] = "RUNNING"
        steps.append({**st, "label": label, "at": at})
    done = sum(1 for s in steps if s["status"] in ("DONE", "WARN"))
    last_eod = next((clean(j.started_at) for j in jobs if j.name == "eod.universe"), None)
    todo = await _todo(db, jobs, sources, users_pending, failed_jobs)
    db_size = (await db.execute(text("SELECT pg_database_size(current_database())"))).scalar()
    headline = "Mọi tác vụ trong phiên đã chạy đúng hạn." if health == "GREEN" else ("Có việc cần bạn xử lý." if health == "YELLOW" else "Có tác vụ hoặc nguồn dữ liệu lỗi.")
    return {"health": health, "session": _session_state(), "headline": headline,
            "kpis": {"users_active": users_active, "users_total": users_total, "users_pending": users_pending, "active_today": active_today, "active_7d": active_7d,
                     "alerts_sent_24h": sent, "alerts_failed_24h": failed, "alert_latency_p95_ms": int(p95) if p95 else None, "alert_latency_target_s": 60,
                     "signal_win_rate_20": round(float(win[0]), 1) if win[0] is not None else None, "signal_avg_return_20": round(float(win[1]), 2) if win[1] is not None else None,
                     "ai_cost_usd": round(ai_cost, 2), "ai_budget_usd": budget, "db_size_mb": round(db_size / 1e6, 1) if db_size else None},
            "eod_chain": steps, "eod_done": done, "eod_total": len(steps), "todo": todo, "sources": sources, "last_eod": last_eod}


@router.get("/overview/report", response_class=PlainTextResponse)
async def overview_report(admin: AdminUser, db: DB):
    """'Xuất báo cáo vận hành': plain-text operations report for the day."""
    o = await overview(admin, db)
    k = o["kpis"]
    lines = [f"BÁO CÁO VẬN HÀNH VINATRADE — {now_vn().strftime('%d/%m/%Y %H:%M')}", f"Sức khỏe hệ thống: {o['health']} · {o['session']['label']}", "",
             "CHỈ SỐ", f"- Người dùng hoạt động hôm nay: {k['active_today']} / {k['users_total']} ({k['users_pending']} chờ duyệt)",
             f"- Độ trễ cảnh báo p95: {k['alert_latency_p95_ms'] / 1000:.1f} giây (mục tiêu ≤ 60)" if k["alert_latency_p95_ms"] else "- Độ trễ cảnh báo p95: chưa có dữ liệu",
             f"- Cảnh báo 24 giờ: {k['alerts_sent_24h']} gửi, {k['alerts_failed_24h']} thất bại",
             f"- Tỷ lệ thắng tín hiệu mua 20 phiên: {k['signal_win_rate_20']}% · lợi nhuận TB {k['signal_avg_return_20']}%",
             f"- Chi phí AI tháng: ${k['ai_cost_usd']} / ${k['ai_budget_usd']}", f"- Dung lượng CSDL: {k['db_size_mb']} MB", "", "CHUỖI XỬ LÝ CUỐI NGÀY"]
    for s in o["eod_chain"]:
        lines.append(f"- {s['at']} {s['label']}: {s['status']}{' · ' + s['summary'] if s.get('summary') else ''}{' · ' + s['error'][:200] if s.get('error') else ''}")
    lines += ["", "CẦN XỬ LÝ"] + ([f"- {t['text']} ({t.get('detail', '')})" for t in o["todo"]] or ["- Không có"])
    lines += ["", "NGUỒN DỮ LIỆU"] + [f"- {s['name']} ({'chính' if s['role'] == 'PRIMARY' else 'dự phòng'}): {s['status']}, {s.get('latency_ms') or '—'} ms, cập nhật {s.get('last_ok_at') or '—'}" for s in o["sources"]]
    return "\n".join(lines)


@router.get("/search")
async def search(admin: AdminUser, db: DB, q: str = ""):
    """Ctrl K in the admin frame: users, jobs and config keys."""
    q = q.strip()
    if len(q) < 2:
        return []
    out = []
    for u in (await db.execute(select(User).where((User.email.ilike(f"%{q}%")) | (User.full_name.ilike(f"%{q}%"))).limit(6))).scalars():
        out.append({"type": "user", "label": u.full_name, "detail": f"{u.email} · {u.status}", "route": f"/admin/users?q={u.email}"})
    ql = q.lower()
    for name, (label, sched, _) in JOB_INFO.items():
        if ql in name or ql in label.lower():
            out.append({"type": "job", "label": label, "detail": f"{name} · {sched}", "route": "/admin/jobs"})
    for key, meta in CONFIG_META.items():
        if ql in key or ql in meta.get("label", "").lower():
            out.append({"type": "config", "label": meta.get("label", key), "detail": key, "route": f"/admin/config?key={key}"})
    for s in (await db.execute(select(Strategy).where((Strategy.code.ilike(f"%{q}%")) | (Strategy.name.ilike(f"%{q}%"))).limit(5))).scalars():
        out.append({"type": "strategy", "label": s.name, "detail": s.code, "route": f"/admin/strategies?code={s.code}"})
    return out[:15]


# ---------------------------------------------------------------- users (A02)
def _user_row(u: User, n_dev: int) -> dict:
    return {**UserOut.model_validate(u).model_dump(), "devices": n_dev, "max_devices": u.max_devices, "invited_by_code": u.invited_by_code, "activated_at": clean(u.activated_at)}


@router.get("/users")
async def users(admin: AdminUser, db: DB, status: str | None = None, q: str | None = None, page: int = 1, size: int = Query(50, le=200)):
    stmt = select(User)
    if status and status.upper() != "ALL":
        stmt = stmt.where(User.status == status.upper())
    if q:
        stmt = stmt.where((User.email.ilike(f"%{q}%")) | (User.full_name.ilike(f"%{q}%")))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (await db.execute(stmt.order_by(User.status == "PENDING", desc(User.created_at)).offset((page - 1) * size).limit(size))).scalars().all()
    dev_counts = dict((await db.execute(select(UserDevice.user_id, func.count(UserDevice.id)).group_by(UserDevice.user_id))).all())
    counts = {s: c for s, c in (await db.execute(select(User.status, func.count(User.id)).group_by(User.status))).all()}
    counts["ALL"] = sum(counts.values())
    return {"items": [_user_row(u, dev_counts.get(u.id, 0)) for u in rows], "total": total, "page": page, "size": size, "counts": counts}


@router.post("/users")
async def create_user(body: UserCreateIn, admin: AdminUser, db: DB, request: Request):
    """'Thêm người dùng': creates an ACTIVE account with a temporary password (shown once)."""
    email = body.email.strip().lower()
    if await db.scalar(select(func.count(User.id)).where(User.email == email)):
        raise bad_request("EMAIL_TAKEN", "Email này đã có tài khoản")
    temp = secrets.token_urlsafe(8)
    u = User(email=email, full_name=body.full_name.strip(), phone=body.phone, password_hash=hash_password(temp), status="ACTIVE", role=body.role if body.role in ("ADMIN", "MEMBER") else "MEMBER",
             activated_at=datetime.now(UTC), max_devices=body.max_devices, expires_at=datetime.now(UTC) + timedelta(days=30 * body.valid_months) if body.valid_months else None)
    db.add(u)
    await db.flush()
    db.add(UserSettings(user_id=u.id))
    await ensure_user_defaults(db, u, await get_config(db, "risk.defaults"))
    await audit(db, admin, "USER_CREATE", "user", str(u.id), after={"email": email, "role": u.role, "valid_months": body.valid_months}, request=request)
    await db.commit()
    await asyncio.to_thread(send_email, email, "Vinatrade – tài khoản của bạn", f"Quản trị viên đã tạo tài khoản cho bạn.\nMật khẩu tạm: {temp}\nĐăng nhập tại {settings.public_web_url} và đổi mật khẩu ngay.")
    return {**UserOut.model_validate(u).model_dump(), "temp_password": temp}


@router.get("/users/{uid}")
async def user_detail(uid: uuid.UUID, admin: AdminUser, db: DB):
    u = await db.get(User, uid)
    if not u:
        raise not_found()
    devs = (await db.execute(select(UserDevice).where(UserDevice.user_id == u.id).order_by(desc(UserDevice.last_seen_at)))).scalars().all()
    devices = [row(d, ["id", "platform", "name", "last_seen_at", "created_at"]) for d in devs]
    first = min(devs, key=lambda d: d.created_at) if devs else None
    logins = [row(a, ["action", "ip", "created_at"]) for a in (await db.execute(select(AuditLog).where(AuditLog.actor_id == u.id, AuditLog.action.in_(["LOGIN", "REGISTER"])).order_by(desc(AuditLog.created_at)).limit(10))).scalars()]
    from app.models import AlertRule

    n_rules = await db.scalar(select(func.count(AlertRule.id)).where(AlertRule.user_id == u.id))
    s = await db.get(UserSettings, u.id)
    return {**_user_row(u, len(devs)), "devices": devices, "registered_device": row(first, ["platform", "name", "created_at"]) if first else None, "logins": logins,
            "alert_rules": n_rules, "ui_detail": s.ui_detail if s else None, "onboarded_at": clean(s.onboarded_at) if s else None}


async def _set_status(db, admin, u: User, status: str, request: Request, note: str | None = None):
    before = {"status": u.status}
    u.status = status
    if status == "ACTIVE" and not u.activated_at:
        u.activated_at = datetime.now(UTC)
    if status in ("LOCKED", "REJECTED"):
        for d in (await db.execute(select(UserDevice).where(UserDevice.user_id == u.id))).scalars():
            await db.delete(d)
    await audit(db, admin, f"USER_{status}", "user", str(u.id), before=before, after={"status": status, "note": note}, request=request)


async def _activate(db, admin, u: User, body: ActivateIn, request: Request):
    if body.valid_months:
        u.expires_at = datetime.now(UTC) + timedelta(days=30 * body.valid_months)
    if body.max_devices:
        u.max_devices = body.max_devices
    if body.role in ("ADMIN", "MEMBER"):
        u.role = body.role
    await _set_status(db, admin, u, "ACTIVE", request, body.message)
    await ensure_user_defaults(db, u, await get_config(db, "risk.defaults"))
    await create_alert(db, u, kind="SYSTEM", priority="HIGH", title="Tài khoản đã được kích hoạt", body=body.message or "Chào mừng bạn đến với Vinatrade. Hãy trả lời 5 câu hỏi để cá nhân hóa ứng dụng.", deeplink="/onboarding", dedupe_key=f"activated:{u.id}")
    await asyncio.to_thread(send_email, u.email, "Vinatrade – tài khoản đã được kích hoạt", (body.message or "Tài khoản của bạn đã được kích hoạt.") + f"\n\nĐăng nhập tại {settings.public_web_url}")


@router.post("/users/{uid}/activate")
async def activate(uid: uuid.UUID, body: ActivateIn, admin: AdminUser, db: DB, request: Request):
    u = await db.get(User, uid)
    if not u:
        raise not_found()
    await _activate(db, admin, u, body, request)
    await db.commit()
    return UserOut.model_validate(u)


@router.post("/users/bulk-activate")
async def bulk_activate(body: BulkActivateIn, admin: AdminUser, db: DB, request: Request):
    n = 0
    for uid in body.ids:
        u = await db.get(User, uid)
        if u and u.status == "PENDING":
            await _activate(db, admin, u, body, request)
            n += 1
    await db.commit()
    return Ok(message=f"Đã kích hoạt {n} tài khoản")


@router.post("/users/{uid}/reject")
async def reject(uid: uuid.UUID, admin: AdminUser, db: DB, request: Request, reason: str | None = None):
    u = await db.get(User, uid)
    if not u:
        raise not_found()
    await _set_status(db, admin, u, "REJECTED", request, reason)
    await asyncio.to_thread(send_email, u.email, "Vinatrade – yêu cầu đăng ký", reason or "Yêu cầu đăng ký của bạn chưa được chấp nhận.")
    await db.commit()
    return UserOut.model_validate(u)


@router.post("/users/{uid}/lock")
async def lock(uid: uuid.UUID, admin: AdminUser, db: DB, request: Request, reason: str | None = None):
    u = await db.get(User, uid)
    if not u:
        raise not_found()
    if u.id == admin.id:
        raise bad_request("SELF_LOCK", "Không thể tự khóa chính mình")
    if u.role == "ADMIN" and await db.scalar(select(func.count(User.id)).where(User.role == "ADMIN", User.status == "ACTIVE")) <= 1:
        raise bad_request("LAST_ADMIN", "Phải còn ít nhất một quản trị viên")
    await _set_status(db, admin, u, "LOCKED", request, reason)
    await db.commit()
    return UserOut.model_validate(u)


@router.post("/users/{uid}/unlock")
async def unlock(uid: uuid.UUID, admin: AdminUser, db: DB, request: Request):
    u = await db.get(User, uid)
    if not u:
        raise not_found()
    await _set_status(db, admin, u, "ACTIVE", request)
    await db.commit()
    return UserOut.model_validate(u)


@router.patch("/users/{uid}")
async def patch_user(uid: uuid.UUID, body: UserPatch, admin: AdminUser, db: DB, request: Request):
    u = await db.get(User, uid)
    if not u:
        raise not_found()
    before = {"role": u.role, "expires_at": clean(u.expires_at), "max_devices": u.max_devices}
    temp = None
    if body.role in ("ADMIN", "MEMBER"):
        if u.role == "ADMIN" and body.role == "MEMBER" and await db.scalar(select(func.count(User.id)).where(User.role == "ADMIN")) <= 1:
            raise bad_request("LAST_ADMIN", "Phải còn ít nhất một quản trị viên")
        u.role = body.role
    if body.expires_at is not None:
        u.expires_at = body.expires_at
        if u.status == "EXPIRED" and body.expires_at > datetime.now(UTC):
            u.status = "ACTIVE"
    if body.max_devices:
        u.max_devices = body.max_devices
    if body.full_name:
        u.full_name = body.full_name
    if body.reset_password:
        temp = secrets.token_urlsafe(8)
        u.password_hash = hash_password(temp)
    await audit(db, admin, "USER_PATCH", "user", str(u.id), before=before, after=body.model_dump(exclude={"reset_password"}), request=request)
    await db.commit()
    return {**UserOut.model_validate(u).model_dump(), "temp_password": temp}


@router.delete("/users/{uid}", response_model=Ok)
async def delete_user(uid: uuid.UUID, admin: AdminUser, db: DB, request: Request):
    u = await db.get(User, uid)
    if not u:
        raise not_found()
    if u.id == admin.id:
        raise bad_request("SELF_DELETE", "Không thể xóa chính mình")
    await audit(db, admin, "USER_DELETE", "user", str(u.id), before={"email": u.email}, request=request)
    await db.delete(u)
    await db.commit()
    return Ok(message="Đã xóa tài khoản")


@router.delete("/users/{uid}/devices/{did}", response_model=Ok)
async def kick_device(uid: uuid.UUID, did: uuid.UUID, admin: AdminUser, db: DB, request: Request):
    d = await db.get(UserDevice, did)
    if d and d.user_id == uid:
        await audit(db, admin, "DEVICE_KICK", "user", str(uid), before={"device": d.name or d.platform}, request=request)
        await db.delete(d)
        await db.commit()
    return Ok(message="Đã đăng xuất thiết bị")


# ---------------------------------------------------------------- invitations
@router.get("/invitations")
async def invitations(admin: AdminUser, db: DB):
    rows = (await db.execute(select(Invitation).order_by(desc(Invitation.created_at)).limit(200))).scalars().all()
    return [{**row(i, ["code", "email", "note", "auto_activate", "valid_months", "expires_at", "used_at", "created_at"]), "used_by": str(i.used_by) if i.used_by else None,
             "link": f"{settings.public_web_url}/register?invite={i.code}", "status": "Đã dùng" if i.used_at else ("Hết hạn" if i.expires_at and i.expires_at < datetime.now(UTC) else "Còn hiệu lực")} for i in rows]


@router.post("/invitations")
async def create_invitation(body: InviteIn, admin: AdminUser, db: DB, request: Request):
    code = new_invite_code()
    while await db.get(Invitation, code):
        code = new_invite_code()
    inv = Invitation(code=code, created_by=admin.id, email=body.email, note=body.note, auto_activate=body.auto_activate, valid_months=body.valid_months,
                     expires_at=datetime.now(UTC) + timedelta(days=body.expires_days))
    db.add(inv)
    await audit(db, admin, "INVITE_CREATE", "invitation", code, after=body.model_dump(), request=request)
    await db.commit()
    return {"code": code, "link": f"{settings.public_web_url}/register?invite={code}"}


@router.delete("/invitations/{code}", response_model=Ok)
async def delete_invitation(code: str, admin: AdminUser, db: DB, request: Request):
    inv = await db.get(Invitation, code)
    if inv:
        await audit(db, admin, "INVITE_DELETE", "invitation", code, request=request)
        await db.delete(inv)
        await db.commit()
    return Ok()


# ---------------------------------------------------------------- config (A05)
@router.get("/config")
async def config(admin: AdminUser, db: DB):
    return await all_config(db)


@router.get("/config/{key}/history")
async def config_history(key: str, admin: AdminUser, db: DB):
    rows = (await db.execute(select(AuditLog).where(AuditLog.target_type == "config", AuditLog.target_id == key).order_by(desc(AuditLog.id)).limit(30))).scalars().all()
    return [row(a, ["id", "actor_email", "action", "before", "after", "created_at"]) for a in rows]


def _check_weights(value: dict):
    for hz, w in value.items():
        if abs(sum(float(x) for x in w.values()) - 100) > 0.01:
            raise bad_request("WEIGHTS_SUM", f"Trọng số khung {hz} phải có tổng 100%")


@router.post("/config/scoring.weights/preview")
async def preview_weights(body: ConfigIn, admin: AdminUser, db: DB):
    """'Ảnh hưởng: N mã đổi xếp loại' before saving new weights — recomputes the composite on the latest scores."""
    _check_weights(body.value)
    d = await db.scalar(select(func.max(StockScore.trade_date)))
    if d is None:
        return {"changed": 0, "total": 0, "by_horizon": {}}
    regime_row = (await db.execute(select(MarketRegime).order_by(desc(MarketRegime.trade_date)).limit(1))).scalar_one_or_none()
    regime = regime_row.regime if regime_row else "UPTREND"
    th = (await get_config(db, "risk.company_thresholds")).get("downgrade", 60)
    risk = {r.symbol: r.score for r in (await db.execute(select(CompanyRiskScore))).scalars()}
    rows = (await db.execute(select(StockScore).where(StockScore.trade_date == d))).scalars().all()
    changed, by_hz, examples = 0, {"SHORT": 0, "MID": 0, "LONG": 0}, []
    for r in rows:
        if r.tech is None or r.fund is None:
            continue
        comp = composite(r.tech, r.fund, r.sector or 50.0, r.pattern_ai or 50.0, body.value, regime)
        new = {hz: rating_for(comp[hz]) for hz in comp}
        if (risk.get(r.symbol) or 0) >= th:
            new = {hz: downgrade(v) for hz, v in new.items()}
        old = {"SHORT": r.rating_short, "MID": r.rating_mid, "LONG": r.rating_long}
        diff = [hz for hz in new if new[hz] != old[hz]]
        if diff:
            changed += 1
            for hz in diff:
                by_hz[hz] += 1
            if len(examples) < 8:
                examples.append({"symbol": r.symbol, "from": old["MID"], "to": new["MID"]})
    return {"changed": changed, "total": len(rows), "by_horizon": by_hz, "examples": examples}


@router.put("/config/{key}")
async def put_config(key: str, body: ConfigIn, admin: AdminUser, db: DB, request: Request):
    if key not in DEFAULTS:
        raise not_found("Khóa cấu hình không tồn tại")
    if key == "scoring.weights":
        _check_weights(body.value)
    if key == "risk.score_weights" and abs(sum(float(v) for v in body.value.values()) - 100) > 0.01:
        raise bad_request("WEIGHTS_SUM", "Tổng 6 trọng số rủi ro phải bằng 100")
    if key == "scoring.thresholds":
        v = body.value
        if not (v["STRONG_BUY"] > v["BUY"] > v["HOLD"] > v["REDUCE"] >= 0):
            raise bad_request("THRESHOLDS_ORDER", "Ngưỡng phải giảm dần: Mua mạnh > Tích lũy > Nắm giữ > Giảm tỷ trọng")
    before = await get_config(db, key)
    await set_config(db, key, body.value, admin.email)
    await audit(db, admin, "CONFIG_SET", "config", key, before={"value": before}, after={"value": body.value}, request=request)
    await db.commit()
    return {"key": key, "value": body.value}


@router.post("/config/{key}/reset")
async def reset_config(key: str, admin: AdminUser, db: DB, request: Request):
    if key not in DEFAULTS:
        raise not_found()
    before = await get_config(db, key)
    await set_config(db, key, DEFAULTS[key][0], admin.email)
    await audit(db, admin, "CONFIG_RESET", "config", key, before={"value": before}, after={"value": DEFAULTS[key][0]}, request=request)
    await db.commit()
    return {"key": key, "value": DEFAULTS[key][0]}


# ---------------------------------------------------------------- strategies (A03)
def _param_fields() -> dict[str, dict]:
    return {f["key"]: f for f in CONFIG_META["strategy.params"]["fields"]}


def _strategy_out(s: Strategy, live: dict) -> dict:
    fields = _param_fields()
    keys = STRATEGY_PARAM_KEYS.get(s.code, [])
    return {**row(s, ["code", "name", "signal_type", "horizon", "description", "enabled", "version", "backtest_years", "win_rate", "avg_return", "max_drawdown", "trades", "updated_at", "draft_updated_at"]),
            "params": {k: live.get(k, DEFAULT_PARAMS.get(k)) for k in keys}, "fields": [fields[k] for k in keys if k in fields],
            "draft_params": s.draft_params, "draft_backtest": s.draft_backtest, "running": f"strategy_backtest:{s.code}" in RUNNING}


@router.get("/strategies")
async def strategies(admin: AdminUser, db: DB):
    live = await get_config(db, "strategy.params")
    rows = (await db.execute(select(Strategy).order_by(Strategy.signal_type, Strategy.code))).scalars().all()
    last_bt = (await db.execute(select(JobRun).where(JobRun.name == "strategy_backtest").order_by(desc(JobRun.id)).limit(1))).scalar_one_or_none()
    return {"items": [_strategy_out(s, live) for s in rows], "backtest_all_running": "strategy_backtest" in RUNNING,
            "last_backtest": row(last_bt, ["status", "started_at", "summary"]) if last_bt else None}


@router.put("/strategies/{code}")
async def put_strategy(code: str, body: StrategyIn, admin: AdminUser, db: DB, request: Request):
    s = await db.get(Strategy, code)
    if not s:
        raise not_found()
    before = row(s, ["enabled", "name"])
    if body.enabled is not None:
        if body.enabled and (s.backtest_years or 0) < 5:
            raise bad_request("BACKTEST_REQUIRED", "Chiến lược chỉ bật được khi đã có backtest ≥ 5 năm (BR-12)")
        s.enabled = body.enabled
    if body.name:
        s.name = body.name
    await audit(db, admin, "STRATEGY_SET", "strategy", code, before=before, after=body.model_dump(exclude_unset=True, exclude={"params"}), request=request)
    await db.commit()
    await db.refresh(s)
    return _strategy_out(s, await get_config(db, "strategy.params"))


@router.put("/strategies/{code}/draft")
async def save_draft(code: str, body: DraftIn, admin: AdminUser, db: DB, request: Request):
    """'Lưu bản nháp': parameter overrides for the next version; the live params stay in force."""
    s = await db.get(Strategy, code)
    if not s:
        raise not_found()
    allowed = set(STRATEGY_PARAM_KEYS.get(code, []))
    params = {k: v for k, v in body.params.items() if k in allowed}
    if not params:
        raise bad_request("NO_PARAMS", "Chiến lược này không có tham số chỉnh được")
    s.draft_params, s.draft_backtest, s.draft_updated_at = params, None, datetime.now(UTC)
    await audit(db, admin, "STRATEGY_DRAFT", "strategy", code, after=params, request=request)
    await db.commit()
    await db.refresh(s)
    return _strategy_out(s, await get_config(db, "strategy.params"))


@router.delete("/strategies/{code}/draft")
async def drop_draft(code: str, admin: AdminUser, db: DB, request: Request):
    s = await db.get(Strategy, code)
    if not s:
        raise not_found()
    s.draft_params = s.draft_backtest = s.draft_updated_at = None
    await audit(db, admin, "STRATEGY_DRAFT_DROP", "strategy", code, request=request)
    await db.commit()
    return Ok()


@router.post("/strategies/{code}/backtest")
async def backtest_strategy(code: str, admin: AdminUser, db: DB, request: Request):
    """Runs the draft-vs-live comparison in the background (150 most liquid symbols, 3 years); poll GET /strategies."""
    s = await db.get(Strategy, code)
    if not s or not s.draft_params:
        raise bad_request("NO_DRAFT", "Lưu bản nháp trước khi so sánh backtest")
    name = f"strategy_backtest:{code}"
    if name in RUNNING:
        return Ok(message="Backtest đang chạy")
    await audit(db, admin, "JOB_RUN", "job", name, request=request)
    await db.commit()
    from app.tasks.scheduler import run_named

    asyncio.create_task(run_named(name, f"admin:{admin.email}"))
    return Ok(message="Đã bắt đầu backtest, kết quả hiện sau vài phút")


@router.post("/strategies/{code}/activate-draft")
async def activate_draft(code: str, admin: AdminUser, db: DB, request: Request):
    """'Bật phiên bản mới': draft params become live (strategy.params), version +1."""
    s = await db.get(Strategy, code)
    if not s or not s.draft_params:
        raise bad_request("NO_DRAFT", "Chiến lược chưa có bản nháp")
    live = dict(await get_config(db, "strategy.params"))
    before = {k: live.get(k) for k in s.draft_params}
    live.update(s.draft_params)
    await set_config(db, "strategy.params", live, admin.email)
    s.params = {**(s.params or {}), **s.draft_params}
    s.version += 1
    s.draft_params = s.draft_backtest = s.draft_updated_at = None
    await audit(db, admin, "STRATEGY_VERSION", "strategy", code, before=before, after={"version": s.version, **s.params}, request=request)
    await db.commit()
    await db.refresh(s)
    return _strategy_out(s, live)


@router.post("/strategies/backtest-all")
async def backtest_all(admin: AdminUser, db: DB, request: Request):
    if "strategy_backtest" in RUNNING:
        return Ok(message="Backtest toàn bộ đang chạy")
    await audit(db, admin, "JOB_RUN", "job", "strategy_backtest", request=request)
    await db.commit()
    from app.tasks.scheduler import run_named

    asyncio.create_task(run_named("strategy_backtest", f"admin:{admin.email}"))
    return Ok(message="Đã bắt đầu backtest 5 năm cho mọi chiến lược (khoảng 20 phút)")


_PERF_CTE = """
WITH idx AS (SELECT trade_date, close, row_number() OVER (ORDER BY trade_date) rn FROM index_daily WHERE index_code = 'VNINDEX'),
sig AS (SELECT s.id, s.trade_date, s.strategy_code, s.signal_type, s.horizon, s.rating, s.symbol, o.return_pct, o.result,
               case when s.regime_at_signal in ('CORRECTION','DOWNTREND') then 'DOWN' when s.regime_at_signal = 'PRESSURE' then 'PRESSURE' else 'UP' end regime3,
               (SELECT i.rn FROM idx i WHERE i.trade_date <= s.trade_date ORDER BY i.trade_date DESC LIMIT 1) rn0
        FROM signals s JOIN signal_outcomes o ON o.signal_id = s.id AND o.days = :days WHERE s.trade_date >= :since),
sig2 AS (SELECT sig.*, (i1.close / i0.close - 1) * 100 idx_ret,
                case when sig.signal_type in ('SELL','TAKE_PROFIT') then (case when sig.return_pct < 0 then 1.0 else 0.0 end)
                     else (case when sig.result in ('TP_HIT','WIN') then 1.0 else 0.0 end) end ok
         FROM sig LEFT JOIN idx i0 ON i0.rn = sig.rn0 LEFT JOIN idx i1 ON i1.rn = sig.rn0 + :days)
"""


def _suggest(cells: dict[str, dict]) -> str:
    def wr(k):
        c = cells.get(k)
        return (c["win_rate"], c["samples"]) if c else (None, 0)

    up, pr, dn = wr("UP"), wr("PRESSURE"), wr("DOWN")
    if all(w is not None and w >= 60 and n >= 30 for w, n in (up, pr, dn)):
        return "Hiệu quả ở mọi trạng thái"
    if dn[0] is not None and dn[0] < 50 and dn[1] >= 30:
        return "Tắt khi thị trường giảm"
    if dn[1] < 30 and (dn[0] is None or dn[0] < 50):
        return "Cần thêm mẫu khi thị trường giảm"
    if up[0] is not None and up[0] >= 60 and all(w is not None and w < 60 for w, _ in (pr, dn)):
        return "Chỉ dùng khi thị trường tăng"
    return "Giữ nguyên"


@router.get("/strategies/performance")
async def strategy_performance(admin: AdminUser, db: DB, months: int = 12, days: int = 20):
    since = today_vn() - timedelta(days=30 * months)
    p = {"days": days, "since": since}
    q = lambda sql: db.execute(text(_PERF_CTE + sql), p)
    by_sr = (await q("""SELECT strategy_code, signal_type, horizon, regime3, count(*) n, avg(ok)*100 win_rate, avg(return_pct) avg_return, avg(return_pct - idx_ret) excess
                        FROM sig2 GROUP BY 1,2,3,4 ORDER BY 1,4""")).all()
    by_rating = (await q("""SELECT rating, count(*) n, avg(ok)*100 win_rate, avg(return_pct) avg_return, avg(return_pct - idx_ret) excess FROM sig2 WHERE rating IS NOT NULL GROUP BY 1""")).all()
    by_sector = (await q("""SELECT st.industry_code, count(*) n, avg(ok)*100 win_rate FROM sig2 JOIN stocks st ON st.symbol = sig2.symbol WHERE signal_type = 'BUY' GROUP BY 1 ORDER BY 3 DESC""")).all()
    monthly = (await q("""SELECT to_char(trade_date,'YYYY-MM') m, count(*) n, avg(ok)*100 win_rate, avg(return_pct) avg_return, avg(return_pct - idx_ret) excess FROM sig2 WHERE signal_type = 'BUY' GROUP BY 1 ORDER BY 1""")).all()
    kpi = (await q("""SELECT count(*) n, avg(case when result = 'TP_HIT' then 1.0 else 0.0 end)*100 tp1, avg(return_pct) ar, avg(return_pct - idx_ret) excess, avg(idx_ret) idx FROM sig2 WHERE signal_type = 'BUY'""")).one()
    names = {s.code: s.name for s in (await db.execute(select(Strategy))).scalars()}
    from app.ingestion.icb import ICB_LV2

    strat_rows: dict[tuple, dict] = {}
    for r in by_sr:
        key = (r.strategy_code, r.horizon)
        strat_rows.setdefault(key, {"strategy": r.strategy_code, "name": names.get(r.strategy_code, r.strategy_code), "signal_type": r.signal_type, "horizon": r.horizon, "cells": {}})
        strat_rows[key]["cells"][r.regime3] = {"samples": int(r.n), "win_rate": round(float(r.win_rate), 1), "avg_return": round(float(r.avg_return), 2), "excess": round(float(r.excess), 2) if r.excess is not None else None}
    for v in strat_rows.values():
        v["suggestion"] = _suggest(v["cells"])
    f = lambda x, d=1: round(float(x), d) if x is not None else None
    return {"months": months, "days": days, "regimes": ["UP", "PRESSURE", "DOWN"], "fee_note": "Mô phỏng sát thực tế: mua giá mở cửa phiên sau, bán sớm nhất T+2, cắt lỗ/chốt lời theo giá mở cửa khi có gap, trừ phí 0,15%×2, thuế 0,1% và trượt giá theo thanh khoản",
            "kpis": {"buy_signals": int(kpi.n or 0), "tp1_rate": f(kpi.tp1), "target_tp1_rate": 55, "avg_return": f(kpi.ar, 2), "excess_vs_index": f(kpi.excess, 2), "vnindex_return": f(kpi.idx, 2)},
            "by_strategy_regime": list(strat_rows.values()),
            "by_rating": [{"rating": r.rating, "samples": int(r.n), "win_rate": f(r.win_rate), "avg_return": f(r.avg_return, 2), "excess": f(r.excess, 2)} for r in by_rating],
            "by_sector": [{"industry_code": r.industry_code, "name": ICB_LV2.get(r.industry_code, (r.industry_code,))[0], "samples": int(r.n), "win_rate": f(r.win_rate)} for r in by_sector],
            "monthly": [{"month": r.m, "samples": int(r.n), "win_rate": f(r.win_rate), "avg_return": f(r.avg_return, 2), "excess": f(r.excess, 2)} for r in monthly]}


@router.get("/risk-avoided")
async def risk_avoided(admin: AdminUser, db: DB, days: int = 180):
    """A10 'Rủi ro tránh được': what happened after RED checks, circuit breakers and stop breaches, system-wide."""
    from app.services.avoided import avoided_risk, user_drawdown_vs_index

    out = await avoided_risk(db, days)
    dds = []
    for (uid,) in (await db.execute(select(User.id).where(User.status == "ACTIVE"))).all():
        r = await user_drawdown_vs_index(db, uid, 90)
        if r and r["vnindex_mdd"] is not None:
            dds.append(r)
    out["drawdown"] = {"users": len(dds), "median_portfolio_mdd": sorted(d["portfolio_mdd"] for d in dds)[len(dds) // 2] if dds else None,
                       "vnindex_mdd": dds[0]["vnindex_mdd"] if dds else None, "pct_better_than_index": round(sum(1 for d in dds if d["portfolio_mdd"] > d["vnindex_mdd"]) / len(dds) * 100) if dds else None}
    return out


# ---------------------------------------------------------------- jobs & data (A04)
async def _quality(db) -> list[dict]:
    last = (await db.execute(text("SELECT max(trade_date) FROM price_daily"))).scalar()
    if last is None:
        return []
    limits = await get_config(db, "market.limits")
    q = (await db.execute(text("""WITH act AS (SELECT symbol, exchange FROM stocks WHERE is_active),
        last AS (SELECT p.symbol, p.close, lag(p.close) OVER (PARTITION BY p.symbol ORDER BY p.trade_date) prev, p.trade_date
                 FROM price_daily p JOIN act ON act.symbol = p.symbol WHERE p.trade_date >= CAST(:d AS date) - 7),
        gap AS (SELECT l.symbol, abs(l.close / nullif(l.prev, 0) - 1) * 100 g, act.exchange FROM last l JOIN act ON act.symbol = l.symbol WHERE l.trade_date = :d AND l.prev IS NOT NULL)
        SELECT (SELECT count(*) FROM act) n_active,
               (SELECT count(*) FROM act WHERE NOT EXISTS (SELECT 1 FROM price_daily p WHERE p.symbol = act.symbol AND p.trade_date = :d)) missing,
               (SELECT string_agg(symbol, ', ') FROM (SELECT symbol FROM act WHERE NOT EXISTS (SELECT 1 FROM price_daily p WHERE p.symbol = act.symbol AND p.trade_date = :d) LIMIT 5) x) missing_syms,
               (SELECT count(*) FROM gap WHERE g > (case exchange when 'HOSE' then CAST(:hose AS float) when 'HNX' then CAST(:hnx AS float) else CAST(:upcom AS float) end) + 0.5) abnormal,
               (SELECT string_agg(symbol, ', ') FROM (SELECT symbol FROM gap WHERE g > (case exchange when 'HOSE' then CAST(:hose AS float) when 'HNX' then CAST(:hnx AS float) else CAST(:upcom AS float) end) + 0.5 LIMIT 5) x) abnormal_syms,
               (SELECT count(DISTINCT gap.symbol) FROM gap JOIN corporate_actions c ON c.symbol = gap.symbol AND c.ex_date BETWEEN CAST(:d AS date) - 4 AND CAST(:d AS date)
                       AND c.kind IN ('STOCK_DIVIDEND','BONUS','ISSUE','CASH_DIVIDEND') WHERE g > 3) unadjusted,
               (SELECT count(*) FROM price_daily p WHERE p.trade_date = :d AND (p.high < p.low OR p.close <= 0)) bad_candles"""),
                           {"d": last, "hose": limits.get("HOSE", 7), "hnx": limits.get("HNX", 10), "upcom": limits.get("UPCOM", 15)})).one()
    fs = (await db.execute(text("""WITH latest AS (SELECT year, quarter FROM financial_statements GROUP BY 1,2 ORDER BY 1 DESC, 2 DESC LIMIT 1)
        SELECT (SELECT year FROM latest), (SELECT quarter FROM latest),
               (SELECT count(DISTINCT f.symbol) FROM financial_statements f JOIN latest l ON l.year = f.year AND l.quarter = f.quarter JOIN stocks s ON s.symbol = f.symbol AND s.is_active)"""))).one()
    imp = (await db.execute(select(JobRun).where(JobRun.name == "price_file_import").order_by(desc(JobRun.id)).limit(1))).scalar_one_or_none()
    mism = (imp.meta or {}).get("mismatches") if imp else None
    n = q.n_active or 1
    return [{"check": "Mã thiếu dữ liệu giá", "value": q.missing, "detail": q.missing_syms, "ok": q.missing < 0.05 * n},
            {"check": "Lệch giá giữa 2 nguồn > 0,5%", "value": len(mism) if isinstance(mism, list) else (mism if mism is not None else "—"),
             "detail": "đối chiếu ở lần nhập file giá gần nhất" if imp else "chỉ đối chiếu được khi nhập file giá", "ok": (not mism) if imp else None},
            {"check": "Biến động bất thường > biên độ", "value": q.abnormal, "detail": q.abnormal_syms, "ok": q.abnormal == 0},
            {"check": "Sự kiện quyền chưa điều chỉnh", "value": q.unadjusted, "detail": None, "ok": q.unadjusted == 0},
            {"check": f"BCTC quý {fs[1]}/{fs[0]} đã có" if fs[0] else "BCTC quý gần nhất", "value": f"{fs[2]} / {q.n_active} mã", "detail": None, "ok": (fs[2] or 0) >= 0.5 * n},
            {"check": "Nến lỗi (cao < thấp, đóng cửa ≤ 0)", "value": q.bad_candles, "detail": None, "ok": q.bad_candles == 0}]


async def _latency_buckets(db) -> list[dict]:
    rows = (await db.execute(text("""WITH d AS (SELECT max(sent_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date dd FROM notification_deliveries WHERE channel <> 'inapp' AND latency_ms IS NOT NULL)
        SELECT to_char(date_trunc('hour', t) + floor(extract(minute from t) / 15) * interval '15 min', 'HH24:MI') b, percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) p95, count(*) n
        FROM (SELECT sent_at AT TIME ZONE 'Asia/Ho_Chi_Minh' t, latency_ms FROM notification_deliveries, d WHERE channel <> 'inapp' AND latency_ms IS NOT NULL
              AND (sent_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date = d.dd) x WHERE t::time BETWEEN '09:00' AND '15:00' GROUP BY 1 ORDER BY 1"""))).all()
    return [{"bucket": r.b, "p95_ms": int(r.p95) if r.p95 is not None else None, "count": int(r.n)} for r in rows]


@router.get("/jobs")
async def jobs(admin: AdminUser, db: DB, limit: int = 100):
    rows = await recent_jobs(db, max(limit, 150))
    from app.tasks.eod import EOD_STEP_INFO
    from app.tasks.scheduler import scheduled_jobs

    sched = {j["id"]: j for j in scheduled_jobs()}
    last_by_name: dict[str, JobRun] = {}
    for j in rows:
        key = "eod" if j.name.startswith("eod.") else j.name
        last_by_name.setdefault(key, j)
    eod_failed = any(j.name.startswith("eod.") and j.status == "FAILED" and j.started_at >= datetime.now(UTC) - timedelta(hours=12) for j in rows)
    table = []
    for name, (label, schedule, queue) in JOB_INFO.items():
        last = last_by_name.get(name)
        running = name in RUNNING or (name == "eod" and any(k.startswith("eod.") for k in RUNNING))
        status = "RUNNING" if running else (("FAILED" if eod_failed else last.status) if last and name == "eod" else (last.status if last else "NEVER"))
        table.append({"name": name, "label": label, "schedule": schedule, "queue": queue, "next_run": sched.get(name, {}).get("next_run"),
                      "last_run_at": clean(last.started_at) if last else None, "duration_ms": last.duration_ms if last else None, "status": status,
                      "summary": (last.summary if last else None), "running": running, "stoppable": running and name not in ("dispatch",)})
    now = datetime.now(UTC)
    failed_24h = [j for j in rows if j.status == "FAILED" and j.started_at >= now - timedelta(days=1)]
    queue = await db.scalar(select(func.count(NotificationDelivery.id)).where(NotificationDelivery.status == "PENDING"))
    db_size = (await db.execute(text("SELECT pg_database_size(current_database())"))).scalar()
    disk = (await db.execute(text("SELECT pg_size_pretty(pg_database_size(current_database()))"))).scalar()
    backup = last_by_name.get("backup")
    kpis = {"queue_pending": queue, "queue_warn": 1000, "failed_24h": len(failed_24h), "failed_names": sorted({j.name for j in failed_24h})[:4],
            "db_size_mb": round(db_size / 1e6, 1) if db_size else None, "db_size_pretty": disk,
            "last_backup_at": clean(backup.started_at) if backup else None, "last_backup_status": backup.status if backup else None, "last_backup_summary": backup.summary if backup else None,
            "last_restore_test": ((backup.meta or {}).get("restore_test") or {}).get("ok") if backup else None}
    runs = [row(j, ["id", "name", "status", "started_at", "finished_at", "duration_ms", "summary", "triggered_by"]) | {"label": EOD_STEP_INFO.get(j.name, (JOB_INFO.get(j.name, (j.name,))[0],))[0], "has_error": bool(j.error)} for j in rows[:limit]]
    return {"kpis": kpis, "jobs": table, "runs": runs, "latency": await _latency_buckets(db), "quality": await _quality(db), "schedule": list(sched.values())}


@router.get("/jobs/runs/{run_id}")
async def job_run_detail(run_id: int, admin: AdminUser, db: DB):
    j = await db.get(JobRun, run_id)
    if not j:
        raise not_found()
    return row(j, ["id", "name", "status", "started_at", "finished_at", "duration_ms", "summary", "meta", "error", "triggered_by"])


@router.post("/jobs/{name}/run")
async def run_job_now(name: str, admin: AdminUser, db: DB, request: Request):
    from app.tasks.scheduler import run_named

    if is_market_open() and name.startswith("eod") and not request.query_params.get("confirm"):
        raise bad_request("CONFIRM_REQUIRED", "Đang trong giờ giao dịch. Thêm ?confirm=1 để chạy ngay.")
    if name in RUNNING:
        raise bad_request("ALREADY_RUNNING", "Tác vụ này đang chạy")
    await audit(db, admin, "JOB_RUN", "job", name, request=request)
    await db.commit()
    asyncio.create_task(run_named(name, f"admin:{admin.email}"))
    return Ok(message=f"Đã xếp lịch chạy {JOB_INFO.get(name, (name,))[0]}")


@router.post("/jobs/{name}/stop")
async def stop_job(name: str, admin: AdminUser, db: DB, request: Request):
    names = [name] + ([k for k in RUNNING if k.startswith("eod.")] if name == "eod" else [])
    stopped = [n for n in names if cancel_job(n)]
    if not stopped:
        raise bad_request("NOT_RUNNING", "Tác vụ không chạy trong tiến trình này")
    await audit(db, admin, "JOB_STOP", "job", name, after={"stopped": stopped}, request=request)
    await db.commit()
    return Ok(message=f"Đã gửi yêu cầu dừng {', '.join(stopped)}")


@router.get("/data-sources")
async def data_sources(admin: AdminUser, db: DB):
    rows = (await db.execute(select(DataSource).order_by(DataSource.priority))).scalars().all()
    last_price = (await db.execute(text("SELECT max(trade_date), count(distinct symbol) FROM price_daily"))).one()
    return {"sources": [row(s, ["code", "name", "role", "priority", "enabled", "status", "last_ok_at", "last_error", "latency_ms", "consecutive_failures"]) for s in rows],
            "coverage": {"last_price_date": clean(last_price[0]), "symbols_with_prices": last_price[1]}, "quality": await _quality(db)}


@router.put("/data-sources/{code}")
async def put_source(code: str, admin: AdminUser, db: DB, request: Request, enabled: bool | None = None, priority: int | None = None, role: str | None = None):
    s = await db.get(DataSource, code)
    if not s:
        raise not_found()
    before = row(s, ["enabled", "priority", "role"])
    if enabled is not None:
        s.enabled = enabled
    if priority is not None:
        s.priority = priority
    if role in ("PRIMARY", "BACKUP"):
        s.role = role
    await audit(db, admin, "SOURCE_SET", "data_source", code, before=before, after=row(s, ["enabled", "priority", "role"]), request=request)
    await db.commit()
    return row(s, ["code", "name", "role", "priority", "enabled", "status"])


@router.post("/price-imports")
async def price_import_preview(admin: AdminUser, db: DB, file: UploadFile = File(...)):  # noqa: B008
    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        raise bad_request("FILE_TOO_BIG", "Tệp tối đa 20 MB")
    return await preview_file(db, raw, file.filename or "upload.csv")


@router.post("/price-imports/{import_id}/commit")
async def price_import_commit(import_id: str, admin: AdminUser, db: DB, request: Request, mode: str = "SKIP_EXISTING"):
    if mode not in ("SKIP_EXISTING", "OVERWRITE"):
        raise bad_request("MODE", "mode phải là SKIP_EXISTING hoặc OVERWRITE")
    res = await commit_import(db, import_id, mode, admin.email)
    await audit(db, admin, "PRICE_IMPORT", "price_import", import_id, after={"mode": mode, **{k: v for k, v in res.items() if k != "symbols"}}, request=request)
    await db.commit()
    from app.tasks.scheduler import run_named

    asyncio.create_task(run_named("eod.recompute", f"admin:{admin.email}"))
    return res


# ---------------------------------------------------------------- audit (A07), broadcast (A06), AI cost (A08), risk (A09)
@router.get("/audit-logs")
async def audit_logs(admin: AdminUser, db: DB, action: str | None = None, actor: str | None = None, page: int = 1, size: int = Query(50, le=200)):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action.upper())
    if actor:
        stmt = stmt.where(AuditLog.actor_email.ilike(f"%{actor}%"))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (await db.execute(stmt.order_by(desc(AuditLog.id)).offset((page - 1) * size).limit(size))).scalars().all()
    actions = sorted(a for (a,) in (await db.execute(select(AuditLog.action).distinct())).all())
    return {"items": [row(a, ["id", "actor_email", "action", "target_type", "target_id", "before", "after", "ip", "created_at"]) for a in rows], "total": total, "page": page, "size": size, "actions": actions}


@router.get("/broadcasts")
async def broadcasts(admin: AdminUser, db: DB):
    rows = (await db.execute(select(Broadcast).order_by(desc(Broadcast.created_at)).limit(50))).scalars().all()
    reads = dict((await db.execute(text("""SELECT (data->>'broadcast_id') b, count(*) FROM alerts WHERE kind = 'SYSTEM' AND read_at IS NOT NULL AND (data::jsonb) ? 'broadcast_id' GROUP BY 1"""))).all())
    return [{"id": str(b.id), **row(b, ["title", "body", "channels", "sent_count", "created_at"]), "read_count": int(reads.get(str(b.id), b.read_count or 0))} for b in rows]


@router.post("/broadcasts")
async def send_broadcast(body: BroadcastIn, admin: AdminUser, db: DB, request: Request):
    b = Broadcast(created_by=admin.id, title=body.title, body=body.body, channels=body.channels)
    db.add(b)
    await db.flush()
    n = 0
    for u in (await db.execute(select(User).where(User.status == "ACTIVE"))).scalars():
        a = await create_alert(db, u, kind="SYSTEM", priority="INFO", title=body.title, body=body.body, data={"broadcast_id": str(b.id)}, channels=body.channels, dedupe_key=f"bc:{b.id}")
        n += 1 if a else 0
    b.sent_count = n
    await audit(db, admin, "BROADCAST", "broadcast", str(b.id), after={"title": body.title, "sent": n}, request=request)
    await db.commit()
    await dispatch_pending(db)
    await db.commit()
    return {"id": str(b.id), "sent_count": n}


@router.get("/ai-usage")
async def ai_usage(admin: AdminUser, db: DB, days: int = 30):
    since = datetime.now(UTC) - timedelta(days=days)
    daily = (await db.execute(text("""SELECT date(m.created_at) d, count(*) filter (where m.role='user') questions, coalesce(sum(m.input_tokens),0) inp, coalesce(sum(m.output_tokens),0) outp
                                      FROM ai_messages m WHERE m.created_at >= :s GROUP BY 1 ORDER BY 1"""), {"s": since})).all()
    by_user = (await db.execute(text("""SELECT u.email, count(*) filter (where m.role='user') questions, coalesce(sum(m.input_tokens),0) inp, coalesce(sum(m.output_tokens),0) outp
                                        FROM ai_messages m JOIN ai_conversations c ON c.id=m.conversation_id JOIN users u ON u.id=c.user_id WHERE m.created_at >= :s GROUP BY 1 ORDER BY 2 DESC LIMIT 30"""), {"s": since})).all()
    by_task = (await db.execute(text("""SELECT coalesce(c.context->>'screen', 'chat') task, count(*) filter (where m.role='user') questions, coalesce(sum(m.input_tokens),0) inp, coalesce(sum(m.output_tokens),0) outp
                                        FROM ai_messages m JOIN ai_conversations c ON c.id=m.conversation_id WHERE m.created_at >= :s GROUP BY 1 ORDER BY 3 DESC"""), {"s": since})).all()
    jobs_ai = (await db.execute(text("""SELECT name, count(*) runs, coalesce(sum((meta->>'tokens')::bigint), 0) tokens FROM job_runs
                                        WHERE started_at >= :s AND name IN ('eod.explain', 'coach_weekly', 'news_sync') AND (meta::jsonb) ? 'tokens' GROUP BY 1"""), {"s": since})).all()
    cost = lambda i, o: round(i / 1e6 * 5 + o / 1e6 * 25, 3)
    limits = await get_config(db, "ai.limits")
    tasks_vi = {"chat": "Hỏi AI (chung)", "market": "Hỏi AI – Thị trường", "stock": "Hỏi AI – Phân tích mã", "portfolio": "Hỏi AI – Danh mục", "screener": "Hỏi AI – Bộ lọc", "alerts": "Hỏi AI – Cảnh báo",
                "eod.explain": "AI viết nhận định cuối ngày", "coach_weekly": "Huấn luyện viên AI hằng tuần", "news_sync": "AI chấm cảm xúc tin tức"}
    return {"limits": limits, "model": settings.ai_model, "days": days,
            "daily": [{"date": clean(r.d), "questions": r.questions, "input_tokens": int(r.inp), "output_tokens": int(r.outp), "cost_usd": cost(r.inp, r.outp)} for r in daily],
            "by_user": [{"email": r.email, "questions": r.questions, "cost_usd": cost(r.inp, r.outp)} for r in by_user],
            "by_task": [{"task": tasks_vi.get(r.task, r.task), "questions": r.questions, "input_tokens": int(r.inp), "output_tokens": int(r.outp), "cost_usd": cost(r.inp, r.outp)} for r in by_task]
                       + [{"task": tasks_vi.get(r.name, r.name), "questions": int(r.runs), "input_tokens": int(r.tokens), "output_tokens": 0, "cost_usd": cost(r.tokens, 0)} for r in jobs_ai]}


@router.get("/risk-stats")
async def risk_stats(admin: AdminUser, db: DB, days: int = 90):
    since = datetime.now(UTC) - timedelta(days=days)
    ev = (await db.execute(select(RiskGuardEvent.kind, func.count(RiskGuardEvent.id)).where(RiskGuardEvent.created_at >= since).group_by(RiskGuardEvent.kind))).all()
    checks = (await db.execute(select(PretradeCheck.result, func.count(PretradeCheck.id)).where(PretradeCheck.created_at >= since).group_by(PretradeCheck.result))).all()
    return {"days": days, "events": {k: c for k, c in ev}, "pretrade": {k: c for k, c in checks}, "defaults": await get_config(db, "risk.defaults"), "company_thresholds": await get_config(db, "risk.company_thresholds"), "chase": await get_config(db, "risk.chase")}


@router.get("/margin-lists")
async def margin_lists(admin: AdminUser, db: DB):
    return await get_config(db, "risk.margin_lists") or {}


async def _save_margin(db, admin, body: dict, request: Request, source: str) -> dict:
    DEFAULTS.setdefault("risk.margin_lists", ({}, "Danh sách mã cho vay ký quỹ theo CTCK", "risk"))
    before = await get_config(db, "risk.margin_lists") or {}
    cleaned = {k.strip(): sorted({s.strip().upper() for s in v if s and s.strip()}) for k, v in body.items() if k.strip()}
    await set_config(db, "risk.margin_lists", cleaned, admin.email)
    await audit(db, admin, "MARGIN_LISTS", "config", "risk.margin_lists", before={"brokers": {k: len(v) for k, v in before.items()}}, after={"brokers": {k: len(v) for k, v in cleaned.items()}, "source": source}, request=request)
    await db.commit()
    return cleaned


@router.put("/margin-lists")
async def put_margin_lists(body: dict, admin: AdminUser, db: DB, request: Request):
    """{"VCBS": ["FPT","HPG",...], "Pinetree": [...]}"""
    return await _save_margin(db, admin, body, request, "manual")


@router.post("/margin-lists/import")
async def import_margin_lists(admin: AdminUser, db: DB, request: Request, file: UploadFile = File(...), replace: bool = False):  # noqa: B008
    """CSV/TXT/Excel with two columns: công ty chứng khoán, mã (any header containing 'ctck'/'công ty' and 'mã'/'symbol');
    or one column per broker (header = broker name, cells = symbols)."""
    import pandas as pd

    raw = await file.read()
    name = (file.filename or "").lower()
    try:
        df = pd.read_excel(io.BytesIO(raw), dtype=str) if name.endswith((".xlsx", ".xls")) else pd.read_csv(io.BytesIO(raw), dtype=str, sep=None, engine="python")
    except Exception as e:
        raise bad_request("FILE_INVALID", f"Không đọc được tệp: {e}") from e
    df = df.dropna(how="all")
    cols = [str(c).strip().lower() for c in df.columns]
    broker_col = next((i for i, c in enumerate(cols) if any(k in c for k in ("ctck", "công ty", "cong ty", "broker", "firm"))), None)
    sym_col = next((i for i, c in enumerate(cols) if any(k in c for k in ("mã", "ma ck", "symbol", "ticker", "cổ phiếu"))), None)
    lists: dict[str, list[str]] = {}
    if broker_col is not None and sym_col is not None:
        for _, r in df.iterrows():
            b, s = str(r.iloc[broker_col] or "").strip(), str(r.iloc[sym_col] or "").strip().upper()
            if b and s and s != "NAN":
                lists.setdefault(b, []).append(s)
    else:
        for c in df.columns:
            syms = [str(v).strip().upper() for v in df[c].dropna() if str(v).strip() and str(v).strip().lower() != "nan"]
            if syms:
                lists[str(c).strip()] = syms
    if not lists:
        raise bad_request("FILE_EMPTY", "Không tìm thấy cột công ty chứng khoán / mã trong tệp")
    known = {s for (s,) in (await db.execute(select(Stock.symbol))).all()}
    unknown = sorted({s for v in lists.values() for s in v if s not in known})[:20]
    merged = lists if replace else {**(await get_config(db, "risk.margin_lists") or {}), **lists}
    saved = await _save_margin(db, admin, merged, request, f"file:{file.filename}")
    return {"lists": saved, "imported": {k: len(v) for k, v in lists.items()}, "unknown_symbols": unknown}


@router.get("/stocks/{symbol}/flags")
async def get_flags(symbol: str, admin: AdminUser, db: DB):
    st = await db.get(Stock, symbol.upper())
    if not st:
        raise not_found()
    return {"symbol": st.symbol, "status_flags": st.status_flags or [], "is_active": st.is_active}


@router.put("/stocks/{symbol}/flags")
async def put_flags(symbol: str, body: dict, admin: AdminUser, db: DB, request: Request):
    st = await db.get(Stock, symbol.upper())
    if not st:
        raise not_found()
    before = {"status_flags": st.status_flags, "is_active": st.is_active}
    if "status_flags" in body:
        st.status_flags = [f for f in body["status_flags"] if f in ("WARNING", "CONTROL", "RESTRICTED", "SUSPENDED")]
    if "is_active" in body:
        st.is_active = bool(body["is_active"])
    await audit(db, admin, "STOCK_FLAGS", "stock", st.symbol, before=before, after=body, request=request)
    await db.commit()
    return {"symbol": st.symbol, "status_flags": st.status_flags, "is_active": st.is_active}


_ = (BackgroundTasks,)

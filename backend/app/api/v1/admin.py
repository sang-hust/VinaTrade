import asyncio
import io
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, File, Query, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import desc, func, select, text

from app.api.deps import DB, AdminUser, audit
from app.api.presenters import clean, row
from app.core.config import settings
from app.core.errors import bad_request, not_found
from app.core.security import hash_password, new_invite_code
from app.core.vntime import today_vn
from app.ingestion.file_import import commit_import, preview_file
from app.models import (
    AiMessage,
    AuditLog,
    Broadcast,
    DataSource,
    Invitation,
    NotificationDelivery,
    PretradeCheck,
    RiskGuardEvent,
    Signal,
    SignalOutcome,
    SignalReliability,
    Stock,
    Strategy,
    User,
    UserDevice,
    UserSettings,
)
from app.schemas.auth import UserOut
from app.schemas.common import Ok
from app.services.jobs import recent_jobs
from app.services.notify import create_alert, dispatch_pending, send_email
from app.services.riskguard import ensure_user_defaults
from app.services.sysconfig import DEFAULTS, all_config, get_config, set_config

router = APIRouter(prefix="/admin", tags=["admin"])


class ActivateIn(BaseModel):
    valid_months: int | None = None
    max_devices: int | None = 3
    role: str | None = None
    message: str | None = None


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


class BroadcastIn(BaseModel):
    title: str
    body: str
    channels: list[str] = ["push", "telegram"]


# ---------------------------------------------------------------- overview
@router.get("/overview")
async def overview(admin: AdminUser, db: DB):
    now = datetime.now(UTC)
    users_active = await db.scalar(select(func.count(User.id)).where(User.status == "ACTIVE"))
    users_pending = await db.scalar(select(func.count(User.id)).where(User.status == "PENDING"))
    active_7d = await db.scalar(select(func.count(func.distinct(UserDevice.user_id))).where(UserDevice.last_seen_at >= now - timedelta(days=7)))
    d24 = now - timedelta(hours=24)
    sent = await db.scalar(select(func.count(NotificationDelivery.id)).where(NotificationDelivery.sent_at >= d24, NotificationDelivery.status == "SENT"))
    failed = await db.scalar(select(func.count(NotificationDelivery.id)).where(NotificationDelivery.sent_at >= d24, NotificationDelivery.status == "FAILED"))
    p95 = (await db.execute(text("SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) FROM notification_deliveries WHERE sent_at >= :d AND channel <> 'inapp'"), {"d": d24})).scalar()
    win20 = (await db.execute(text("""SELECT avg(case when o.result in ('TP_HIT','WIN') then 1.0 else 0.0 end)*100 FROM signals s JOIN signal_outcomes o ON o.signal_id=s.id AND o.days=20
                                       WHERE s.signal_type='BUY' AND s.trade_date >= :d"""), {"d": today_vn() - timedelta(days=120)})).scalar()
    ai_tokens = (await db.execute(select(func.coalesce(func.sum(AiMessage.input_tokens), 0), func.coalesce(func.sum(AiMessage.output_tokens), 0)).where(AiMessage.created_at >= now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)))).one()
    ai_cost = ai_tokens[0] / 1e6 * 5 + ai_tokens[1] / 1e6 * 25
    budget = (await get_config(db, "ai.limits")).get("monthly_budget_usd", 50)
    jobs = await recent_jobs(db, 40)
    chain = {}
    for j in jobs:
        if j.name.startswith("eod.") and j.name not in chain:
            chain[j.name] = {"name": j.name, "status": j.status, "summary": j.summary, "started_at": clean(j.started_at), "duration_ms": j.duration_ms, "id": j.id, "error": (j.error or "")[-600:] or None}
    from app.tasks.eod import EOD_STEPS
    steps = [chain.get(n, {"name": n, "status": "PENDING"}) for n, _ in EOD_STEPS]
    sources = [row(s, ["code", "name", "role", "priority", "enabled", "status", "last_ok_at", "last_error", "latency_ms", "consecutive_failures"]) for s in (await db.execute(select(DataSource).order_by(DataSource.priority))).scalars()]
    todo = []
    if users_pending:
        todo.append({"kind": "PENDING_USERS", "text": f"{users_pending} tài khoản chờ duyệt", "action": "Duyệt", "route": "/admin/users?status=PENDING"})
    failed_jobs = [j for j in jobs if j.status == "FAILED" and j.started_at >= now - timedelta(days=1)]
    if failed_jobs:
        todo.append({"kind": "FAILED_JOBS", "text": f"{len(failed_jobs)} tác vụ lỗi trong 24 giờ", "action": "Xem", "route": "/admin/jobs"})
    for s in sources:
        if s["status"] == "DOWN":
            todo.append({"kind": "SOURCE_DOWN", "text": f"Nguồn {s['name']} không phản hồi", "action": "Xem", "route": "/admin/jobs"})
    health = "RED" if failed_jobs or any(s["status"] == "DOWN" for s in sources) else ("YELLOW" if users_pending or (p95 and p95 > 60000) else "GREEN")
    db_size = (await db.execute(text("SELECT pg_database_size(current_database())"))).scalar()
    return {"health": health, "kpis": {"users_active": users_active, "users_pending": users_pending, "active_7d": active_7d, "alerts_sent_24h": sent, "alerts_failed_24h": failed,
                                       "alert_latency_p95_ms": int(p95) if p95 else None, "signal_win_rate_20": round(float(win20), 1) if win20 is not None else None,
                                       "ai_cost_usd": round(ai_cost, 2), "ai_budget_usd": budget, "db_size_mb": round(db_size / 1e6, 1) if db_size else None},
            "eod_chain": steps, "todo": todo, "sources": sources, "last_eod": next((clean(j.started_at) for j in jobs if j.name == "eod.users" and j.status != "FAILED"), None)}


# ---------------------------------------------------------------- users
@router.get("/users")
async def users(admin: AdminUser, db: DB, status: str | None = None, q: str | None = None, page: int = 1, size: int = Query(50, le=200)):
    stmt = select(User)
    if status and status.upper() != "ALL":
        stmt = stmt.where(User.status == status.upper())
    if q:
        stmt = stmt.where((User.email.ilike(f"%{q}%")) | (User.full_name.ilike(f"%{q}%")))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (await db.execute(stmt.order_by(User.status == "PENDING", desc(User.created_at)).offset((page - 1) * size).limit(size))).scalars().all()
    out = []
    for u in rows:
        n_dev = await db.scalar(select(func.count(UserDevice.id)).where(UserDevice.user_id == u.id))
        out.append({**UserOut.model_validate(u).model_dump(), "devices": n_dev, "invited_by_code": u.invited_by_code, "max_devices": u.max_devices, "activated_at": clean(u.activated_at)})
    counts = {s: c for s, c in (await db.execute(select(User.status, func.count(User.id)).group_by(User.status))).all()}
    counts["ALL"] = sum(counts.values())
    return {"items": out, "total": total, "page": page, "size": size, "counts": counts}


@router.get("/users/{uid}")
async def user_detail(uid: uuid.UUID, admin: AdminUser, db: DB):
    u = await db.get(User, uid)
    if not u:
        raise not_found()
    devices = [row(d, ["id", "platform", "name", "last_seen_at", "created_at"]) for d in (await db.execute(select(UserDevice).where(UserDevice.user_id == u.id).order_by(desc(UserDevice.last_seen_at)))).scalars()]
    logins = [row(a, ["action", "ip", "created_at"]) for a in (await db.execute(select(AuditLog).where(AuditLog.actor_id == u.id, AuditLog.action.in_(["LOGIN", "REGISTER"])).order_by(desc(AuditLog.created_at)).limit(10))).scalars()]
    from app.models import AlertRule
    n_rules = await db.scalar(select(func.count(AlertRule.id)).where(AlertRule.user_id == u.id))
    s = await db.get(UserSettings, u.id)
    return {**UserOut.model_validate(u).model_dump(), "max_devices": u.max_devices, "invited_by_code": u.invited_by_code, "activated_at": clean(u.activated_at), "devices": devices, "logins": logins,
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


@router.post("/users/{uid}/activate")
async def activate(uid: uuid.UUID, body: ActivateIn, admin: AdminUser, db: DB, request: Request):
    u = await db.get(User, uid)
    if not u:
        raise not_found()
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
    await db.commit()
    return UserOut.model_validate(u)


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
        import secrets
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
async def kick_device(uid: uuid.UUID, did: uuid.UUID, admin: AdminUser, db: DB):
    d = await db.get(UserDevice, did)
    if d and d.user_id == uid:
        await db.delete(d)
        await db.commit()
    return Ok()


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
async def delete_invitation(code: str, admin: AdminUser, db: DB):
    inv = await db.get(Invitation, code)
    if inv:
        await db.delete(inv)
        await db.commit()
    return Ok()


# ---------------------------------------------------------------- config & strategies
@router.get("/config")
async def config(admin: AdminUser, db: DB):
    return await all_config(db)


@router.put("/config/{key}")
async def put_config(key: str, body: ConfigIn, admin: AdminUser, db: DB, request: Request):
    if key not in DEFAULTS:
        raise not_found("Khóa cấu hình không tồn tại")
    if key == "scoring.weights":
        for hz, w in body.value.items():
            if abs(sum(float(x) for x in w.values()) - 100) > 0.01:
                raise bad_request("WEIGHTS_SUM", f"Trọng số khung {hz} phải có tổng 100%")
    before = await get_config(db, key)
    await set_config(db, key, body.value, admin.email)
    await audit(db, admin, "CONFIG_SET", "config", key, before={"value": before}, after={"value": body.value}, request=request)
    await db.commit()
    return {"key": key, "value": body.value}


@router.post("/config/{key}/reset")
async def reset_config(key: str, admin: AdminUser, db: DB, request: Request):
    if key not in DEFAULTS:
        raise not_found()
    await set_config(db, key, DEFAULTS[key][0], admin.email)
    await audit(db, admin, "CONFIG_RESET", "config", key, request=request)
    await db.commit()
    return {"key": key, "value": DEFAULTS[key][0]}


@router.get("/strategies")
async def strategies(admin: AdminUser, db: DB):
    rows = (await db.execute(select(Strategy).order_by(Strategy.signal_type, Strategy.code))).scalars().all()
    return [row(s, ["code", "name", "signal_type", "horizon", "description", "params", "enabled", "version", "backtest_years", "win_rate", "avg_return", "max_drawdown", "trades", "updated_at"]) for s in rows]


@router.put("/strategies/{code}")
async def put_strategy(code: str, body: StrategyIn, admin: AdminUser, db: DB, request: Request):
    s = await db.get(Strategy, code)
    if not s:
        raise not_found()
    before = row(s, ["enabled", "params", "name"])
    if body.enabled is not None:
        if body.enabled and (s.backtest_years or 0) < 5:
            raise bad_request("BACKTEST_REQUIRED", "Chiến lược chỉ bật được khi đã có backtest ≥ 5 năm (BR-12)")
        s.enabled = body.enabled
    if body.params is not None:
        s.params = body.params
        s.version += 1
    if body.name:
        s.name = body.name
    await audit(db, admin, "STRATEGY_SET", "strategy", code, before=before, after=body.model_dump(exclude_unset=True), request=request)
    await db.commit()
    return row(s, ["code", "name", "signal_type", "horizon", "params", "enabled", "version", "win_rate", "avg_return", "trades"])


@router.get("/strategies/performance")
async def strategy_performance(admin: AdminUser, db: DB, months: int = 12, days: int = 20):
    since = today_vn() - timedelta(days=30 * months)
    rows = (await db.execute(text("""
        SELECT s.strategy_code, s.signal_type, s.horizon, s.regime_at_signal AS regime, count(*) n,
               avg(case when o.result in ('TP_HIT','WIN') then 1.0 else 0.0 end)*100 win_rate, avg(o.return_pct) avg_return
        FROM signals s JOIN signal_outcomes o ON o.signal_id=s.id AND o.days=:days WHERE s.trade_date >= :since
        GROUP BY 1,2,3,4 ORDER BY 1,4"""), {"days": days, "since": since})).all()
    by_rating = (await db.execute(text("""
        SELECT s.rating, count(*) n, avg(case when (s.signal_type in ('SELL','TAKE_PROFIT') and o.return_pct < 0) or (s.signal_type not in ('SELL','TAKE_PROFIT') and o.result in ('TP_HIT','WIN')) then 1.0 else 0.0 end)*100 win_rate,
               avg(o.return_pct) avg_return
        FROM signals s JOIN signal_outcomes o ON o.signal_id=s.id AND o.days=:days WHERE s.trade_date >= :since AND s.rating IS NOT NULL GROUP BY 1"""), {"days": days, "since": since})).all()
    by_sector = (await db.execute(text("""
        SELECT st.industry_code, count(*) n, avg(case when o.result in ('TP_HIT','WIN') then 1.0 else 0.0 end)*100 win_rate
        FROM signals s JOIN signal_outcomes o ON o.signal_id=s.id AND o.days=:days JOIN stocks st ON st.symbol=s.symbol
        WHERE s.trade_date >= :since AND s.signal_type='BUY' GROUP BY 1 ORDER BY 3 DESC"""), {"days": days, "since": since})).all()
    monthly = (await db.execute(text("""
        SELECT to_char(s.trade_date,'YYYY-MM') m, count(*) n, avg(case when o.result in ('TP_HIT','WIN') then 1.0 else 0.0 end)*100 win_rate, avg(o.return_pct) avg_return
        FROM signals s JOIN signal_outcomes o ON o.signal_id=s.id AND o.days=:days WHERE s.trade_date >= :since AND s.signal_type='BUY' GROUP BY 1 ORDER BY 1"""), {"days": days, "since": since})).all()
    idx = (await db.execute(text("SELECT close FROM index_daily WHERE index_code='VNINDEX' AND trade_date >= :since ORDER BY trade_date"), {"since": since})).scalars().all()
    idx_ret = (idx[-1] / idx[0] - 1) * 100 if len(idx) > 1 else None
    total_buy = sum(r.n for r in rows if r.signal_type == "BUY")
    tp_rate = (await db.execute(text("""SELECT avg(case when o.result='TP_HIT' then 1.0 else 0.0 end)*100, avg(o.return_pct) FROM signals s JOIN signal_outcomes o ON o.signal_id=s.id AND o.days=:days
                                        WHERE s.trade_date >= :since AND s.signal_type='BUY'"""), {"days": days, "since": since})).one()
    from app.ingestion.icb import ICB_LV2
    return {"months": months, "days": days, "kpis": {"buy_signals": total_buy, "tp1_rate": round(float(tp_rate[0]), 1) if tp_rate[0] is not None else None, "target_tp1_rate": 55,
                                                     "avg_return": round(float(tp_rate[1]), 2) if tp_rate[1] is not None else None, "vnindex_return": round(idx_ret, 2) if idx_ret is not None else None},
            "by_strategy_regime": [{"strategy": r.strategy_code, "signal_type": r.signal_type, "horizon": r.horizon, "regime": r.regime, "samples": int(r.n), "win_rate": round(float(r.win_rate), 1), "avg_return": round(float(r.avg_return), 2),
                                    "suggestion": "Tắt khi thị trường này" if r.n >= 30 and r.win_rate < 45 else ("Chưa đủ mẫu" if r.n < 30 else "Giữ nguyên")} for r in rows],
            "by_rating": [{"rating": r.rating, "samples": int(r.n), "win_rate": round(float(r.win_rate), 1), "avg_return": round(float(r.avg_return), 2)} for r in by_rating],
            "by_sector": [{"industry_code": r.industry_code, "name": ICB_LV2.get(r.industry_code, (r.industry_code,))[0], "samples": int(r.n), "win_rate": round(float(r.win_rate), 1)} for r in by_sector],
            "monthly": [{"month": r.m, "samples": int(r.n), "win_rate": round(float(r.win_rate), 1), "avg_return": round(float(r.avg_return), 2)} for r in monthly]}


# ---------------------------------------------------------------- jobs & data
@router.get("/jobs")
async def jobs(admin: AdminUser, db: DB, limit: int = 100):
    rows = await recent_jobs(db, limit)
    from app.tasks.scheduler import scheduled_jobs
    return {"runs": [row(j, ["id", "name", "status", "started_at", "finished_at", "duration_ms", "summary", "meta", "triggered_by"]) | {"error": (j.error or "")[-1500:] or None} for j in rows], "schedule": scheduled_jobs()}


@router.post("/jobs/{name}/run")
async def run_job_now(name: str, admin: AdminUser, db: DB, bg: BackgroundTasks, request: Request):
    from app.core.vntime import is_market_open
    from app.tasks.scheduler import run_named

    if is_market_open() and name.startswith("eod") and not request.query_params.get("confirm"):
        raise bad_request("CONFIRM_REQUIRED", "Đang trong giờ giao dịch. Thêm ?confirm=1 để chạy ngay.")
    await audit(db, admin, "JOB_RUN", "job", name, request=request)
    await db.commit()
    bg.add_task(run_named, name, f"admin:{admin.email}")
    return Ok(message=f"Đã xếp lịch chạy {name}")


@router.get("/data-sources")
async def data_sources(admin: AdminUser, db: DB):
    rows = (await db.execute(select(DataSource).order_by(DataSource.priority))).scalars().all()
    last_price = (await db.execute(text("SELECT max(trade_date), count(distinct symbol) FROM price_daily"))).one()
    quality = (await db.execute(text("""SELECT
        (SELECT count(*) FROM stocks WHERE is_active) active_stocks,
        (SELECT count(*) FROM stock_snapshots WHERE trade_date = (SELECT max(trade_date) FROM stock_snapshots)) snapshot_rows,
        (SELECT count(*) FROM price_daily p WHERE p.trade_date = (SELECT max(trade_date) FROM price_daily) AND (p.high < p.low OR p.close <= 0)) bad_candles,
        (SELECT count(*) FROM stocks s WHERE s.is_active AND NOT EXISTS (SELECT 1 FROM price_daily p WHERE p.symbol=s.symbol AND p.trade_date >= current_date - 10)) stale_symbols,
        (SELECT count(*) FROM stocks s WHERE s.is_active AND NOT EXISTS (SELECT 1 FROM financial_statements f WHERE f.symbol=s.symbol)) no_financials"""))).one()
    return {"sources": [row(s, ["code", "name", "role", "priority", "enabled", "status", "last_ok_at", "last_error", "latency_ms", "consecutive_failures"]) for s in rows],
            "coverage": {"last_price_date": clean(last_price[0]), "symbols_with_prices": last_price[1]},
            "quality": [{"check": "Mã đang niêm yết", "value": quality.active_stocks, "ok": True},
                        {"check": "Snapshot phiên gần nhất", "value": quality.snapshot_rows, "ok": quality.snapshot_rows > 0.9 * quality.active_stocks},
                        {"check": "Nến lỗi (high < low, close ≤ 0)", "value": quality.bad_candles, "ok": quality.bad_candles == 0},
                        {"check": "Mã không có giá 10 ngày", "value": quality.stale_symbols, "ok": quality.stale_symbols < 0.1 * quality.active_stocks},
                        {"check": "Mã thiếu BCTC", "value": quality.no_financials, "ok": quality.no_financials < 0.1 * quality.active_stocks}]}


@router.put("/data-sources/{code}")
async def put_source(code: str, admin: AdminUser, db: DB, enabled: bool | None = None, priority: int | None = None, role: str | None = None):
    s = await db.get(DataSource, code)
    if not s:
        raise not_found()
    if enabled is not None:
        s.enabled = enabled
    if priority is not None:
        s.priority = priority
    if role in ("PRIMARY", "BACKUP"):
        s.role = role
    await db.commit()
    return row(s, ["code", "name", "role", "priority", "enabled", "status"])


@router.post("/price-imports")
async def price_import_preview(admin: AdminUser, db: DB, file: UploadFile = File(...)):
    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        raise bad_request("FILE_TOO_BIG", "Tệp tối đa 20 MB")
    return await preview_file(db, raw, file.filename or "upload.csv")


@router.post("/price-imports/{import_id}/commit")
async def price_import_commit(import_id: str, admin: AdminUser, db: DB, bg: BackgroundTasks, request: Request, mode: str = "SKIP_EXISTING"):
    if mode not in ("SKIP_EXISTING", "OVERWRITE"):
        raise bad_request("MODE", "mode phải là SKIP_EXISTING hoặc OVERWRITE")
    res = await commit_import(db, import_id, mode, admin.email)
    await audit(db, admin, "PRICE_IMPORT", "price_import", import_id, after={"mode": mode, **{k: v for k, v in res.items() if k != "symbols"}}, request=request)
    await db.commit()
    from app.tasks.scheduler import run_named
    bg.add_task(run_named, "eod.recompute", f"admin:{admin.email}")
    return res


# ---------------------------------------------------------------- audit, broadcast, AI cost, risk stats
@router.get("/audit-logs")
async def audit_logs(admin: AdminUser, db: DB, action: str | None = None, actor: str | None = None, page: int = 1, size: int = Query(50, le=200)):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action.upper())
    if actor:
        stmt = stmt.where(AuditLog.actor_email.ilike(f"%{actor}%"))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (await db.execute(stmt.order_by(desc(AuditLog.id)).offset((page - 1) * size).limit(size))).scalars().all()
    actions = [a for (a,) in (await db.execute(select(AuditLog.action).distinct())).all()]
    return {"items": [row(a, ["id", "actor_email", "action", "target_type", "target_id", "before", "after", "ip", "created_at"]) for a in rows], "total": total, "page": page, "size": size, "actions": actions}


@router.get("/broadcasts")
async def broadcasts(admin: AdminUser, db: DB):
    rows = (await db.execute(select(Broadcast).order_by(desc(Broadcast.created_at)).limit(50))).scalars().all()
    return [{"id": str(b.id), **row(b, ["title", "body", "channels", "sent_count", "read_count", "created_at"])} for b in rows]


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
    cost = lambda i, o: round(i / 1e6 * 5 + o / 1e6 * 25, 3)  # noqa: E731
    limits = await get_config(db, "ai.limits")
    return {"limits": limits, "daily": [{"date": clean(r.d), "questions": r.questions, "input_tokens": int(r.inp), "output_tokens": int(r.outp), "cost_usd": cost(r.inp, r.outp)} for r in daily],
            "by_user": [{"email": r.email, "questions": r.questions, "cost_usd": cost(r.inp, r.outp)} for r in by_user], "model": settings.ai_model}


@router.get("/risk-stats")
async def risk_stats(admin: AdminUser, db: DB, days: int = 90):
    since = datetime.now(UTC) - timedelta(days=days)
    ev = (await db.execute(select(RiskGuardEvent.kind, func.count(RiskGuardEvent.id)).where(RiskGuardEvent.created_at >= since).group_by(RiskGuardEvent.kind))).all()
    checks = (await db.execute(select(PretradeCheck.result, func.count(PretradeCheck.id)).where(PretradeCheck.created_at >= since).group_by(PretradeCheck.result))).all()
    return {"days": days, "events": {k: c for k, c in ev}, "pretrade": {k: c for k, c in checks}, "defaults": await get_config(db, "risk.defaults"), "company_thresholds": await get_config(db, "risk.company_thresholds"), "chase": await get_config(db, "risk.chase")}


@router.get("/margin-lists")
async def margin_lists(admin: AdminUser, db: DB):
    return await get_config(db, "risk.margin_lists") or {}


@router.put("/margin-lists")
async def put_margin_lists(body: dict, admin: AdminUser, db: DB):
    """{"VCBS": ["FPT","HPG",...], "Pinetree": [...]}"""
    DEFAULTS.setdefault("risk.margin_lists", ({}, "Danh sách mã cho vay ký quỹ theo CTCK", "risk"))
    await set_config(db, "risk.margin_lists", {k: [s.upper() for s in v] for k, v in body.items()}, admin.email)
    await db.commit()
    return body


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


_ = (io, SignalOutcome, SignalReliability, Signal)

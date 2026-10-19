"""JobRun bookkeeping + a tiny in-process step tracker for the EOD chain (A01 'chuỗi xử lý cuối ngày')."""

import asyncio
import logging
import time
import traceback
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_scope
from app.models import JobRun

log = logging.getLogger(__name__)

# name → asyncio task of the job currently running in this process (A04 "Dừng"); one replica only.
RUNNING: dict[str, asyncio.Task] = {}

# Vietnamese labels + schedules for the job table (A04). EOD steps are labelled in tasks.eod.EOD_STEP_INFO.
JOB_INFO: dict[str, tuple[str, str, str]] = {  # name: (label, schedule, queue)
    "eod": ("Chuỗi xử lý cuối ngày", "15:05 ngày giao dịch", "compute"),
    "intraday": ("Quét trong phiên", "mỗi 5 phút, 09:00–15:00", "ingest"),
    "dispatch": ("Gửi cảnh báo chờ", "mỗi 1 phút", "notify"),
    "news_sync": ("Tin tức RSS + AI chấm cảm xúc", "mỗi 30 phút, 06:00–22:00", "ingest"),
    "fundamentals_sync": ("Cập nhật báo cáo tài chính", "18:00 ngày giao dịch", "ingest"),
    "maintenance": ("Hết hạn tài khoản, dọn token", "00:05 hằng ngày", "system"),
    "coach_weekly": ("Huấn luyện viên AI hằng tuần", "09:00 thứ Bảy", "ai"),
    "backup": ("Sao lưu cơ sở dữ liệu", "01:30 hằng ngày", "system"),
    "strategy_backtest": ("Backtest toàn bộ chiến lược", "02:00 Chủ nhật", "backtest"),
    "extras_backfill": ("Nạp lại sự kiện, dòng tiền lịch sử", "thủ công", "ingest"),
    "price_file_import": ("Nhập file giá", "thủ công", "ingest"),
}


def cancel_job(name: str) -> bool:
    t = RUNNING.get(name)
    if t is None or t.done():
        return False
    t.cancel()
    return True


async def run_job(name: str, fn: Callable[[AsyncSession], Awaitable[dict | None]], triggered_by: str = "scheduler") -> JobRun:
    """Runs fn inside its own session; records a JobRun row regardless of outcome."""
    async with session_scope() as db:
        job = JobRun(name=name, triggered_by=triggered_by)
        db.add(job)
        await db.flush()
        job_id = job.id
    t0 = time.monotonic()
    status, summary, meta, error = "DONE", None, None, None
    task = asyncio.current_task()
    if task is not None:
        RUNNING[name] = task
    try:
        async with session_scope() as db:
            res = await fn(db)
            if isinstance(res, dict):
                meta = res
                summary = res.get("summary") or ", ".join(f"{k}={v}" for k, v in list(res.items())[:6] if not isinstance(v, (dict, list)))
                if res.get("warn"):
                    status = "WARN"
    except asyncio.CancelledError:
        status, summary, error = "FAILED", "Đã dừng theo yêu cầu của quản trị viên", "cancelled"
        log.warning("job %s cancelled", name)
    except Exception as e:
        status, error = "FAILED", traceback.format_exc()[-4000:]
        summary = str(e)[:250]
        log.exception("job %s failed", name)
    finally:
        if RUNNING.get(name) is task:
            RUNNING.pop(name, None)
    async with session_scope() as db:
        job = await db.get(JobRun, job_id)
        job.status, job.summary, job.meta, job.error = status, summary, meta, error
        job.finished_at = datetime.now(UTC)
        job.duration_ms = int((time.monotonic() - t0) * 1000)
        return job


async def recent_jobs(db: AsyncSession, limit: int = 60) -> list[JobRun]:
    return list((await db.execute(select(JobRun).order_by(desc(JobRun.id)).limit(limit))).scalars())


async def _run(*cmd: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    return proc.returncode, (out + err).decode(errors="ignore")[-600:]


def _pg_urls() -> tuple[str, str, str]:
    """(live url, maintenance url on the `postgres` db, scratch url) — all plain postgresql:// for the CLI tools."""
    from urllib.parse import urlsplit, urlunsplit

    from app.core.config import settings

    u = urlsplit(settings.database_url.replace("postgresql+asyncpg://", "postgresql://"))
    scratch = "vinatrade_restore_test"
    return urlunsplit(u), urlunsplit(u._replace(path="/postgres")), urlunsplit(u._replace(path=f"/{scratch}"))


async def restore_test(path: str) -> dict:
    """A04 'lần khôi phục thử': restore the dump into a scratch database, compare row counts of key tables with the
    live database, then drop the scratch database. Needs CREATEDB on the Postgres user (Railway's default has it)."""
    import time as _t

    live, maint, scratch = _pg_urls()
    name = scratch.rsplit("/", 1)[1]
    t0 = _t.time()
    await _run("dropdb", "--if-exists", f"--maintenance-db={maint}", name)
    rc, msg = await _run("createdb", f"--maintenance-db={maint}", name)
    if rc != 0:
        return {"ok": False, "error": f"createdb: {msg}"}
    try:
        rc, msg = await _run("pg_restore", "--no-owner", "--no-acl", "-d", scratch, path)
        # pg_restore returns 1 on warnings (e.g. extension comments) while the data is complete; compare counts instead.
        counts = {}
        for table in ("users", "stocks", "price_daily", "signals", "stock_snapshots", "system_config"):
            a = await _run("psql", live, "-At", "-c", f"select count(*) from {table}")
            b = await _run("psql", scratch, "-At", "-c", f"select count(*) from {table}")
            counts[table] = (a[1].strip(), b[1].strip())
        mismatch = {k: v for k, v in counts.items() if v[0] != v[1]}
        return {"ok": not mismatch, "tables": {k: v[1] for k, v in counts.items()}, "mismatch": mismatch, "restore_rc": rc, "seconds": int(_t.time() - t0),
                "error": None if not mismatch else f"Số dòng lệch: {', '.join(f'{k} {v[0]}→{v[1]}' for k, v in mismatch.items())}"}
    finally:
        await _run("dropdb", "--if-exists", f"--maintenance-db={maint}", name)


async def backup_database(db: AsyncSession) -> dict:
    """Nightly pg_dump (custom format) into MEDIA_ROOT/backups, keeping the last 7, then a restore test into a scratch
    database. Reports WARN when pg_dump is missing (Railway Postgres also keeps its own snapshots)."""
    import os
    import shutil
    from datetime import datetime as _dt

    from app.core.config import settings

    if not shutil.which("pg_dump"):
        return {"warn": True, "summary": "pg_dump không có trên máy chủ, bỏ qua sao lưu", "files": 0}
    folder = os.path.join(settings.media_root, "backups")
    os.makedirs(folder, exist_ok=True)
    live, _, _ = _pg_urls()
    path = os.path.join(folder, f"vinatrade-{_dt.now().strftime('%Y%m%d-%H%M')}.dump")
    rc, err = await _run("pg_dump", "-Fc", "--no-owner", "--no-acl", "-d", live, "-f", path)
    if rc != 0:
        raise RuntimeError(err or f"pg_dump exit {rc}")
    files = sorted(f for f in os.listdir(folder) if f.endswith(".dump"))
    for old in files[:-7]:
        os.remove(os.path.join(folder, old))
    size = os.path.getsize(path)
    rt = await restore_test(path) if shutil.which("pg_restore") else {"ok": None, "error": "pg_restore không có trên máy chủ"}
    restored = "khôi phục thử đạt" if rt.get("ok") else ("khôi phục thử LỖI" if rt.get("ok") is False else "chưa khôi phục thử")
    return {"file": os.path.basename(path), "size_mb": round(size / 1e6, 1), "kept": min(len(files), 7), "restore_test": rt, "warn": rt.get("ok") is False,
            "summary": f"{os.path.basename(path)} · {size / 1e6:.1f} MB · {restored}"}

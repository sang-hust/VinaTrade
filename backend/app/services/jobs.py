"""JobRun bookkeeping + a tiny in-process step tracker for the EOD chain (A01 'chuỗi xử lý cuối ngày')."""

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


async def run_job(name: str, fn: Callable[[AsyncSession], Awaitable[dict | None]], triggered_by: str = "scheduler") -> JobRun:
    """Runs fn inside its own session; records a JobRun row regardless of outcome."""
    async with session_scope() as db:
        job = JobRun(name=name, triggered_by=triggered_by)
        db.add(job)
        await db.flush()
        job_id = job.id
    t0 = time.monotonic()
    status, summary, meta, error = "DONE", None, None, None
    try:
        async with session_scope() as db:
            res = await fn(db)
            if isinstance(res, dict):
                meta = res
                summary = res.get("summary") or ", ".join(f"{k}={v}" for k, v in list(res.items())[:6] if not isinstance(v, (dict, list)))
                if res.get("warn"):
                    status = "WARN"
    except Exception as e:  # noqa: BLE001
        status, error = "FAILED", traceback.format_exc()[-4000:]
        summary = str(e)[:250]
        log.exception("job %s failed", name)
    async with session_scope() as db:
        job = await db.get(JobRun, job_id)
        job.status, job.summary, job.meta, job.error = status, summary, meta, error
        job.finished_at = datetime.now(UTC)
        job.duration_ms = int((time.monotonic() - t0) * 1000)
        return job


async def recent_jobs(db: AsyncSession, limit: int = 60) -> list[JobRun]:
    return list((await db.execute(select(JobRun).order_by(desc(JobRun.id)).limit(limit))).scalars())


async def last_job(db: AsyncSession, name: str) -> JobRun | None:
    return (await db.execute(select(JobRun).where(JobRun.name == name).order_by(desc(JobRun.id)).limit(1))).scalar_one_or_none()

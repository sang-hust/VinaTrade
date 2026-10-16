"""APScheduler inside the API process (spec 4.5 reduced to what the EOD-first MVP needs). One replica only."""

import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, update

from app.core.config import settings
from app.core.db import session_scope
from app.core.vntime import VN_TZ, is_market_open, is_trading_day, today_vn
from app.models import ActionItem, RefreshToken, User
from app.services.jobs import run_job

log = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone=VN_TZ)


async def _eod():
    if not is_trading_day(today_vn()):
        return
    from app.tasks.eod import run_eod

    await run_eod("scheduler")


async def _dispatch(db):
    from app.services.notify import dispatch_pending

    return await dispatch_pending(db)


async def _maintenance(db):
    now = datetime.now(UTC)
    exp = await db.execute(update(User).where(User.status == "ACTIVE", User.expires_at.isnot(None), User.expires_at < now).values(status="EXPIRED"))
    tok = await db.execute(RefreshToken.__table__.delete().where(RefreshToken.expires_at < now))
    items = await db.execute(update(ActionItem).where(ActionItem.status == "OPEN", ActionItem.expires_at.isnot(None), ActionItem.expires_at < now).values(status="EXPIRED"))
    return {"expired_users": exp.rowcount, "tokens_deleted": tok.rowcount, "items_expired": items.rowcount}


async def _weekly_coach(db):
    from app.services.coach import weekly_reports

    return {"reports": await weekly_reports(db)}


async def _intraday(db):
    """Light intraday pass: refresh quotes for followed symbols, evaluate URGENT portfolio rules (stop broken), plans."""
    if not is_market_open():
        return {"skipped": "market closed"}
    from app.tasks.intraday import intraday_pass

    return await intraday_pass(db)


async def _news(db):
    from app.ingestion.extras import enrich_snapshots, sync_news

    r = await sync_news(db)
    if r.get("new"):
        await enrich_snapshots(db)
    return r


async def run_named(name: str, triggered_by: str = "admin"):
    if name == "eod" or name == "eod.all":
        from app.tasks.eod import run_eod

        return await run_eod(triggered_by)
    if name == "eod.recompute":
        from app.tasks.eod import run_eod

        return await run_eod(triggered_by, skip_ingest=True)
    if name.startswith("eod."):
        from app.tasks.alerts import step_users
        from app.tasks.eod import EOD_STEPS

        fn = dict(EOD_STEPS).get(name) or (step_users if name == "eod.users" else None)
        if fn is None:
            raise ValueError(f"unknown step {name}")
        return await run_job(name, fn, triggered_by)
    if name == "dispatch":
        return await run_job("dispatch", _dispatch, triggered_by)
    if name == "maintenance":
        return await run_job("maintenance", _maintenance, triggered_by)
    if name == "coach_weekly":
        return await run_job("coach_weekly", _weekly_coach, triggered_by)
    if name == "intraday":
        return await run_job("intraday", _intraday, triggered_by)
    if name == "news_sync":
        return await run_job("news_sync", _news, triggered_by)
    if name == "extras_backfill":
        from app.ingestion.extras import backfill_extras

        return await run_job("extras_backfill", lambda db: backfill_extras(db), triggered_by)
    if name == "fundamentals_sync":
        from app.ingestion.fundamentals import sync_fundamentals

        return await run_job("fundamentals_sync", lambda db: sync_fundamentals(db), triggered_by)
    raise ValueError(f"unknown job {name}")


def start():
    if not settings.scheduler_enabled or scheduler.running:
        return
    scheduler.add_job(_eod, CronTrigger(day_of_week="mon-fri", hour=15, minute=5), id="eod", name="Chuỗi xử lý cuối ngày", replace_existing=True, misfire_grace_time=3600)
    scheduler.add_job(lambda: run_job("dispatch", _dispatch), IntervalTrigger(minutes=1), id="dispatch", name="Gửi cảnh báo chờ", replace_existing=True)
    scheduler.add_job(lambda: run_job("intraday", _intraday), IntervalTrigger(minutes=5), id="intraday", name="Quét trong phiên (5 phút)", replace_existing=True)
    scheduler.add_job(lambda: run_job("maintenance", _maintenance), CronTrigger(hour=0, minute=5), id="maintenance", name="Hết hạn tài khoản, dọn token", replace_existing=True)
    scheduler.add_job(lambda: run_job("coach_weekly", _weekly_coach), CronTrigger(day_of_week="sat", hour=9, minute=0), id="coach_weekly", name="Huấn luyện viên AI hằng tuần", replace_existing=True)
    scheduler.add_job(lambda: run_named("fundamentals_sync", "scheduler"), CronTrigger(day_of_week="mon-fri", hour=18, minute=0), id="fundamentals_sync", name="Cập nhật BCTC", replace_existing=True, misfire_grace_time=3600)
    scheduler.add_job(lambda: run_job("news_sync", _news), CronTrigger(hour="6-22", minute="5,35"), id="news_sync", name="Lấy tin tức RSS + AI chấm cảm xúc (30 phút)", replace_existing=True)
    scheduler.start()
    log.info("scheduler started")


def scheduled_jobs() -> list[dict]:
    if not scheduler.running:
        return []
    return [{"id": j.id, "name": j.name, "next_run": j.next_run_time.isoformat() if j.next_run_time else None, "trigger": str(j.trigger)} for j in scheduler.get_jobs()]


_ = (select, session_scope)

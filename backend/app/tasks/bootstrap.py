"""First-boot data load: if price_daily is empty → universe, 6y prices, indexes, fundamentals, full EOD, backfill.
Safe to run every start (does nothing when data exists). python -m app.tasks.bootstrap"""

import asyncio
import logging

from sqlalchemy import func, select

from app.core.db import session_scope
from app.models import PriceDaily, StockSnapshot

log = logging.getLogger("bootstrap")


async def main():
    async with session_scope() as db:
        n_prices = await db.scalar(select(func.count()).select_from(PriceDaily))
        n_snap = await db.scalar(select(func.count()).select_from(StockSnapshot))
    if n_prices and n_snap:
        log.info("data present (%s price rows), nothing to do", n_prices)
        return
    from app.ingestion.fundamentals import sync_fundamentals
    from app.ingestion.prices import sync_indexes, sync_prices
    from app.ingestion.universe import sync_universe
    from app.services.jobs import run_job
    from app.tasks.backfill import backfill
    from app.tasks.eod import run_eod, step_indicators

    if not n_prices:
        await run_job("bootstrap.universe", lambda db: sync_universe(db), "bootstrap")
        await run_job("bootstrap.indexes", lambda db: sync_indexes(db, full=True), "bootstrap")
        await run_job("bootstrap.prices", lambda db: sync_prices(db, full=True, concurrency=10), "bootstrap")
        await run_job("bootstrap.fundamentals", lambda db: sync_fundamentals(db, concurrency=8), "bootstrap")
    await run_job("eod.indicators", lambda db: step_indicators(db, full=True), "bootstrap")
    await run_eod("bootstrap", skip_ingest=True, only=[n for n in ("eod.bases", "eod.rs_beta", "eod.ratios", "eod.regime", "eod.sectors", "eod.company_risk", "eod.scores", "eod.signals", "eod.snapshot", "eod.outcomes", "eod.presets", "eod.explain", "eod.users")])
    await run_job("backfill", lambda db: backfill(db, years=4), "bootstrap")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())

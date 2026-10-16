"""Daily price + index history loading with SSI primary / VCI backup, incremental by last stored date."""

import asyncio
import logging
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vntime import last_closed_trading_day
from app.ingestion.adapters.base import Candle
from app.ingestion.adapters.ssi import SSIAdapter
from app.ingestion.adapters.vci import VCIAdapter
from app.ingestion.universe import mark_source
from app.models import IndexDaily, PriceDaily, Stock

log = logging.getLogger(__name__)
INDEXES = ["VNINDEX", "VN30", "HNXINDEX", "UPCOMINDEX"]
HISTORY_YEARS = 6


async def _last_dates(db: AsyncSession) -> dict[str, date]:
    rows = await db.execute(select(PriceDaily.symbol, func.max(PriceDaily.trade_date)).group_by(PriceDaily.symbol))
    return {s: d for s, d in rows.all()}


async def upsert_candles(db: AsyncSession, symbol: str, candles: list[Candle], source: str, overwrite: bool = True) -> int:
    if not candles:
        return 0
    by_date = {}
    for c in candles:
        if c.close and c.close > 0:
            by_date[c.trade_date] = c  # last wins → dedupe duplicate timestamps from the source
    rows = [
        dict(symbol=symbol, trade_date=c.trade_date, open=c.open, high=c.high, low=c.low, close=c.close,
             volume=c.volume, value=c.value if c.value is not None else c.close * c.volume, source=source)
        for c in by_date.values()
    ]
    if not rows:
        return 0
    stmt = insert(PriceDaily).values(rows)
    if overwrite:
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "trade_date"],
            set_={k: getattr(stmt.excluded, k) for k in ("open", "high", "low", "close", "volume", "value", "source")},
        )
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=["symbol", "trade_date"])
    await db.execute(stmt)
    return len(rows)


async def fetch_history(symbol: str, start: date, end: date, ssi: SSIAdapter, vci: VCIAdapter) -> tuple[list[Candle], str]:
    try:
        c = await ssi.daily_history(symbol, start, end)
        if c:
            return c, "SSI"
    except Exception as e:  # noqa: BLE001
        log.warning("SSI history %s failed: %s", symbol, e)
    try:
        return await vci.daily_history(symbol, start, end), "VCI"
    except Exception as e:  # noqa: BLE001
        log.warning("VCI history %s failed: %s", symbol, e)
        return [], "NONE"


async def sync_prices(db: AsyncSession, symbols: list[str] | None = None, full: bool = False,
                      concurrency: int = 8, progress=None) -> dict:
    end = last_closed_trading_day()
    if symbols is None:
        symbols = [s for (s,) in (await db.execute(select(Stock.symbol).where(Stock.is_active))).all()]
    last = await _last_dates(db)
    ssi, vci = SSIAdapter(timeout=40), VCIAdapter(timeout=40)
    sem = asyncio.Semaphore(concurrency)
    stats = {"symbols": len(symbols), "rows": 0, "failed": 0, "ssi": 0, "vci": 0}

    async def one(sym: str):
        start = date(end.year - HISTORY_YEARS, 1, 1) if full or sym not in last else last[sym] - timedelta(days=3)
        if start > end:
            return
        async with sem:
            candles, src = await fetch_history(sym, start, end, ssi, vci)
        if src == "NONE":
            stats["failed"] += 1
            return
        stats[src.lower()] += 1
        return sym, candles, src

    results = []
    for i in range(0, len(symbols), 50):
        batch = symbols[i : i + 50]
        results = await asyncio.gather(*(one(s) for s in batch), return_exceptions=True)
        for r in results:
            if isinstance(r, Exception) or r is None:
                if isinstance(r, Exception):
                    stats["failed"] += 1
                continue
            sym, candles, src = r
            stats["rows"] += await upsert_candles(db, sym, candles, src)
        await db.flush()
        if progress:
            await progress(min(i + 50, len(symbols)), len(symbols))
    await mark_source(db, "SSI", stats["ssi"] > 0 or stats["symbols"] == 0)
    await mark_source(db, "VCI", stats["vci"] > 0 or stats["ssi"] > 0)
    await ssi.close()
    await vci.close()
    return stats


async def sync_indexes(db: AsyncSession, full: bool = False) -> dict:
    end = last_closed_trading_day()
    ssi, vci = SSIAdapter(timeout=40), VCIAdapter(timeout=40)
    n = 0
    try:
        for code in INDEXES:
            lastd = (await db.execute(select(func.max(IndexDaily.trade_date)).where(IndexDaily.index_code == code))).scalar()
            start = date(end.year - HISTORY_YEARS, 1, 1) if full or not lastd else lastd - timedelta(days=3)
            candles: list[Candle] = []
            try:
                candles = await ssi.index_history(code, start, end)
            except Exception as e:  # noqa: BLE001
                log.warning("SSI index %s failed: %s", code, e)
            if not candles:
                try:
                    candles = await vci.index_history(code, start, end)
                except Exception as e:  # noqa: BLE001
                    log.warning("VCI index %s failed: %s", code, e)
            if not candles:
                continue
            dedup = {c.trade_date: c for c in candles if c.close}
            rows = [dict(index_code=code, trade_date=c.trade_date, open=c.open, high=c.high, low=c.low, close=c.close,
                         volume=c.volume, value=c.value) for c in dedup.values()]
            stmt = insert(IndexDaily).values(rows)
            stmt = stmt.on_conflict_do_update(index_elements=["index_code", "trade_date"],
                                              set_={k: getattr(stmt.excluded, k) for k in ("open", "high", "low", "close", "volume", "value")})
            await db.execute(stmt)
            n += len(rows)
    finally:
        await ssi.close()
        await vci.close()
    return {"rows": n}

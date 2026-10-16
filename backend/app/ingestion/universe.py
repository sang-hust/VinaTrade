"""Sync the stock universe (symbols, exchange, ICB industry, VN30 membership) from VCI + SSI."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.adapters.ssi import SSIAdapter
from app.ingestion.adapters.vci import VCIAdapter
from app.ingestion.icb import ICB_LV2
from app.models import DataSource, Industry, Stock

log = logging.getLogger(__name__)


async def mark_source(db: AsyncSession, code: str, ok: bool, error: str | None = None, latency_ms: int | None = None):
    src = await db.get(DataSource, code)
    if not src:
        src = DataSource(code=code, name=code, role="PRIMARY" if code == "SSI" else "BACKUP", priority=1 if code == "SSI" else 2)
        db.add(src)
    if ok:
        src.status, src.last_ok_at, src.consecutive_failures, src.last_error = "OK", datetime.now(UTC), 0, None
    else:
        src.consecutive_failures += 1
        src.status = "DOWN" if src.consecutive_failures >= 3 else "DEGRADED"
        src.last_error = (error or "")[:255]
    if latency_ms is not None:
        src.latency_ms = latency_ms


async def sync_industries(db: AsyncSession) -> None:
    for code, (vi, en) in ICB_LV2.items():
        await db.execute(
            insert(Industry)
            .values(code=code, name_vi=vi, name_en=en, level=2)
            .on_conflict_do_update(index_elements=["code"], set_={"name_vi": vi, "name_en": en})
        )


async def sync_universe(db: AsyncSession, limit: int = 0) -> dict:
    vci, ssi = VCIAdapter(), SSIAdapter()
    try:
        await sync_industries(db)
        t0 = datetime.now(UTC)
        vci_rows = await vci.list_stocks()
        await mark_source(db, "VCI", True, latency_ms=int((datetime.now(UTC) - t0).total_seconds() * 1000))
        t0 = datetime.now(UTC)
        ssi_rows = await ssi.list_stocks()
        vn30 = set(await ssi.group("VN30"))
        await mark_source(db, "SSI", True, latency_ms=int((datetime.now(UTC) - t0).total_seconds() * 1000))
    except Exception as e:  # noqa: BLE001
        log.exception("universe sync failed")
        await mark_source(db, "SSI", False, str(e))
        raise
    finally:
        await vci.close()
        await ssi.close()

    by_symbol = {s.symbol: s for s in vci_rows}
    ssi_by = {s.symbol: s for s in ssi_rows}
    # SSI is authoritative for "listed & tradable"; VCI adds names/industry.
    symbols = [s for s in ssi_by if s in by_symbol] + [s for s in by_symbol if s not in ssi_by]
    if limit:
        # dev: keep VN30 + most liquid-looking first (alphabetical fallback)
        symbols = sorted(symbols, key=lambda s: (s not in vn30, s))[:limit]

    existing = {s.symbol: s for s in (await db.execute(select(Stock))).scalars()}
    n_new = 0
    for sym in symbols:
        v, s = by_symbol.get(sym), ssi_by.get(sym)
        exchange = (s.exchange if s else v.exchange) if (s or v) else "UPCOM"
        icb2 = v.icb_lv2 if v else None
        vals = dict(
            symbol=sym,
            exchange=exchange,
            name_vi=(v.name_vi if v else s.name_vi) or sym,
            name_en=(v.name_en if v else s.name_en),
            short_name=(v.short_name if v else None),
            industry_code=icb2 if icb2 in ICB_LV2 else None,
            listed_shares=s.listed_shares if s else None,
            in_vn30=sym in vn30,
            status_flags=(s.status_flags if s else None) or [],
            is_active=True,
        )
        if sym in existing:
            st = existing[sym]
            for k, val in vals.items():
                setattr(st, k, val)
        else:
            db.add(Stock(**vals))
            n_new += 1
    # Symbols no longer listed → inactive
    keep = set(symbols)
    n_off = 0
    for sym, st in existing.items():
        if sym not in keep and st.is_active:
            st.is_active = False
            n_off += 1
    await db.flush()
    return {"total": len(symbols), "new": n_new, "deactivated": n_off, "vn30": len(vn30)}

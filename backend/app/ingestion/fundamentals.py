"""Financial statements (Vietcap) → financial_statements; company profile → stocks extra fields."""

import asyncio
import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.adapters.vci import VCIAdapter
from app.models import FinancialStatement, Stock

log = logging.getLogger(__name__)
STATEMENT_COLS = ["revenue", "gross_profit", "operating_profit", "pretax_profit", "net_profit", "eps", "total_assets",
                  "total_liabilities", "current_liabilities", "current_assets", "equity", "short_debt", "long_debt", "cash",
                  "receivables", "inventory", "cfo", "capex", "dividends_paid"]


def _d(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:10]).date()
    except ValueError:
        return None


async def sync_fundamentals(db: AsyncSession, symbols: list[str] | None = None, concurrency: int = 6, progress=None) -> dict:
    if symbols is None:
        symbols = [s for (s,) in (await db.execute(select(Stock.symbol).where(Stock.is_active))).all()]
    vci = VCIAdapter(timeout=40)
    sem = asyncio.Semaphore(concurrency)
    stats = {"symbols": len(symbols), "rows": 0, "failed": 0}

    async def one(sym: str):
        async with sem:
            try:
                st = await vci.statements(sym)
                co = await vci.company(sym)
                return sym, st, co
            except Exception as e:  # noqa: BLE001
                log.warning("fundamentals %s failed: %s", sym, e)
                return sym, None, None

    try:
        for i in range(0, len(symbols), 30):
            batch = symbols[i : i + 30]
            for r in await asyncio.gather(*(one(s) for s in batch)):
                sym, st, co = r
                if st is None:
                    stats["failed"] += 1
                    continue
                rows = []
                for (y, q), rec in st.items():
                    if y < 2015:
                        continue
                    row = {c: rec.get(c) for c in STATEMENT_COLS}
                    rows.append(dict(symbol=sym, year=y, quarter=q, public_date=_d(rec.get("public_date")), source="VCI", **row))
                if rows:
                    cols = STATEMENT_COLS + ["public_date", "source"]
                    stmt = insert(FinancialStatement).values(rows)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["symbol", "year", "quarter"],
                        set_={c: getattr(stmt.excluded, c) for c in cols},
                    )
                    await db.execute(stmt)
                    stats["rows"] += len(rows)
                if co:
                    stock = await db.get(Stock, sym)
                    if stock:
                        stock.icb_lv4 = str(co.get("icbCodeLv4")) if co.get("icbCodeLv4") else stock.icb_lv4
                        if co.get("icbCodeLv2") and not stock.industry_code:
                            stock.industry_code = str(co["icbCodeLv2"])
                        stock.free_float_pct = _pct(co.get("freeFloatPercentage"))
                        stock.foreign_pct = _pct(co.get("foreignerPercentage"))
                        stock.state_pct = _pct(co.get("statePercentage"))
                        stock.is_bank = bool(co.get("isBank") or co.get("bank"))
                        stock.listing_date = _d(co.get("listingDate"))
                        if co.get("issueShare"):
                            stock.listed_shares = int(float(co["issueShare"]))
                        stock.profile_vi = _strip_html(co.get("profile"))[:4000] if co.get("profile") else stock.profile_vi
                        stock.source_meta = {
                            "vci_rating": co.get("rating"),
                            "vci_target": co.get("targetPrice"),
                            "vci_rating_as_of": co.get("ratingAsOf"),
                            "avg_value_1m": co.get("averageMatchValue1Month"),
                            "high_1y": co.get("highestPrice1Year"),
                            "low_1y": co.get("lowestPrice1Year"),
                            "dps": co.get("dividendPerShareTsr"),
                        }
            await db.flush()
            if progress:
                await progress(min(i + 30, len(symbols)), len(symbols))
    finally:
        await vci.close()
    return stats


def _pct(v) -> float | None:
    try:
        return round(float(v) * 100, 2) if v is not None else None
    except (TypeError, ValueError):
        return None


def _strip_html(s: str) -> str:
    import re

    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()

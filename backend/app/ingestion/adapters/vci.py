"""Vietcap (VCI) public endpoints: symbol list with ICB codes, adjusted OHLCV chart, company profile, financial statements."""

from datetime import UTC, date, datetime, timedelta

from app.ingestion.adapters.base import Candle, DataAdapter, StockInfo

BASE = "https://trading.vietcap.com.vn/api"
BOARD = {"HSX": "HOSE", "HOSE": "HOSE", "HNX": "HNX", "UPCOM": "UPCOM"}

# Vietcap statement field codes → our FinancialStatement columns
INCOME = {
    "revenue": "isa3",
    "gross_profit": "isa5",
    "operating_profit": "isa11",
    "pretax_profit": "isa16",
    "net_profit": "isa22",
    "eps": "isa23",
}
BALANCE = {
    "total_assets": "bsa53",
    "total_liabilities": "bsa54",
    "current_liabilities": "bsa55",
    "current_assets": "bsa1",
    "equity": "bsa78",
    "short_debt": "bsa56",
    "long_debt": "bsa71",
    "cash": "bsa2",
    "receivables": "bsa9",
    "inventory": "bsa15",
}
CASHFLOW = {"cfo": "cfa18", "capex": "cfa19", "dividends_paid": "cfa32"}


class VCIAdapter(DataAdapter):
    code = "VCI"

    async def list_stocks(self) -> list[StockInfo]:
        r = await self.client.get(f"{BASE}/price/symbols/getAll")
        r.raise_for_status()
        out = []
        for row in r.json() or []:
            if row.get("type") != "STOCK":
                continue
            sym = (row.get("symbol") or "").upper()
            if not sym:
                continue
            out.append(
                StockInfo(
                    symbol=sym,
                    exchange=BOARD.get((row.get("board") or "").upper(), "UPCOM"),
                    name_vi=row.get("organName") or sym,
                    name_en=row.get("enOrganName"),
                    short_name=row.get("organShortName"),
                    icb_lv2=str(row["icbCode2"]) if row.get("icbCode2") else None,
                )
            )
        return out

    async def chart(self, symbol: str, start: date, end: date, timeframe: str = "ONE_DAY") -> list[Candle]:
        to = int(datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=UTC).timestamp())
        count_back = max(10, (end - start).days * 5 // 7 + 10)
        r = await self.client.post(
            f"{BASE}/chart/OHLCChart/gap-chart",
            json={"timeFrame": timeframe, "symbols": [symbol], "to": to, "countBack": count_back},
        )
        r.raise_for_status()
        rows = r.json() or []
        if not rows:
            return []
        d = rows[0]
        out = []
        vals = d.get("accumulatedValue") or [None] * len(d["t"])
        for t, o, h, lo, c, v, val in zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"], vals, strict=False):
            td = datetime.fromtimestamp(int(t), tz=UTC).date()
            if td < start or td > end:
                continue
            out.append(Candle(td, float(o), float(h), float(lo), float(c), int(v or 0), float(val) * 1e6 if val else None))
        return out

    async def daily_history(self, symbol: str, start: date, end: date) -> list[Candle]:
        return await self.chart(symbol, start, end)

    async def index_history(self, index_code: str, start: date, end: date) -> list[Candle]:
        code = {"HNXINDEX": "HNXIndex", "UPCOMINDEX": "HNXUpcomIndex"}.get(index_code, index_code)
        return await self.chart(code, start, end)

    async def company(self, symbol: str) -> dict:
        r = await self.client.get(f"{BASE}/iq-insight-service/v1/company/{symbol}")
        if r.status_code != 200:
            return {}
        return (r.json() or {}).get("data") or {}

    async def statements(self, symbol: str) -> dict[tuple[int, int], dict]:
        """Returns {(year, quarter): {col: value, ...}} merging income, balance sheet, cash flow (quarterly + yearly)."""
        merged: dict[tuple[int, int], dict] = {}
        for section, mapping in (("INCOME_STATEMENT", INCOME), ("BALANCE_SHEET", BALANCE), ("CASH_FLOW", CASHFLOW)):
            r = await self.client.get(
                f"{BASE}/iq-insight-service/v1/company/{symbol}/financial-statement",
                params={"section": section, "period": "Q"},
            )
            if r.status_code != 200:
                continue
            data = (r.json() or {}).get("data") or {}
            for bucket in ("quarters", "years"):
                for row in data.get(bucket) or []:
                    y, q = row.get("yearReport"), row.get("lengthReport")
                    if not y or q is None:
                        continue
                    rec = merged.setdefault((int(y), int(q)), {})
                    for col, code in mapping.items():
                        if row.get(code) is not None:
                            rec[col] = float(row[code])
                    pd_ = row.get("publicDate")
                    if pd_ and "public_date" not in rec:
                        rec["public_date"] = pd_[:10]
        return merged

"""SSI iBoard public endpoints: stock lists per exchange, reference/ceiling/floor, daily history (prices in thousand VND)."""

from datetime import UTC, date, datetime, timedelta

from app.ingestion.adapters.base import Candle, DataAdapter, Quote, StockInfo

QUERY = "https://iboard-query.ssi.com.vn"
API = "https://iboard-api.ssi.com.vn"

EXCHANGES = {"hose": "HOSE", "hnx": "HNX", "upcom": "UPCOM"}
INDEX_SYMBOLS = {"VNINDEX": "VNINDEX", "VN30": "VN30", "HNXINDEX": "HNXINDEX", "UPCOMINDEX": "UPCOMINDEX"}  # UPCOMINDEX empty on SSI → VCI fallback
INDEX_UPPER = {v.upper() for v in INDEX_SYMBOLS.values()} | set(INDEX_SYMBOLS)


def _flags(row: dict) -> list[str]:
    flags = []
    st = (row.get("adminStatus") or "").upper()
    # SSI codes: NRM normal, WRN warning, CTR control, SUS suspended, RST restricted
    if st in ("WRN", "WARNING"):
        flags.append("WARNING")
    elif st in ("CTR", "CONTROL"):
        flags.append("CONTROL")
    elif st in ("SUS", "SUSPENDED"):
        flags.append("SUSPENDED")
    elif st in ("RST", "RESTRICTED"):
        flags.append("RESTRICTED")
    return flags


class SSIAdapter(DataAdapter):
    code = "SSI"

    async def _exchange_rows(self, ex: str) -> list[dict]:
        r = await self.client.get(f"{QUERY}/stock/exchange/{ex}")
        r.raise_for_status()
        return r.json().get("data") or []

    async def list_stocks(self) -> list[StockInfo]:
        out: list[StockInfo] = []
        for ex, code in EXCHANGES.items():
            for row in await self._exchange_rows(ex):
                sym = (row.get("stockSymbol") or row.get("symbol") or "").upper()
                if not sym or row.get("market") not in (None, "STO", "UPX", "HNX") and row.get("securityType") not in (None, "ST"):
                    continue
                if len(sym) != 3 and not sym.isalpha():
                    continue  # skip CW, ETF, bonds (CW symbols like CFPT2301 are longer)
                out.append(
                    StockInfo(
                        symbol=sym,
                        exchange=code,
                        name_vi=row.get("companyNameVi") or sym,
                        name_en=row.get("companyNameEn"),
                        listed_shares=row.get("listedShare"),
                        ref_price=row.get("refPrice") or row.get("priorClosePrice"),
                        ceiling=row.get("ceiling"),
                        floor=row.get("floor"),
                        status_flags=_flags(row),
                    )
                )
        return out

    async def group(self, name: str = "VN30") -> list[str]:
        r = await self.client.get(f"{QUERY}/stock/group/{name}")
        r.raise_for_status()
        return [(x.get("stockSymbol") or x.get("symbol") or "").upper() for x in r.json().get("data") or []]

    async def stock_info(self, symbol: str) -> dict:
        r = await self.client.get(f"{QUERY}/stock/{symbol}")
        r.raise_for_status()
        return r.json().get("data") or {}

    async def _history(self, symbol: str, start: date, end: date) -> list[Candle]:
        frm = int(datetime.combine(start, datetime.min.time(), tzinfo=UTC).timestamp())
        to = int(datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=UTC).timestamp())
        r = await self.client.get(
            f"{API}/statistics/charts/history",
            params={"resolution": "1D", "symbol": symbol, "from": frm, "to": to},
        )
        r.raise_for_status()
        d = (r.json() or {}).get("data") or {}
        if d.get("s") != "ok" or not d.get("t"):
            return []
        out = []
        for t, o, h, lo, c, v in zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"], strict=False):
            td = datetime.fromtimestamp(int(t), tz=UTC).date()
            if td > end:
                continue
            mult = 1.0 if symbol.upper() in INDEX_UPPER else 1000.0
            out.append(Candle(td, float(o) * mult, float(h) * mult, float(lo) * mult, float(c) * mult, int(v or 0)))
        return out

    async def daily_history(self, symbol: str, start: date, end: date) -> list[Candle]:
        return await self._history(symbol, start, end)

    async def index_history(self, index_code: str, start: date, end: date) -> list[Candle]:
        return await self._history(INDEX_SYMBOLS.get(index_code, index_code), start, end)

    async def quotes(self, symbols: list[str]) -> list[Quote]:
        """Reference/ceiling/floor from the exchange lists (SSI exposes no cheap batch last-price endpoint)."""
        wanted = set(s.upper() for s in symbols)
        out = []
        for ex in EXCHANGES:
            for row in await self._exchange_rows(ex):
                sym = (row.get("stockSymbol") or row.get("symbol") or "").upper()
                if sym not in wanted:
                    continue
                ref = row.get("refPrice") or row.get("priorClosePrice")
                last = row.get("matchedPrice") or row.get("lastPrice") or row.get("closePrice") or ref
                out.append(
                    Quote(
                        symbol=sym,
                        price=float(last or 0),
                        ref_price=float(ref) if ref else None,
                        ceiling=row.get("ceiling"),
                        floor=row.get("floor"),
                        change=(float(last) - float(ref)) if last and ref else None,
                        change_pct=((float(last) / float(ref) - 1) * 100) if last and ref else None,
                        volume=row.get("nmTotalTradedQty") or row.get("totalVolume"),
                        high=row.get("highest"),
                        low=row.get("lowest"),
                    )
                )
        return out

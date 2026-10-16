"""VNDirect finfo public API (api-finfo.vndirect.com.vn/v4): corporate events, foreign & proprietary flows,
broker recommendations, daily prices (backup). Prices returned in thousand VND."""

from datetime import date, datetime

from app.ingestion.adapters.base import Candle, DataAdapter

BASE = "https://api-finfo.vndirect.com.vn/v4"

EVENT_KIND = {
    "DIVIDEND": "CASH_DIVIDEND",
    "STOCKDIV": "STOCK_DIVIDEND",
    "KINDDIV": "BONUS",
    "ISSUE": "ISSUE",
    "MEETING": "AGM",
    "meetingRight": "AGM_RECORD",
    "POLL": "POLL",
    "LISTED": "LISTED",
    "updateListed": "LISTED",
    "ADPAYDATE": "PAY_DATE_CHANGE",
    "control": "ALERT_CONTROL",
    "halt": "ALERT_SPECIAL_CONTROL",
    "warning": "ALERT_WARNING",
    "noticed": "ALERT_NOTICE",
    "suspend": "ALERT_SUSPEND",
    "delistedUpcom": "ALERT_DELIST",
    "delisted": "ALERT_DELIST",
    "lastTradeUpcom": "ALERT_DELIST",
}


def _d(s) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)[:10]).date()
    except ValueError:
        return None


class VNDirectAdapter(DataAdapter):
    code = "VND"

    async def _get(self, path: str, params: dict) -> dict:
        r = await self.client.get(f"{BASE}/{path}", params=params)
        r.raise_for_status()
        return r.json() or {}

    async def _all(self, path: str, q: str, size: int = 1000, sort: str | None = None, max_pages: int = 20) -> list[dict]:
        out, page = [], 1
        while page <= max_pages:
            params = {"q": q, "size": size, "page": page}
            if sort:
                params["sort"] = sort
            d = await self._get(path, params)
            rows = d.get("data") or []
            out += rows
            if len(rows) < size or page >= (d.get("totalPages") or 1):
                break
            page += 1
        return out

    async def events(self, since: date, until: date | None = None, field: str = "disclosureDate") -> list[dict]:
        q = f"locale:VN~{field}:gte:{since.isoformat()}"
        if until:
            q += f"~{field}:lte:{until.isoformat()}"
        rows = await self._all("events", q, sort=f"{field}:desc")
        out = []
        for e in rows:
            kind = EVENT_KIND.get(e.get("type") or "")
            if not kind or not e.get("code") or len(e["code"]) > 6:
                continue
            ex = _d(e.get("effectiveDate"))
            if kind == "LISTED" and ex and ex.year > date.today().year + 2:
                ex = None  # VNDirect puts far-future dates on some listing records
            cash = e.get("dividend")
            out.append({
                "external_id": f"VND:{e.get('id')}",
                "symbol": e["code"].upper(),
                "kind": kind,
                "ex_date": ex if kind not in ("AGM",) else None,
                "record_date": _d(e.get("expiredDate")) if kind in ("CASH_DIVIDEND", "STOCK_DIVIDEND", "BONUS", "ISSUE", "AGM_RECORD") else None,
                "event_date": _d(e.get("actualDate")) or (ex if kind == "AGM" else None),
                "disclosure_date": _d(e.get("disclosureDate")),
                "ratio": e.get("ratio"),
                "cash_per_share": float(cash) if cash else None,
                "issue_price": e.get("price"),
                "shares": e.get("numberOfShares"),
                "title": (e.get("typeDesc") or "")[:255],
                "note": e.get("note"),
                "detail": {k: e.get(k) for k in ("type", "group", "divYear", "registerStartDate", "registerEndDate", "tradingStartDate", "tradingEndDate", "newsId") if e.get(k) is not None},
                "source": "VND",
            })
        return out

    async def foreign_flows(self, d: date) -> list[dict]:
        rows = await self._all("foreigns", f"tradingDate:{d.isoformat()}~type:STOCK", size=2000)
        return [{"symbol": r["code"].upper(), "trade_date": d, "foreign_buy_val": r.get("buyVal"), "foreign_sell_val": r.get("sellVal"),
                 "foreign_net_val": r.get("netVal"), "foreign_buy_vol": r.get("buyVol"), "foreign_sell_vol": r.get("sellVol"),
                 "foreign_net_vol": r.get("netVol"), "foreign_room": r.get("currentRoom")} for r in rows if r.get("code")]

    async def proprietary_flows(self, d: date) -> list[dict]:
        rows = await self._all("proprietary_trading", f"date:{d.isoformat()}~type:STOCK", size=2000)
        return [{"symbol": r["code"].upper(), "trade_date": d, "prop_buy_val": r.get("buyingVal"), "prop_sell_val": r.get("sellingVal"),
                 "prop_net_val": r.get("netVal")} for r in rows if r.get("code")]

    async def recommendations(self, since: date) -> list[dict]:
        rows = await self._all("recommendations", f"reportDate:gte:{since.isoformat()}", size=1000, sort="reportDate:desc")
        out = []
        for r in rows:
            if not r.get("code") or not r.get("firm") or not r.get("reportDate"):
                continue
            k = 1000.0
            out.append({"symbol": r["code"].upper(), "firm": r["firm"][:80], "rec_type": (r.get("type") or "")[:16] or None, "report_date": _d(r["reportDate"]),
                        "report_price": r["reportPrice"] * k if r.get("reportPrice") else None, "target_price": r["targetPrice"] * k if r.get("targetPrice") else None,
                        "analyst": (r.get("analyst") or "")[:120] or None, "source": (r.get("source") or "")[:40] or None})
        return out

    async def daily_history(self, symbol: str, start: date, end: date) -> list[Candle]:
        rows = await self._all("stock_prices", f"code:{symbol}~date:gte:{start.isoformat()}~date:lte:{end.isoformat()}", size=2000, sort="date")
        return [Candle(_d(r["date"]), r["adOpen"] * 1000, r["adHigh"] * 1000, r["adLow"] * 1000, r["adClose"] * 1000, int(r.get("nmVolume") or 0),
                       float(r.get("nmValue") or 0) or None) for r in rows if r.get("adClose")]

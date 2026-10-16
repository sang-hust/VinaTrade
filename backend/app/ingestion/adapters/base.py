"""Data-source adapter interface (spec 10: swap providers by writing a new adapter)."""

from dataclasses import dataclass
from datetime import date

import httpx

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"


@dataclass
class Candle:
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    value: float | None = None


@dataclass
class StockInfo:
    symbol: str
    exchange: str
    name_vi: str
    name_en: str | None = None
    short_name: str | None = None
    icb_lv2: str | None = None
    icb_lv4: str | None = None
    listed_shares: int | None = None
    ref_price: float | None = None
    ceiling: float | None = None
    floor: float | None = None
    status_flags: list[str] | None = None


@dataclass
class Quote:
    symbol: str
    price: float
    ref_price: float | None
    ceiling: float | None
    floor: float | None
    change: float | None
    change_pct: float | None
    volume: int | None
    high: float | None
    low: float | None
    value: float | None = None


class DataAdapter:
    code = "BASE"

    def __init__(self, timeout: float = 25.0):
        self.client = httpx.AsyncClient(timeout=timeout, headers={"User-Agent": UA, "Accept": "application/json"})

    async def close(self) -> None:
        await self.client.aclose()

    async def list_stocks(self) -> list[StockInfo]:
        raise NotImplementedError

    async def daily_history(self, symbol: str, start: date, end: date) -> list[Candle]:
        raise NotImplementedError

    async def index_history(self, index_code: str, start: date, end: date) -> list[Candle]:
        raise NotImplementedError

    async def quotes(self, symbols: list[str]) -> list[Quote]:
        raise NotImplementedError

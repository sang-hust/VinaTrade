"""Vietnam market time helpers: timezone, sessions, trading days, tick sizes (BR-03..BR-06)."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# Fixed public holidays (dd-mm). Lunar holidays (Tết, Giỗ Tổ) are added per year below.
FIXED_HOLIDAYS = {(1, 1), (30, 4), (1, 5), (2, 9)}
# Observed Tết + Giỗ Tổ Hùng Vương per year (HOSE announcements). Extend yearly.
LUNAR_HOLIDAYS: dict[int, list[tuple[int, int]]] = {
    2024: [(8, 2), (9, 2), (12, 2), (13, 2), (14, 2), (18, 4), (3, 9)],
    2025: [(27, 1), (28, 1), (29, 1), (30, 1), (31, 1), (7, 4)],
    2026: [(16, 2), (17, 2), (18, 2), (19, 2), (20, 2), (27, 4), (3, 9)],
    2027: [(5, 2), (8, 2), (9, 2), (10, 2), (11, 2), (16, 4)],
}


def now_vn() -> datetime:
    return datetime.now(VN_TZ)


def today_vn() -> date:
    return now_vn().date()


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=VN_TZ)
    return dt.astimezone(UTC)


def is_holiday(d: date) -> bool:
    if (d.day, d.month) in FIXED_HOLIDAYS:
        return True
    return (d.day, d.month) in LUNAR_HOLIDAYS.get(d.year, [])


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and not is_holiday(d)


def previous_trading_day(d: date | None = None) -> date:
    d = d or today_vn()
    d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def next_trading_day(d: date | None = None) -> date:
    d = d or today_vn()
    d += timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def add_sessions(d: date, n: int) -> date:
    for _ in range(n):
        d = next_trading_day(d)
    return d


def last_closed_trading_day() -> date:
    """The most recent trading day whose session has ended (after 15:00 VN)."""
    now = now_vn()
    d = now.date()
    if is_trading_day(d) and now.time() >= time(15, 0):
        return d
    return previous_trading_day(d)


def session_state(now: datetime | None = None) -> str:
    """PRE | ATO | CONTINUOUS | LUNCH | ATC | CLOSED | HOLIDAY"""
    now = now or now_vn()
    if not is_trading_day(now.date()):
        return "HOLIDAY"
    t = now.time()
    if t < time(9, 0):
        return "PRE"
    if t < time(9, 15):
        return "ATO"
    if t < time(11, 30):
        return "CONTINUOUS"
    if t < time(13, 0):
        return "LUNCH"
    if t < time(14, 30):
        return "CONTINUOUS"
    if t < time(14, 45):
        return "ATC"
    return "CLOSED"


def is_market_open(now: datetime | None = None) -> bool:
    return session_state(now) in ("ATO", "CONTINUOUS", "ATC")


def tick_size(price: float, exchange: str) -> int:
    if exchange.upper() in ("HNX", "UPCOM"):
        return 100
    if price < 10_000:
        return 10
    if price < 50_000:
        return 50
    return 100


def round_tick(price: float, exchange: str = "HOSE", mode: str = "nearest") -> int:
    if price is None or price <= 0:
        return 0
    t = tick_size(price, exchange)
    q = price / t
    if mode == "down":
        n = int(q)
    elif mode == "up":
        n = int(q) if q == int(q) else int(q) + 1
    else:
        n = int(q + 0.5)
    return int(n * t)


def floor_lot(qty: float, lot: int = 100) -> int:
    return int(qty // lot) * lot


def price_limit_pct(exchange: str) -> float:
    return {"HOSE": 7.0, "HNX": 10.0, "UPCOM": 15.0}.get(exchange.upper(), 7.0)


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def month_start(d: date) -> date:
    return d.replace(day=1)

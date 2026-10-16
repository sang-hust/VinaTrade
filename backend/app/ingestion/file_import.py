"""Admin price-file import (UC-11 / 4.6o): CSV, TXT or Excel with Vietnamese or English headers → preview → commit."""

import csv
import io
import re
import unicodedata
import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import bad_request
from app.core.vntime import is_trading_day
from app.ingestion.adapters.base import Candle
from app.ingestion.prices import upsert_candles
from app.models import JobRun, PriceDaily, Stock

ALIASES = {
    "symbol": ["ma", "ma ck", "ma chung khoan", "symbol", "ticker", "code", "ma co phieu"],
    "trade_date": ["ngay", "ngay gd", "ngay giao dich", "date", "trade_date", "time"],
    "open": ["mo cua", "gia mo cua", "open", "o"],
    "high": ["cao nhat", "gia cao nhat", "high", "h"],
    "low": ["thap nhat", "gia thap nhat", "low", "l"],
    "close": ["dong cua", "gia dong cua", "close", "c", "gia"],
    "volume": ["khoi luong", "kl", "volume", "vol", "v", "kl khop"],
}
_PENDING: dict[str, dict] = {}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn").replace("đ", "d").replace("Đ", "D")
    return re.sub(r"\s+", " ", s.strip().lower())


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "")
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", s):  # 128.500 or 128.500,5 (vi)
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", s):  # 128,500.5 (en)
        s = s.replace(",", "")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or "").strip()[:10]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _read(raw: bytes, filename: str) -> tuple[list[str], list[list]]:
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")):
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
        if not rows:
            return [], []
        return [str(h or "") for h in rows[0]], rows[1:]
    text = raw.decode("utf-8-sig", errors="ignore")
    sample = text[:4000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel_tab if "\t" in sample else csv.excel
    reader = list(csv.reader(io.StringIO(text), dialect=dialect))
    reader = [r for r in reader if any(c.strip() for c in r)]
    return (reader[0], reader[1:]) if reader else ([], [])


def map_columns(header: list[str]) -> dict[str, int]:
    norm = [_norm(h) for h in header]
    out = {}
    for key, names in ALIASES.items():
        for i, h in enumerate(norm):
            if h in names and key not in out:
                out[key] = i
    return out


async def preview_file(db: AsyncSession, raw: bytes, filename: str) -> dict:
    header, rows = _read(raw, filename)
    if not header:
        raise bad_request("FILE_EMPTY", "Tệp không có dữ liệu")
    cols = map_columns(header)
    sym_from_name = re.match(r"^([A-Za-z0-9]{3})[._ -]", filename)
    if "trade_date" not in cols or "close" not in cols or ("symbol" not in cols and not sym_from_name):
        raise bad_request("COLUMNS", "Không nhận dạng được cột bắt buộc (mã, ngày, đóng cửa). Hãy đặt tên cột: mã, ngày, mở cửa, cao nhất, thấp nhất, đóng cửa, khối lượng.",
                          {"header": header, "mapped": cols})
    active = {s for (s,) in (await db.execute(select(Stock.symbol).where(Stock.is_active))).all()}
    ok_rows, errors = [], []
    closes = []
    for i, r in enumerate(rows, start=2):
        try:
            sym = (str(r[cols["symbol"]]).strip().upper() if "symbol" in cols else sym_from_name.group(1).upper())
            d = _date(r[cols["trade_date"]])
            if not d:
                raise ValueError("ngày không hợp lệ")
            c = _num(r[cols["close"]])
            if c is None or c <= 0:
                raise ValueError("giá đóng cửa không hợp lệ")
            o = _num(r[cols["open"]]) if "open" in cols else c
            h = _num(r[cols["high"]]) if "high" in cols else max(o or c, c)
            lo = _num(r[cols["low"]]) if "low" in cols else min(o or c, c)
            v = _num(r[cols["volume"]]) if "volume" in cols else 0
            if sym not in active:
                raise ValueError(f"mã {sym} không có trong danh sách")
            if not is_trading_day(d):
                raise ValueError("không phải ngày giao dịch")
            ok_rows.append((sym, d, o or c, h or c, lo or c, c, int(v or 0)))
            closes.append(c)
        except Exception as e:  # noqa: BLE001
            errors.append({"row": i, "error": str(e)[:120]})
    # unit detection: thousand VND
    mult = 1000.0 if closes and max(closes) < 1000 else 1.0
    ok_rows = [(s, d, o * mult, h * mult, lo * mult, c * mult, v) for s, d, o, h, lo, c, v in ok_rows]
    # compare with existing
    existing = {}
    if ok_rows:
        syms = list({r[0] for r in ok_rows})
        dates = [r[1] for r in ok_rows]
        for p in (await db.execute(select(PriceDaily).where(PriceDaily.symbol.in_(syms), PriceDaily.trade_date >= min(dates), PriceDaily.trade_date <= max(dates)))).scalars():
            existing[(p.symbol, p.trade_date)] = p.close
    dup = [r for r in ok_rows if (r[0], r[1]) in existing]
    mismatches = [{"symbol": r[0], "date": r[1].isoformat(), "file": r[5], "api": existing[(r[0], r[1])]} for r in dup if abs(r[5] / existing[(r[0], r[1])] - 1) > 0.005]
    import_id = uuid.uuid4().hex
    _PENDING[import_id] = {"rows": ok_rows, "filename": filename, "errors": errors}
    return {"import_id": import_id, "filename": filename, "columns": {k: header[i] for k, i in cols.items()}, "unit": "nghìn đồng → ×1000" if mult > 1 else "đồng",
            "preview": [{"symbol": r[0], "date": r[1].isoformat(), "open": r[2], "high": r[3], "low": r[4], "close": r[5], "volume": r[6]} for r in ok_rows[:20]],
            "rows_ok": len(ok_rows), "rows_error": len(errors), "errors": errors[:100], "new_sessions": len(ok_rows) - len(dup), "duplicate_sessions": len(dup),
            "mismatches": mismatches[:50], "symbols": sorted({r[0] for r in ok_rows})}


async def commit_import(db: AsyncSession, import_id: str, mode: str, by: str) -> dict:
    p = _PENDING.pop(import_id, None)
    if not p:
        raise bad_request("IMPORT_EXPIRED", "Phiên nhập đã hết hạn, hãy tải lại tệp")
    by_sym: dict[str, list[Candle]] = {}
    for s, d, o, h, lo, c, v in p["rows"]:
        by_sym.setdefault(s, []).append(Candle(d, o, h, lo, c, v, c * v))
    n = 0
    for s, candles in by_sym.items():
        n += await upsert_candles(db, s, candles, "FILE", overwrite=(mode == "OVERWRITE"))
    job = JobRun(name="price_file_import", status="DONE", finished_at=datetime.now().astimezone(), triggered_by=f"admin:{by}",
                 summary=f"{p['filename']}: {n} dòng, {len(p['errors'])} lỗi, {mode}", meta={"file": p["filename"], "user": by, "rows_ok": n, "rows_err": len(p["errors"]), "errors": p["errors"][:100], "mode": mode, "symbols": sorted(by_sym)})
    db.add(job)
    await db.flush()
    return {"rows": n, "symbols": sorted(by_sym), "mode": mode, "job_id": job.id}

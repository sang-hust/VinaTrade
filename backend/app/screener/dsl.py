"""Condition DSL shared by screeners, alert rules and trade-plan steps (spec 5).

Condition := {"all": [...]} | {"any": [...]} | {"not": c} | {"field", "op", "value", "lookback"?}
Two executors: to_sql() → SQLAlchemy clause on stock_snapshots; evaluate() → in-memory on a snapshot dict
(used in intraday evaluation and plan steps)."""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import and_, cast, not_, or_
from sqlalchemy.sql import ColumnElement
from sqlalchemy.types import Text

from app.core.errors import bad_request
from app.models import StockSnapshot

FIELDS: dict[str, dict] = {
    # giá & khối lượng
    "price": {"type": "num", "vi": "Giá", "group": "price"},
    "change_pct": {"type": "num", "vi": "% thay đổi", "group": "price"},
    "volume": {"type": "num", "vi": "Khối lượng", "group": "price"},
    "vol_ratio": {"type": "num", "vi": "KL / TB20", "group": "price"},
    "value": {"type": "num", "vi": "Giá trị GD", "group": "price"},
    "value_ma20": {"type": "num", "vi": "GTGD TB 20 phiên", "group": "price"},
    "high_52w": {"type": "num", "vi": "Đỉnh 52 tuần", "group": "price"},
    "low_52w": {"type": "num", "vi": "Đáy 52 tuần", "group": "price"},
    # chỉ báo
    "ma10": {"type": "num", "vi": "MA10", "group": "ta"}, "ma20": {"type": "num", "vi": "MA20", "group": "ta"},
    "ma50": {"type": "num", "vi": "MA50", "group": "ta"}, "ma200": {"type": "num", "vi": "MA200", "group": "ta"},
    "rsi14": {"type": "num", "vi": "RSI (14)", "group": "ta"}, "macd": {"type": "num", "vi": "MACD", "group": "ta"},
    "macd_signal": {"type": "num", "vi": "MACD tín hiệu", "group": "ta"}, "macd_hist": {"type": "num", "vi": "MACD histogram", "group": "ta"},
    "adx14": {"type": "num", "vi": "ADX (14)", "group": "ta"}, "atr14": {"type": "num", "vi": "ATR (14)", "group": "ta"},
    "bb_upper": {"type": "num", "vi": "Bollinger trên", "group": "ta"}, "bb_lower": {"type": "num", "vi": "Bollinger dưới", "group": "ta"},
    "bb_width": {"type": "num", "vi": "Độ rộng Bollinger %", "group": "ta"}, "mfi14": {"type": "num", "vi": "MFI (14)", "group": "ta"},
    "cmf20": {"type": "num", "vi": "Chaikin Money Flow", "group": "ta"}, "stoch_k": {"type": "num", "vi": "Stochastic %K", "group": "ta"},
    "rs_rating": {"type": "num", "vi": "Xếp hạng RS", "group": "ta"},
    "trend_state": {"type": "enum", "vi": "Xu hướng", "group": "ta", "values": ["STRONG_UP", "UP", "FLAT", "DOWN", "STRONG_DOWN"]},
    "support_1": {"type": "num", "vi": "Hỗ trợ gần nhất", "group": "ta"}, "resistance_1": {"type": "num", "vi": "Kháng cự gần nhất", "group": "ta"},
    "dist_ma50_pct": {"type": "num", "vi": "% cách MA50", "group": "ta"}, "ma50_slope": {"type": "num", "vi": "Độ dốc MA50 (10 phiên, %)", "group": "ta"},
    "ceiling_streak": {"type": "num", "vi": "Số phiên trần liên tiếp", "group": "ta"},
    "golden_cross_days": {"type": "num", "vi": "Số phiên từ khi MA50 cắt lên MA200", "group": "ta"},
    "death_cross_days": {"type": "num", "vi": "Số phiên từ khi MA50 cắt xuống MA200", "group": "ta"},
    # định giá
    "pe": {"type": "num", "vi": "P/E", "group": "val"}, "pb": {"type": "num", "vi": "P/B", "group": "val"},
    "ps": {"type": "num", "vi": "P/S", "group": "val"}, "peg": {"type": "num", "vi": "PEG", "group": "val"},
    "market_cap": {"type": "num", "vi": "Vốn hóa", "group": "val"}, "fair_value": {"type": "num", "vi": "Giá trị thực", "group": "val"},
    "margin_of_safety": {"type": "num", "vi": "Biên an toàn %", "group": "val"}, "dividend_yield": {"type": "num", "vi": "Tỷ suất cổ tức %", "group": "val"},
    # cơ bản
    "roe": {"type": "num", "vi": "ROE %", "group": "fund"}, "roa": {"type": "num", "vi": "ROA %", "group": "fund"},
    "gross_margin": {"type": "num", "vi": "Biên LN gộp %", "group": "fund"}, "net_margin": {"type": "num", "vi": "Biên LN ròng %", "group": "fund"},
    "debt_to_equity": {"type": "num", "vi": "Nợ vay / VCSH", "group": "fund"}, "current_ratio": {"type": "num", "vi": "Thanh toán hiện hành", "group": "fund"},
    "revenue_yoy": {"type": "num", "vi": "Tăng trưởng DT quý %", "group": "fund"}, "profit_yoy": {"type": "num", "vi": "Tăng trưởng LN quý %", "group": "fund"},
    "revenue_cagr_3y": {"type": "num", "vi": "CAGR doanh thu 3 năm %", "group": "fund"}, "profit_cagr_3y": {"type": "num", "vi": "CAGR lợi nhuận 3 năm %", "group": "fund"},
    "cfo_to_profit": {"type": "num", "vi": "Dòng tiền KD / LN", "group": "fund"},
    # điểm & tín hiệu
    "score_short": {"type": "num", "vi": "Điểm ngắn hạn", "group": "score"}, "score_mid": {"type": "num", "vi": "Điểm trung hạn", "group": "score"},
    "score_long": {"type": "num", "vi": "Điểm dài hạn", "group": "score"},
    "rating": {"type": "enum", "vi": "Khuyến nghị", "group": "score", "values": ["STRONG_BUY", "BUY", "HOLD", "REDUCE", "SELL"]},
    "base_status": {"type": "enum", "vi": "Trạng thái nền", "group": "score", "values": ["FORMING", "BROKEN_OUT", "FAILED"]},
    "base_length_days": {"type": "num", "vi": "Số phiên của nền", "group": "score"},
    "base_tightness": {"type": "num", "vi": "Độ chặt nền (%)", "group": "score"},
    "rally_gain_vs_median": {"type": "num", "vi": "Mức tăng so với đợt trung bình (%)", "group": "score"},
    "gain_from_base_pct": {"type": "num", "vi": "% cách điểm phá nền", "group": "score"},
    "signal": {"type": "signal", "vi": "Tín hiệu hệ thống", "group": "score"},
    # phân loại
    "symbol": {"type": "str", "vi": "Mã", "group": "cls"},
    "exchange": {"type": "enum", "vi": "Sàn", "group": "cls", "values": ["HOSE", "HNX", "UPCOM"]},
    "industry_code": {"type": "str", "vi": "Ngành", "group": "cls"},
    "in_vn30": {"type": "bool", "vi": "Thuộc VN30", "group": "cls"},
    # rủi ro
    "risk_score": {"type": "num", "vi": "Điểm rủi ro DN", "group": "risk"},
    "beta_60": {"type": "num", "vi": "Beta 60 phiên", "group": "risk"},
    "earnings_in_days": {"type": "num", "vi": "Số phiên tới BCTC/GDKHQ", "group": "risk"},
    # danh mục (chỉ dùng trong cảnh báo / kế hoạch, đánh giá trong bộ nhớ)
    "position_pnl_pct": {"type": "num", "vi": "Lãi/lỗ vị thế %", "group": "pf", "memory_only": True},
    "position_weight_pct": {"type": "num", "vi": "Tỷ trọng vị thế %", "group": "pf", "memory_only": True},
    "price_vs_stop_pct": {"type": "num", "vi": "% giá so với cắt lỗ", "group": "pf", "memory_only": True},
    "guard_mode": {"type": "enum", "vi": "Chế độ cầu dao", "group": "pf", "memory_only": True, "values": ["NORMAL", "DEFENSIVE"]},
}
OPS = [">", ">=", "<", "<=", "==", "!=", "between", "in", "not_in", "cross_above", "cross_below", "pct_change_gte",
       "pct_change_lte", "near", "rising", "falling", "has_signal"]
MAX_RULES = 40


class DslError(ValueError):
    pass


def validate(cond: Any, depth: int = 0, count: list | None = None) -> None:
    count = count if count is not None else [0]
    if depth > 6:
        raise DslError("Điều kiện lồng quá sâu")
    if not isinstance(cond, dict):
        raise DslError("Điều kiện phải là một đối tượng")
    if "all" in cond or "any" in cond:
        key = "all" if "all" in cond else "any"
        if not isinstance(cond[key], list) or not cond[key]:
            raise DslError(f"'{key}' phải là danh sách không rỗng")
        for c in cond[key]:
            validate(c, depth + 1, count)
        return
    if "not" in cond:
        validate(cond["not"], depth + 1, count)
        return
    count[0] += 1
    if count[0] > MAX_RULES:
        raise DslError(f"Tối đa {MAX_RULES} điều kiện")
    f, op = cond.get("field"), cond.get("op")
    if f not in FIELDS:
        raise DslError(f"Trường không hỗ trợ: {f}")
    if op not in OPS:
        raise DslError(f"Toán tử không hỗ trợ: {op}")
    v = cond.get("value")
    if op == "between" and not (isinstance(v, list) and len(v) == 2):
        raise DslError("'between' cần [min, max]")
    if op in ("in", "not_in") and not isinstance(v, list):
        raise DslError(f"'{op}' cần danh sách")
    if isinstance(v, dict) and "field" in v and v["field"] not in FIELDS:
        raise DslError(f"Trường so sánh không hỗ trợ: {v['field']}")


def _col(name: str):
    return getattr(StockSnapshot, name)


def _rhs(v, sa: bool):
    if isinstance(v, dict) and "field" in v:
        return _col(v["field"]) if sa else ("__field__", v["field"])
    return v


def to_sql(cond: dict) -> ColumnElement:
    if "all" in cond:
        return and_(*[to_sql(c) for c in cond["all"]])
    if "any" in cond:
        return or_(*[to_sql(c) for c in cond["any"]])
    if "not" in cond:
        return not_(to_sql(cond["not"]))
    f, op, v = cond["field"], cond["op"], cond.get("value")
    meta = FIELDS[f]
    if meta.get("memory_only"):
        raise DslError(f"Trường {f} chỉ dùng cho cảnh báo danh mục")
    if op == "has_signal":
        # signals_today is JSON [{"code":..}] → text search; cheap and good enough for ≤ 2k rows
        return cast(StockSnapshot.signals_today, Text).like(f'%"{v}"%')
    col = _col(f)
    r = _rhs(v, True)
    if op == ">":
        return col > r
    if op == ">=":
        return col >= r
    if op == "<":
        return col < r
    if op == "<=":
        return col <= r
    if op == "==":
        return col == r
    if op == "!=":
        return col != r
    if op == "between":
        return and_(col >= v[0], col <= v[1])
    if op == "in":
        return col.in_(v)
    if op == "not_in":
        return not_(col.in_(v))
    if op == "near":
        tgt, pct = (_col(v["field"]) if isinstance(v, dict) else v), (v.get("pct", 2) if isinstance(v, dict) else 2)
        return and_(col >= tgt * (1 - pct / 100), col <= tgt * (1 + pct / 100))
    if op == "cross_above":
        # cross events are precomputed for MA50×MA200; for price×MA use dist + previous close via golden days when possible
        lb = cond.get("lookback", 3)
        if f == "ma50" and isinstance(v, dict) and v.get("field") == "ma200":
            return and_(StockSnapshot.golden_cross_days.isnot(None), StockSnapshot.golden_cross_days <= lb)
        return and_(col > r, StockSnapshot.rating_changed.is_(True)) if False else col > r
    if op == "cross_below":
        lb = cond.get("lookback", 3)
        if f == "ma50" and isinstance(v, dict) and v.get("field") == "ma200":
            return and_(StockSnapshot.death_cross_days.isnot(None), StockSnapshot.death_cross_days <= lb)
        return col < r
    if op in ("pct_change_gte", "pct_change_lte", "rising", "falling"):
        # only change_pct (1 session) available on the snapshot; longer lookbacks are evaluated in memory
        if f == "price" and op == "pct_change_gte":
            return StockSnapshot.change_pct >= v
        if f == "price" and op == "pct_change_lte":
            return StockSnapshot.change_pct <= v
        if f == "ma50" and op == "rising":
            return StockSnapshot.ma50_slope > 0
        if f == "ma50" and op == "falling":
            return StockSnapshot.ma50_slope < 0
        raise DslError(f"Toán tử {op} với trường {f} chưa hỗ trợ trong bộ lọc")
    raise DslError(f"Toán tử không hỗ trợ: {op}")


def _num(x):
    if x is None:
        return None
    if isinstance(x, float) and math.isnan(x):
        return None
    return x


def evaluate(cond: dict, row: dict, history: dict | None = None) -> bool:
    """row: snapshot-like dict (may include portfolio fields). history: {field: [older..newer]} for cross/lookback ops."""
    if "all" in cond:
        return all(evaluate(c, row, history) for c in cond["all"])
    if "any" in cond:
        return any(evaluate(c, row, history) for c in cond["any"])
    if "not" in cond:
        return not evaluate(cond["not"], row, history)
    f, op, v = cond["field"], cond["op"], cond.get("value")
    lb = int(cond.get("lookback") or 3)
    if op == "has_signal":
        return any((s.get("code") if isinstance(s, dict) else s) == v for s in (row.get("signals_today") or []))
    x = _num(row.get(f))
    if isinstance(v, dict) and "field" in v and op not in ("near",):
        v = _num(row.get(v["field"]))
    if op in (">", ">=", "<", "<=", "==", "!=", "between", "in", "not_in", "near"):
        if x is None:
            return False
        if op == ">":
            return v is not None and x > v
        if op == ">=":
            return v is not None and x >= v
        if op == "<":
            return v is not None and x < v
        if op == "<=":
            return v is not None and x <= v
        if op == "==":
            return x == v
        if op == "!=":
            return x != v
        if op == "between":
            return v[0] <= x <= v[1]
        if op == "in":
            return x in v
        if op == "not_in":
            return x not in v
        if op == "near":
            tgt = _num(row.get(v["field"])) if isinstance(v, dict) else v
            pct = v.get("pct", 2) if isinstance(v, dict) else 2
            return tgt is not None and abs(x / tgt - 1) * 100 <= pct
    h = (history or {}).get(f) or []
    if op in ("cross_above", "cross_below"):
        other = (history or {}).get(v["field"]) if isinstance(v, dict) else None
        if not h or len(h) < 2:
            return False
        seq = h[-(lb + 1) :]
        oth = other[-(lb + 1) :] if other else [v] * len(seq)
        diffs = [a - b for a, b in zip(seq, oth, strict=False) if a is not None and b is not None]
        if len(diffs) < 2:
            return False
        return (diffs[-1] > 0 and any(d <= 0 for d in diffs[:-1])) if op == "cross_above" else (diffs[-1] < 0 and any(d >= 0 for d in diffs[:-1]))
    if op in ("pct_change_gte", "pct_change_lte"):
        if len(h) <= lb or not h[-1 - lb]:
            return False
        ch = (h[-1] / h[-1 - lb] - 1) * 100
        return ch >= v if op == "pct_change_gte" else ch <= v
    if op in ("rising", "falling"):
        seq = [s for s in h[-(lb + 1) :] if s is not None]
        if len(seq) < 2:
            return False
        return all(b > a for a, b in zip(seq, seq[1:], strict=False)) if op == "rising" else all(b < a for a, b in zip(seq, seq[1:], strict=False))
    return False


def ensure_valid(cond: dict) -> None:
    try:
        validate(cond)
    except DslError as e:
        raise bad_request("DSL_INVALID", str(e)) from e


def describe(cond: dict) -> list[str]:
    """Human-readable chips for the applied conditions (Vietnamese)."""
    out = []
    if "all" in cond:
        for c in cond["all"]:
            out += describe(c)
        return out
    if "any" in cond:
        return [" HOẶC ".join(" ".join(describe(c)) for c in cond["any"])]
    if "not" in cond:
        return ["KHÔNG (" + " ".join(describe(cond["not"])) + ")"]
    f, op, v = cond["field"], cond["op"], cond.get("value")
    name = FIELDS.get(f, {}).get("vi", f)
    opv = {">": ">", ">=": "≥", "<": "<", "<=": "≤", "==": "=", "!=": "≠"}.get(op)
    if isinstance(v, dict) and "field" in v:
        v = FIELDS.get(v["field"], {}).get("vi", v["field"])
    if opv:
        return [f"{name} {opv} {_fmt(v)}"]
    if op == "between":
        return [f"{name} {_fmt(v[0])}–{_fmt(v[1])}"]
    if op in ("in", "not_in"):
        return [f"{name} {'∈' if op == 'in' else '∉'} {', '.join(map(str, v))}"]
    if op == "has_signal":
        return [f"Có tín hiệu {v}"]
    if op in ("cross_above", "cross_below"):
        return [f"{name} cắt {'lên' if op == 'cross_above' else 'xuống'} {v}"]
    return [f"{name} {op} {_fmt(v)}"]


def _fmt(v):
    if isinstance(v, (int, float)):
        if abs(v) >= 1e9:
            return f"{v / 1e9:g} tỷ"
        if abs(v) >= 1e6:
            return f"{v / 1e6:g} tr"
        return f"{v:g}"
    return str(v)

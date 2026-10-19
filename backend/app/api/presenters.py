"""Row → API dict helpers shared by routers (prices in VND integers per BR-23)."""

import math
from datetime import date, datetime
from decimal import Decimal

from app.engines.scoring import RATING_VI

RATING_LABEL = RATING_VI
TREND_SYMBOL = {"UP": "▲", "FLAT": "▬", "DOWN": "▼"}
REGIME_VI = {"UPTREND": "tăng", "PRESSURE": "chịu áp lực", "CORRECTION": "điều chỉnh", "DOWNTREND": "giảm"}
RISK_VI = {"LOW": "Thấp", "MEDIUM": "Trung bình", "HIGH": "Cao"}


def clean(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 4)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def row(obj, cols: list[str], **extra) -> dict:
    d = {c: clean(getattr(obj, c, None)) for c in cols}
    d.update(extra)
    return d


def price_int(v) -> int | None:
    v = clean(v)
    return int(round(v)) if v is not None else None


SNAP_LIST_COLS = ["symbol", "exchange", "industry_code", "in_vn30", "price", "change", "change_pct", "ref_price", "ceiling", "floor", "volume", "value", "vol_ratio", "value_ma20",
                  "rsi14", "ma20", "ma50", "ma200", "dist_ma50_pct", "trend_state", "rs_rating", "score_short", "score_mid", "score_long", "rating_short", "rating_mid", "rating_long",
                  "rating", "trend_short", "trend_mid", "trend_long", "entry_low", "entry_high", "stop_loss", "take_profit_1", "risk_score", "risk_level", "is_chase",
                  "risk_total", "risk_total_level", "score_adj_short", "score_adj_mid", "score_adj_long",
                  "gain_from_base_pct", "base_status", "pe", "pb", "roe", "profit_yoy", "margin_of_safety", "rating_changed", "prev_rating", "signals_today", "trade_date", "high_52w", "low_52w", "market_cap",
                  "foreign_net_today", "foreign_net_5d", "foreign_net_20d", "prop_net_5d", "insider_net_90d", "consensus_target", "consensus_upside_pct",
                  "news_sentiment_7d", "news_count_7d", "next_event", "earnings_in_days", "dividend_yield"]


def snapshot_item(s, stock=None, horizon: str = "MID") -> dict:
    d = row(s, SNAP_LIST_COLS)
    for k in ("price", "change", "ref_price", "ceiling", "floor", "entry_low", "entry_high", "stop_loss", "take_profit_1", "ma20", "ma50", "ma200", "high_52w", "low_52w", "consensus_target"):
        d[k] = price_int(d.get(k))
    hz = horizon.lower()
    d["score"] = d.get(f"score_{hz}")
    d["rating_hz"] = d.get(f"rating_{hz}")
    d["rating_vi"] = RATING_LABEL.get(d.get(f"rating_{hz}") or d.get("rating"))
    d["trend3"] = "".join(TREND_SYMBOL.get(d.get(k) or "FLAT", "▬") for k in ("trend_short", "trend_mid", "trend_long"))
    d["risk_vi"] = RISK_VI.get(d.get("risk_level"))
    d["score_adj"] = d.get(f"score_adj_{hz}")
    d["risk_total_vi"] = RISK_VI.get(d.get("risk_total_level"))
    if stock is not None:
        d["name"] = stock.short_name or stock.name_vi
        d["name_full"] = stock.name_vi
        d["status_flags"] = stock.status_flags or []
    return d

"""Technical / fundamental / composite scoring and trade plan (spec 3.2d, 3.3c, 4.2, 4.3, 4.6 d/e)."""

import math

import numpy as np
import pandas as pd

from app.core.vntime import floor_lot, round_tick

DEFAULT_WEIGHTS = {
    "SHORT": {"tech": 55, "fund": 10, "sector": 10, "pattern": 25},
    "MID": {"tech": 35, "fund": 30, "sector": 15, "pattern": 20},
    "LONG": {"tech": 15, "fund": 55, "sector": 20, "pattern": 10},
}
RATING_THRESHOLDS = [(80, "STRONG_BUY"), (65, "BUY"), (50, "HOLD"), (35, "REDUCE"), (0, "SELL")]
RATING_VI = {"STRONG_BUY": "Mua mạnh", "BUY": "Tích lũy", "HOLD": "Nắm giữ", "REDUCE": "Giảm tỷ trọng", "SELL": "Bán"}
RATING_ORDER = ["SELL", "REDUCE", "HOLD", "BUY", "STRONG_BUY"]


def rating_for(score: float | None) -> str | None:
    if score is None or (isinstance(score, float) and math.isnan(score)):
        return None
    for th, label in RATING_THRESHOLDS:
        if score >= th:
            return label
    return "SELL"


def downgrade(rating: str | None, steps: int = 1) -> str | None:
    if rating is None:
        return None
    i = max(0, RATING_ORDER.index(rating) - steps)
    return RATING_ORDER[i]


def _clip(x: float, lo: float = 0, hi: float = 100) -> float:
    return float(max(lo, min(hi, x)))


def _nz(v, default=np.nan):
    return default if v is None or (isinstance(v, float) and math.isnan(v)) else v


def tech_components(row: dict) -> dict:
    """row = latest indicator values for one symbol. Returns 0–100 components + weighted tech score."""
    c = _nz(row.get("close"))
    ma10, ma20, ma50, ma200 = (_nz(row.get(k)) for k in ("ma10", "ma20", "ma50", "ma200"))
    adx_v = _nz(row.get("adx14"), 15)
    slope50, slope200 = _nz(row.get("ma50_slope"), 0), _nz(row.get("ma200_slope"), 0)
    # Trend (30%)
    t = 50.0
    if not np.isnan(ma50):
        t += 15 if c > ma50 else -15
    if not np.isnan(ma200):
        t += 10 if c > ma200 else -10
        t += 10 if ma50 > ma200 else -10
    if not np.isnan(ma10) and not np.isnan(ma20):
        t += 5 if c > ma10 > ma20 else (-5 if c < ma10 < ma20 else 0)
    t += _clip(slope50 * 2, -10, 10) + _clip(slope200 * 2, -5, 5)
    t += (adx_v - 20) * 0.5 if (not np.isnan(ma50) and c > ma50) else -(adx_v - 20) * 0.3
    trend = _clip(t)
    # Momentum (20%)
    rsi = _nz(row.get("rsi14"), 50)
    if rsi > 75:
        m = 55 - (rsi - 75) * 2
    elif rsi >= 50:
        m = 60 + (rsi - 50) * 1.6  # 50→60, 70→92
    elif rsi >= 30:
        m = 30 + (rsi - 30) * 1.5
    else:
        m = 25
    hist, macd_v, sig = _nz(row.get("macd_hist"), 0), _nz(row.get("macd"), 0), _nz(row.get("macd_signal"), 0)
    m += 8 if macd_v > sig else -8
    m += 4 if hist > 0 else -4
    momentum = _clip(m)
    # Volume & money flow (20%)
    vr = _nz(row.get("vol_ratio"), 1)
    chg = _nz(row.get("change_pct"), 0)
    v = 50.0
    if chg > 0:
        v += _clip((vr - 1) * 25, -15, 25)
    else:
        v -= _clip((vr - 1) * 25, -10, 25)
    cmf_v, mfi_v = _nz(row.get("cmf20"), 0), _nz(row.get("mfi14"), 50)
    v += _clip(cmf_v * 100, -15, 15) + (mfi_v - 50) * 0.3
    v -= 3 * _nz(row.get("distribution_days"), 0)
    volume = _clip(v)
    # Relative strength (15%)
    rs = _clip(_nz(row.get("rs_rating"), 50))
    # Pattern & price zone (15%)
    pz = 50.0
    base_status = row.get("base_status")
    gain = _nz(row.get("gain_from_base_pct"), np.nan)
    sup, res = _nz(row.get("support_1")), _nz(row.get("resistance_1"))
    if base_status == "FORMING":
        tight = _nz(row.get("base_tightness"), 10)
        pz += 20 - min(tight, 10)
    if base_status == "BROKEN_OUT" and not np.isnan(gain):
        pz += 30 if gain <= 5 else (15 if gain <= 12 else (-5 if gain <= 20 else -20))
    if not np.isnan(sup) and c > 0:
        d_sup = (c - sup) / c * 100
        pz += 10 if d_sup <= 4 else 0
    if not np.isnan(res) and c > 0:
        d_res = (res - c) / c * 100
        pz += 5 if d_res >= 8 else (-10 if d_res < 2 else 0)
    bbw = _nz(row.get("bb_width"), np.nan)
    if not np.isnan(bbw) and bbw < 8:
        pz += 5  # squeeze
    pattern = _clip(pz)
    tech = 0.30 * trend + 0.20 * momentum + 0.20 * volume + 0.15 * rs + 0.15 * pattern
    return {"tech": round(tech, 1), "tech_trend": round(trend, 1), "tech_momentum": round(momentum, 1),
            "tech_volume": round(volume, 1), "tech_rs": round(rs, 1), "tech_pattern": round(pattern, 1)}


def fund_components(r: dict, pct: dict) -> dict:
    """r = financial ratio row; pct = percentiles within industry (0–100) for each ratio key, precomputed."""

    def p(key, default=50.0, invert=False):
        v = pct.get(key)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return default
        return 100 - v if invert else v

    growth = 0.4 * p("profit_yoy") + 0.3 * p("revenue_yoy") + 0.15 * p("profit_cagr_3y") + 0.15 * p("revenue_cagr_3y")
    prof = 0.4 * p("roe") + 0.25 * p("roa") + 0.2 * p("net_margin") + 0.15 * p("gross_margin")
    health = 0.4 * p("debt_to_equity", invert=True) + 0.3 * p("current_ratio") + 0.3 * p("cfo_to_profit")
    val = 0.35 * p("pe", invert=True) + 0.25 * p("pb", invert=True) + 0.2 * p("peg", invert=True) + 0.2 * p("dividend_yield")
    # absolute sanity: negative profit or negative equity caps the score
    if _nz(r.get("roe"), 0) < 0 or _nz(r.get("net_margin"), 0) < 0:
        prof = min(prof, 30)
    if _nz(r.get("pe"), 0) <= 0:
        val = min(val, 35)
    fund = 0.30 * growth + 0.25 * prof + 0.20 * health + 0.25 * val
    return {"fund": round(_clip(fund), 1), "fund_growth": round(_clip(growth), 1), "fund_profitability": round(_clip(prof), 1),
            "fund_health": round(_clip(health), 1), "fund_valuation": round(_clip(val), 1)}


def pattern_ai_score(row: dict, rally: dict | None) -> float:
    """'Thống kê nền giá & AI' component: how much room the current move has vs the stock's own history."""
    s = 50.0
    base_status = row.get("base_status")
    gain = _nz(row.get("gain_from_base_pct"), np.nan)
    if rally and rally.get("median_gain_pct") and not np.isnan(gain) and base_status == "BROKEN_OUT":
        ratio = gain / rally["median_gain_pct"]
        s += 30 if ratio < 0.3 else (15 if ratio < 0.6 else (-10 if ratio < 0.9 else -30))
    elif base_status == "FORMING":
        tight = _nz(row.get("base_tightness"), 10)
        s += 15 if tight < 3 else (8 if tight < 5 else 0)
        vd = _nz(row.get("vol_dry_ratio"), 1)
        s += 10 if vd < 0.7 else 0
    rsi = _nz(row.get("rsi14"), 50)
    if rsi > 78:
        s -= 15
    dist = _nz(row.get("dist_ma50_pct"), 0)
    if dist > 25:
        s -= 15
    return _clip(s)


def composite(tech: float, fund: float, sector: float, pattern: float, weights: dict, regime: str) -> dict:
    out = {}
    for hz in ("SHORT", "MID", "LONG"):
        w = weights.get(hz, DEFAULT_WEIGHTS[hz])
        total = (w["tech"] * tech + w["fund"] * fund + w["sector"] * sector + w["pattern"] * pattern) / 100
        if regime == "DOWNTREND":
            total -= 10
        out[hz] = round(_clip(total), 1)
    return out


# Stop / take-profit placement (4b study). The old rule took the TIGHTEST of (2×ATR, 7%, just under support) → 54% of
# buys were stopped out. Now: ATR-based distance clamped to [floor, cap] % of price, optionally widened to just under a
# nearby support; TP1 at tp_rr × risk (or the resistance if higher). Admin-editable via system_config "plan.params".
# 4b study (2.032 tín hiệu mua 6/2025–10/2026, mô phỏng sát thực tế): stop ≈ 5% (ATR nếu lớn hơn, tối đa 8%), TP1 = 1.5 × risk
# gave the best expectancy and smallest tail loss; wider stops lost more per stop than they saved in whipsaws.
DEFAULT_PLAN_PARAMS = {"atr_mult": 1.0, "stop_floor_pct": 5.0, "stop_cap_pct": 8.0, "use_support": 0, "tp_rr": 1.5}  # use_support: 0/1 (admin form)


def plan_levels(close: float, atr14: float | None, support: float | None, resistance: float | None, params: dict | None = None) -> dict:
    p = {**DEFAULT_PLAN_PARAMS, **(params or {})}
    atr_v = atr14 if atr14 and not math.isnan(atr14) else close * 0.025
    dist = float(p["atr_mult"]) * atr_v
    dist = min(max(dist, close * float(p["stop_floor_pct"]) / 100), close * float(p["stop_cap_pct"]) / 100)
    stop = close - dist
    if p.get("use_support") and support and not math.isnan(support) and support < close:
        s_stop = support * 0.99
        if s_stop < stop and (close - s_stop) <= close * float(p["stop_cap_pct"]) / 100:
            stop = s_stop  # widen to sit under the support, never beyond the cap
    risk = close - stop
    tp1 = max(resistance if resistance and not math.isnan(resistance) and resistance > close * 1.03 else 0, close + float(p["tp_rr"]) * risk)
    tp2 = max(close + (float(p["tp_rr"]) + 1.5) * risk, tp1 * 1.08)
    return {"stop": stop, "tp1": tp1, "tp2": tp2, "risk": risk}


def trade_plan(close: float, atr14: float | None, support: float | None, resistance: float | None,
               exchange: str, stop_pct: float = 7.0, base_high: float | None = None, params: dict | None = None) -> dict:
    """Entry zone / stop loss / take profit per spec 4.6e (levels from plan_levels), rounded to tick."""
    if not close or close <= 0:
        return {}
    lv = plan_levels(close, atr14, support, resistance, {**(params or {}), **({"stop_floor_pct": stop_pct} if params is None and stop_pct != 7.0 else {})})
    stop, tp1, tp2, risk = lv["stop"], lv["tp1"], lv["tp2"], lv["risk"]
    if base_high and base_high < close <= base_high * 1.05:
        entry_low, entry_high = base_high * 0.99, base_high * 1.03
    else:
        entry_low, entry_high = close * 0.975, close * 1.01
    rr = (tp1 - close) / risk if risk > 0 else None
    return {
        "entry_low": round_tick(entry_low, exchange, "down"),
        "entry_high": round_tick(entry_high, exchange, "up"),
        "stop_loss": round_tick(stop, exchange, "down"),
        "take_profit_1": round_tick(tp1, exchange, "up"),
        "take_profit_2": round_tick(tp2, exchange, "up"),
        "risk_reward": round(rr, 2) if rr else None,
    }


def position_size(equity: float, entry: float, stop: float, risk_pct: float, max_position_pct: float) -> int:
    if entry <= stop or equity <= 0:
        return 0
    qty = equity * risk_pct / 100 / (entry - stop)
    qty = min(qty, equity * max_position_pct / 100 / entry)
    return floor_lot(qty)


def percentile_within_groups(df: pd.DataFrame, group_col: str, cols: list[str]) -> pd.DataFrame:
    """Percentile rank (0–100) of each col within its group; falls back to global rank when group < 5 rows."""
    out = pd.DataFrame(index=df.index)
    sizes = df.groupby(group_col)[cols[0]].transform("size")
    for col in cols:
        grp = df.groupby(group_col)[col].rank(pct=True) * 100
        glob = df[col].rank(pct=True) * 100
        out[col] = np.where(sizes >= 5, grp, glob)
    return out

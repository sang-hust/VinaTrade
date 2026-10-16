"""Signal strategies (spec 3.2c, 3.4b). Each takes the per-symbol snapshot dict + recent indicator frame and
returns a list of signal dicts. Rule thresholds come from system_config "strategy.params" (DEFAULT_PARAMS below)."""

import math

import pandas as pd

DEFAULT_PARAMS = {
    "breakout_vol_ratio": 1.5,
    "take_profit_ratio": 0.8,
    "take_profit_rsi": 75,
    "take_profit_dist_ma50": 25,
    "distribution_days": 4,
    "pullback_rsi_max": 55,
    "pullback_dist_ma50": [-3, 2],
    "tight_base_tightness": 3.0,
    "tight_base_vol": 0.8,
    "chase_short": 15,
    "chase_mid": 20,
}

STRATEGIES = [
    # code, name, signal_type, horizon, description
    ("BREAKOUT_BASE", "Phá nền kèm khối lượng", "BUY", "MID", "Đóng cửa vượt đỉnh nền ≥ 25 phiên với KL ≥ 1,5 lần TB20"),
    ("BREAKOUT_52W", "Vượt đỉnh 52 tuần", "BUY", "SHORT", "Giá đóng cửa ≥ đỉnh 52 tuần, KL ≥ 1,5 lần TB20"),
    ("GOLDEN_CROSS", "MA50 cắt lên MA200", "BUY", "LONG", "MA50 vừa cắt lên MA200 (trong 3 phiên)"),
    ("MA50_PULLBACK", "Hồi về MA50 trong xu hướng tăng", "BUY", "MID", "Giá về sát MA50 đang dốc lên, RSI 35–55, KL thấp"),
    ("MA50_CROSS_UP", "Giá cắt lên MA50", "BUY", "MID", "Giá cắt lên MA50 khi MA50 > MA200"),
    ("DEATH_CROSS", "MA50 cắt xuống MA200", "SELL", "LONG", "MA50 vừa cắt xuống MA200"),
    ("BREAK_MA50", "Thủng MA50 với khối lượng lớn", "SELL", "MID", "Đóng cửa dưới MA50 với KL ≥ 1,5 lần TB20"),
    ("DISTRIBUTION", "Vào vùng phân phối", "SELL", "MID", "≥ 4 phiên phân phối trong 20 phiên, giá cách MA50 > 10%"),
    ("TAKE_PROFIT", "Tăng đến vùng nên chốt lời", "TAKE_PROFIT", "MID", "Mức tăng từ nền ≥ 80% trung vị các đợt trước, RSI > 75 hoặc cách MA50 > 25%"),
    ("TIGHT_BASE", "Đi nền tốt, có xu hướng tăng", "WATCH", "MID", "Nền chặt (biên độ 10 phiên ≤ 3%), KL cạn, giá trên MA50/MA200"),
    ("SUPPORT_DISCOUNT", "Về hỗ trợ, chiết khấu tốt", "BUY", "LONG", "Giá về MA200/đáy nền cũ, KL giảm, cơ bản tốt, biên an toàn ≥ 20%"),
    ("RSI_DIVERGENCE", "Phân kỳ âm RSI tại đỉnh", "SELL", "SHORT", "Giá lập đỉnh cao hơn nhưng RSI thấp hơn"),
]


def _v(d: dict, k: str, default=None):
    v = d.get(k)
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return default
    return v


def _crossed(series_a: pd.Series, series_b: pd.Series, lookback: int, up: bool = True) -> bool:
    if len(series_a) < lookback + 2:
        return False
    a, b = series_a.iloc[-(lookback + 1) :], series_b.iloc[-(lookback + 1) :]
    diff = (a - b).dropna()
    if len(diff) < 2:
        return False
    if up:
        return bool((diff.iloc[-1] > 0) and (diff.iloc[:-1] <= 0).any())
    return bool((diff.iloc[-1] < 0) and (diff.iloc[:-1] >= 0).any())


def evaluate(snap: dict, ind: pd.DataFrame, rally: dict | None, params: dict | None = None) -> list[dict]:
    """snap: current snapshot fields; ind: last ≥ 60 rows of indicators (ascending). Returns candidate signals."""
    p = {**DEFAULT_PARAMS, **(params or {})}
    out: list[dict] = []
    c = _v(snap, "price")
    if not c or len(ind) < 30:
        return out
    ma50, ma200, rsi = _v(snap, "ma50"), _v(snap, "ma200"), _v(snap, "rsi14", 50)
    vr = _v(snap, "vol_ratio", 1.0)
    dist50 = _v(snap, "dist_ma50_pct", 0)
    trend = snap.get("trend_state") or "FLAT"
    gain = _v(snap, "gain_from_base_pct")
    base_status = snap.get("base_status")
    base_len = _v(snap, "base_length_days", 0)
    tight = _v(snap, "base_tightness")
    close = ind["close"]

    def add(code, **facts):
        out.append({"strategy_code": code, "facts": facts})

    # --- BUY ---
    if base_status == "BROKEN_OUT" and _v(snap, "breakout_days", 99) <= 1 and vr >= p["breakout_vol_ratio"] and base_len >= 25:
        add("BREAKOUT_BASE", base_length_days=base_len, vol_ratio=round(vr, 2), base_high=_v(snap, "base_high"))
    hi52 = _v(snap, "high_52w")
    if hi52 and c >= hi52 * 0.999 and vr >= p["breakout_vol_ratio"] and trend in ("UP", "STRONG_UP"):
        prev_hi = ind["high_52w"].iloc[-2] if "high_52w" in ind and len(ind) > 1 else None
        if prev_hi is None or close.iloc[-2] < prev_hi:
            add("BREAKOUT_52W", high_52w=hi52, vol_ratio=round(vr, 2))
    if "ma50" in ind and "ma200" in ind and _crossed(ind["ma50"], ind["ma200"], 3, up=True):
        add("GOLDEN_CROSS", ma50=ma50, ma200=ma200)
    lo, hi = p["pullback_dist_ma50"]
    if trend in ("UP", "STRONG_UP") and ma50 and lo <= dist50 <= hi and rsi <= p["pullback_rsi_max"] and vr < 1.0 and _v(snap, "ma50_slope", 0) > 0:
        add("MA50_PULLBACK", dist_ma50_pct=round(dist50, 2), rsi14=round(rsi, 1), vol_ratio=round(vr, 2))
    if ma50 and ma200 and ma50 > ma200 and _crossed(close, ind["ma50"], 2, up=True) and vr >= 1.0:
        add("MA50_CROSS_UP", ma50=ma50, vol_ratio=round(vr, 2))
    mos = _v(snap, "margin_of_safety")
    fund_ok = (_v(snap, "roe", 0) >= 12) and (_v(snap, "profit_yoy", 0) > 0)
    near_support = (ma200 and abs(c / ma200 - 1) <= 0.03) or (_v(snap, "support_1") and abs(c / _v(snap, "support_1") - 1) <= 0.03)
    if near_support and vr < 0.9 and fund_ok and mos is not None and mos >= 20 and trend not in ("STRONG_DOWN",):
        add("SUPPORT_DISCOUNT", margin_of_safety=round(mos, 1), roe=_v(snap, "roe"), ma200=ma200)
    # --- WATCH ---
    if base_status == "FORMING" and tight is not None and tight <= p["tight_base_tightness"] and vr <= p["tight_base_vol"] and ma50 and c > ma50 and (not ma200 or c > ma200):
        add("TIGHT_BASE", base_tightness=round(tight, 2), base_length_days=base_len, vol_ratio=round(vr, 2))
    # --- SELL / TAKE PROFIT ---
    if "ma50" in ind and "ma200" in ind and _crossed(ind["ma50"], ind["ma200"], 3, up=False):
        add("DEATH_CROSS", ma50=ma50, ma200=ma200)
    if ma50 and c < ma50 and vr >= p["breakout_vol_ratio"] and close.iloc[-2] >= ind["ma50"].iloc[-2]:
        add("BREAK_MA50", ma50=ma50, vol_ratio=round(vr, 2))
    dd = _v(snap, "distribution_days", 0)
    if dd >= p["distribution_days"] and dist50 > 10:
        add("DISTRIBUTION", distribution_days=int(dd), dist_ma50_pct=round(dist50, 1))
    if rally and rally.get("median_gain_pct") and gain is not None and base_status == "BROKEN_OUT":
        if gain >= p["take_profit_ratio"] * rally["median_gain_pct"] and (rsi > p["take_profit_rsi"] or dist50 > p["take_profit_dist_ma50"] or (rally.get("median_peak_vol_ratio") and vr > rally["median_peak_vol_ratio"])):
            add("TAKE_PROFIT", gain_from_base_pct=round(gain, 1), median_gain_pct=round(rally["median_gain_pct"], 1),
                rally_count=rally.get("rally_count"), rsi14=round(rsi, 1), dist_ma50_pct=round(dist50, 1))
    if "rsi14" in ind and len(ind) >= 30:
        last30 = ind.iloc[-30:]
        i_hi = last30["close"].idxmax()
        if i_hi == last30.index[-1] or (last30["close"].iloc[-1] >= last30["close"].max() * 0.995):
            prev = last30.iloc[:-5]
            if len(prev) > 5:
                j = prev["close"].idxmax()
                if last30["close"].iloc[-1] > prev.loc[j, "close"] and last30["rsi14"].iloc[-1] < prev.loc[j, "rsi14"] - 5 and rsi > 60:
                    add("RSI_DIVERGENCE", rsi_now=round(rsi, 1), rsi_prev=round(float(prev.loc[j, "rsi14"]), 1))
    return out


def is_chase(gain_from_base_pct: float | None, ceiling_streak: int | None, horizon: str, params: dict | None = None) -> bool:
    p = {**DEFAULT_PARAMS, **(params or {})}
    limit = p["chase_short"] if horizon == "SHORT" else p["chase_mid"]
    if ceiling_streak and ceiling_streak >= 2:
        return True
    return gain_from_base_pct is not None and gain_from_base_pct > limit


def signal_title(code: str, symbol: str, snap: dict, facts: dict, horizon: str, rating_vi: str | None) -> str:
    hz = {"SHORT": "Ngắn hạn", "MID": "Trung hạn", "LONG": "Dài hạn"}[horizon]
    body = {
        "BREAKOUT_BASE": f"{symbol} phá nền {facts.get('base_length_days', 0)} phiên với KL gấp {facts.get('vol_ratio', 0):.1f} lần TB20",
        "BREAKOUT_52W": f"{symbol} vượt đỉnh 52 tuần, KL gấp {facts.get('vol_ratio', 0):.1f} lần TB20",
        "GOLDEN_CROSS": f"{symbol}: MA50 cắt lên MA200",
        "MA50_PULLBACK": f"{symbol} hồi về MA50 trong xu hướng tăng, RSI {facts.get('rsi14', 0):.0f}",
        "MA50_CROSS_UP": f"{symbol} cắt lên MA50 khi MA50 > MA200",
        "SUPPORT_DISCOUNT": f"{symbol} về hỗ trợ, biên an toàn {facts.get('margin_of_safety', 0):.0f}%",
        "TIGHT_BASE": f"{symbol} đi nền chặt {facts.get('base_length_days', 0)} phiên, KL cạn",
        "DEATH_CROSS": f"{symbol}: MA50 cắt xuống MA200",
        "BREAK_MA50": f"{symbol} thủng MA50 với KL gấp {facts.get('vol_ratio', 0):.1f} lần TB20",
        "DISTRIBUTION": f"{symbol} vào vùng phân phối: {facts.get('distribution_days', 0)} phiên phân phối/20 phiên",
        "TAKE_PROFIT": f"{symbol} đã tăng {facts.get('gain_from_base_pct', 0):.0f}% từ nền, bằng {facts.get('gain_from_base_pct', 0) / max(facts.get('median_gain_pct', 1), 1) * 100:.0f}% đợt trung bình",
        "RSI_DIVERGENCE": f"{symbol}: phân kỳ âm RSI tại đỉnh",
    }.get(code, f"{symbol}: {code}")
    label = rating_vi or {"SELL": "Bán", "TAKE_PROFIT": "Chốt lời", "WATCH": "Theo dõi", "BUY": "Mua"}.get(
        next((s[2] for s in STRATEGIES if s[0] == code), "BUY"), "Tín hiệu")
    return f"[{label} – {hz}] {body}"

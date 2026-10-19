"""Market regime from VN-Index + breadth (spec M10 'trạng thái thị trường chung', 4.6 n headline)."""

import pandas as pd

REGIME_EQUITY = {"UPTREND": 80, "PRESSURE": 60, "CORRECTION": 40, "DOWNTREND": 20}
REGIME_VI = {"UPTREND": "tăng", "PRESSURE": "chịu áp lực", "CORRECTION": "điều chỉnh", "DOWNTREND": "giảm"}

HEADLINE_TEMPLATES = {
    "UPTREND": "Thị trường tăng, {pct_above_ma50:.0f}% mã trên MA50; ưu tiên mã mạnh, tỷ trọng cổ phiếu tối đa {max_equity_pct}%.",
    "PRESSURE": "Thị trường chịu áp lực, {dist_days} phiên phân phối gần đây; giữ mã mạnh, không mua đuổi, tỷ trọng tối đa {max_equity_pct}%.",
    "CORRECTION": "Thị trường điều chỉnh, VN-Index dưới MA50; ưu tiên bảo vệ vốn, chỉ mua thăm dò, tỷ trọng tối đa {max_equity_pct}%.",
    "DOWNTREND": "Thị trường giảm, VN-Index dưới MA50 và MA200; đứng ngoài, tỷ trọng cổ phiếu tối đa {max_equity_pct}%.",
}


DEFAULT_BREADTH_PARAMS = {"narrow_ma50_pct": 40.0, "new_lows_ratio": 2.0, "new_lows_min": 20, "foreign_sell_days": 5, "foreign_sell_5d_vnd": 1_000_000_000_000}


def classify_regime(index_df: pd.DataFrame, breadth: dict | None = None, params: dict | None = None) -> dict:
    """index_df: VN-Index daily close/volume/value ascending. breadth: {pct_above_ma50, advances, declines, new_highs,
    new_lows, foreign_net_5d, foreign_sell_streak}. Breadth and foreign flows can downgrade UPTREND → PRESSURE
    (index up but fewer stocks participating, or persistent foreign selling): early warning 1–3 weeks before the index."""
    pr = {**DEFAULT_BREADTH_PARAMS, **(params or {})}
    df = index_df.sort_index()
    c = df["close"]
    ma50 = c.rolling(50).mean()
    ma200 = c.rolling(200).mean()
    vol = df["volume"].astype(float) if "volume" in df else None
    value = df["value"] if "value" in df and df["value"].notna().any() else None
    last = c.iloc[-1]
    m50, m200 = ma50.iloc[-1], ma200.iloc[-1]
    prev = c.shift(1)
    dist = ((c < prev * 0.998) & (vol > vol.rolling(20).mean())) if vol is not None else pd.Series(False, index=c.index)
    dist_days = int(dist.iloc[-25:].sum())
    pct50 = (breadth or {}).get("pct_above_ma50")
    ma50_rising = ma50.iloc[-1] > ma50.iloc[-10] if len(ma50.dropna()) > 10 else True

    if pd.isna(m50):
        regime = "UPTREND" if last >= c.iloc[-min(20, len(c))] else "CORRECTION"
    elif last < m50 and (pd.isna(m200) or last < m200):
        regime = "DOWNTREND"
    elif last < m50:
        regime = "CORRECTION"
    elif dist_days >= 5 or (pct50 is not None and pct50 < float(pr["narrow_ma50_pct"])) or not ma50_rising:
        regime = "PRESSURE"
    else:
        regime = "UPTREND"
    b = breadth or {}
    pressure_reasons = []
    nh, nl = b.get("new_highs"), b.get("new_lows")
    if regime == "UPTREND" and nl is not None and nh is not None and nl >= int(pr["new_lows_min"]) and nl >= float(pr["new_lows_ratio"]) * max(nh, 1):
        regime = "PRESSURE"
        pressure_reasons.append(f"{nl} mã lập đáy 52 tuần so với {nh} mã lập đỉnh")
    fs, fn = b.get("foreign_sell_streak"), b.get("foreign_net_5d")
    if regime == "UPTREND" and fs is not None and fn is not None and fs >= int(pr["foreign_sell_days"]) and fn <= -float(pr["foreign_sell_5d_vnd"]):
        regime = "PRESSURE"
        pressure_reasons.append(f"khối ngoại bán ròng {fs} phiên liên tiếp ({abs(fn) / 1e9:,.0f} tỷ trong 5 phiên)".replace(",", "."))
    elif fs is not None and fn is not None and fs >= int(pr["foreign_sell_days"]) and fn <= -float(pr["foreign_sell_5d_vnd"]):
        pressure_reasons.append(f"khối ngoại bán ròng {fs} phiên liên tiếp ({abs(fn) / 1e9:,.0f} tỷ trong 5 phiên)".replace(",", "."))
    if pct50 is not None and pct50 < float(pr["narrow_ma50_pct"]) and regime in ("PRESSURE", "UPTREND"):
        pressure_reasons.append(f"chỉ {pct50:.0f}% mã trên MA50")
    liq = None
    if value is not None and value.rolling(20).mean().iloc[-1]:
        liq = float(value.iloc[-1] / value.rolling(20).mean().iloc[-1])
    elif vol is not None and vol.rolling(20).mean().iloc[-1]:
        liq = float(vol.iloc[-1] / vol.rolling(20).mean().iloc[-1])
    change_pct = float((last / prev.iloc[-1] - 1) * 100) if len(c) > 1 else 0.0
    facts = {
        "regime": regime,
        "regime_vi": REGIME_VI[regime],
        "max_equity_pct": REGIME_EQUITY[regime],
        "vnindex": round(float(last), 2),
        "vnindex_change_pct": round(change_pct, 2),
        "above_ma50": bool(last > m50) if not pd.isna(m50) else None,
        "above_ma200": bool(last > m200) if not pd.isna(m200) else None,
        "dist_days": dist_days,
        "liquidity_ratio": round(liq, 2) if liq else None,
        "pct_above_ma50": pct50,
        "advances": b.get("advances"),
        "declines": b.get("declines"),
        "new_highs": nh, "new_lows": nl, "foreign_net_5d": fn, "foreign_sell_streak": fs,
        "pressure_reasons": pressure_reasons,
    }
    headline = HEADLINE_TEMPLATES[regime].format(**{**facts, "pct_above_ma50": pct50 or 0})
    if pressure_reasons:
        headline += " Dấu hiệu sớm: " + "; ".join(pressure_reasons) + "."
    facts["headline_rule"] = headline
    return facts

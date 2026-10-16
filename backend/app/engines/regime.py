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


def classify_regime(index_df: pd.DataFrame, breadth: dict | None = None) -> dict:
    """index_df: VN-Index daily close/volume/value ascending. breadth: {pct_above_ma50, advances, declines}."""
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
    elif dist_days >= 5 or (pct50 is not None and pct50 < 40) or not ma50_rising:
        regime = "PRESSURE"
    else:
        regime = "UPTREND"
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
        "advances": (breadth or {}).get("advances"),
        "declines": (breadth or {}).get("declines"),
    }
    headline = HEADLINE_TEMPLATES[regime].format(**{**facts, "pct_above_ma50": pct50 or 0})
    facts["headline_rule"] = headline
    return facts

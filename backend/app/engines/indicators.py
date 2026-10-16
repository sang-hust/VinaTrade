"""Technical indicator engine (pure pandas/numpy). Input: daily OHLCV DataFrame indexed by trade_date, ascending."""

import numpy as np
import pandas as pd

OUTPUT_COLS = [
    "close", "change_pct", "ma10", "ma20", "ma50", "ma200", "ema12", "ema26", "rsi14", "macd", "macd_signal",
    "macd_hist", "adx14", "atr14", "bb_upper", "bb_lower", "bb_width", "obv", "mfi14", "cmf20", "stoch_k", "stoch_d",
    "vol_ma20", "vol_ratio", "value_ma20", "support_1", "resistance_1", "high_52w", "low_52w", "dist_ma50_pct",
    "ma50_slope", "ma200_slope", "ceiling_streak", "distribution_days", "trend_state",
]


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def _rma(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0)
    dn = -d.clip(upper=0)
    rs = _rma(up, n) / _rma(dn, n).replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    return _rma(tr, n)


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up = df["high"].diff()
    dn = -df["low"].diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = atr(df, n)
    plus_di = 100 * _rma(pd.Series(plus_dm, index=df.index), n) / tr
    minus_di = 100 * _rma(pd.Series(minus_dm, index=df.index), n) / tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return _rma(dx, n)


def mfi(df: pd.DataFrame, n: int = 14) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    mf = tp * df["volume"]
    pos = mf.where(tp > tp.shift(1), 0.0).rolling(n).sum()
    neg = mf.where(tp < tp.shift(1), 0.0).rolling(n).sum()
    return 100 - 100 / (1 + pos / neg.replace(0, np.nan))


def cmf(df: pd.DataFrame, n: int = 20) -> pd.Series:
    hl = (df["high"] - df["low"]).replace(0, np.nan)
    mfm = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / hl
    return (mfm * df["volume"]).rolling(n).sum() / df["volume"].rolling(n).sum().replace(0, np.nan)


def stochastic(df: pd.DataFrame, n: int = 14, d: int = 3) -> tuple[pd.Series, pd.Series]:
    lo = df["low"].rolling(n).min()
    hi = df["high"].rolling(n).max()
    k = 100 * (df["close"] - lo) / (hi - lo).replace(0, np.nan)
    return k, k.rolling(d).mean()


def pivots(df: pd.DataFrame, lookback: int = 60, wing: int = 5) -> tuple[pd.Series, pd.Series]:
    """Nearest swing-low support below price and swing-high resistance above price, from the last `lookback` sessions."""
    close, high, low = df["close"], df["high"], df["low"]
    is_high = (high == high.rolling(2 * wing + 1, center=True).max())
    is_low = (low == low.rolling(2 * wing + 1, center=True).min())
    sup = pd.Series(np.nan, index=df.index)
    res = pd.Series(np.nan, index=df.index)
    highs = high.where(is_high)
    lows = low.where(is_low)
    for i in range(len(df)):
        if i < wing + 5:
            continue
        c = close.iloc[i]
        start = max(0, i - lookback)
        window_l = lows.iloc[start : i - wing + 1].dropna()
        window_h = highs.iloc[start : i - wing + 1].dropna()
        below = window_l[window_l < c]
        above = window_h[window_h > c]
        sup.iloc[i] = below.max() if len(below) else low.iloc[start : i + 1].min()
        res.iloc[i] = above.min() if len(above) else high.iloc[start : i + 1].max()
    return sup, res


def trend_state(row: pd.Series) -> str | None:
    c, m10, m50, m200, adx_v, slope200 = row.get("close"), row.get("ma10"), row.get("ma50"), row.get("ma200"), row.get("adx14"), row.get("ma200_slope")
    macd_v, sig = row.get("macd"), row.get("macd_signal")
    if pd.isna(m50):
        return None
    if pd.isna(m200):
        # young listing: use MA50 only
        if c > m50 and (pd.isna(macd_v) or macd_v >= sig):
            return "UP"
        if c < m50:
            return "DOWN"
        return "FLAT"
    if c > m10 > m50 > m200 and (slope200 or 0) > 0 and (adx_v or 0) > 25:
        return "STRONG_UP"
    if c > m50 > m200 and (pd.isna(macd_v) or macd_v >= sig):
        return "UP"
    if c < m10 < m50 < m200 and (slope200 or 0) < 0:
        return "STRONG_DOWN"
    if c < m50 < m200 and (pd.isna(macd_v) or macd_v <= sig):
        return "DOWN"
    return "FLAT"


def compute_indicators(df: pd.DataFrame, exchange: str = "HOSE", pivot_tail: int = 420) -> pd.DataFrame:
    """df columns: open, high, low, close, volume, value (optional). Returns a frame with OUTPUT_COLS."""
    df = df.sort_index().copy()
    df = df[~df.index.duplicated(keep="last")]
    out = pd.DataFrame(index=df.index)
    c, v = df["close"], df["volume"].astype(float)
    out["close"] = c
    out["change_pct"] = c.pct_change() * 100
    for n in (10, 20, 50, 200):
        out[f"ma{n}"] = c.rolling(n).mean()
    out["ema12"], out["ema26"] = _ema(c, 12), _ema(c, 26)
    out["rsi14"] = rsi(c)
    out["macd"] = out["ema12"] - out["ema26"]
    out["macd_signal"] = _ema(out["macd"], 9)
    out["macd_hist"] = out["macd"] - out["macd_signal"]
    out["adx14"] = adx(df)
    out["atr14"] = atr(df)
    std20 = c.rolling(20).std()
    out["bb_upper"], out["bb_lower"] = out["ma20"] + 2 * std20, out["ma20"] - 2 * std20
    out["bb_width"] = (out["bb_upper"] - out["bb_lower"]) / out["ma20"] * 100
    out["obv"] = (np.sign(c.diff()).fillna(0) * v).cumsum()
    out["mfi14"] = mfi(df)
    out["cmf20"] = cmf(df)
    out["stoch_k"], out["stoch_d"] = stochastic(df)
    out["vol_ma20"] = v.rolling(20).mean()
    out["vol_ratio"] = v / out["vol_ma20"].replace(0, np.nan)
    value = df["value"] if "value" in df and df["value"].notna().any() else c * v
    out["value_ma20"] = value.rolling(20).mean()
    if len(df) > pivot_tail + 80:
        sup, res = pivots(df.iloc[-(pivot_tail + 80):])
        out["support_1"] = sup.reindex(df.index)
        out["resistance_1"] = res.reindex(df.index)
    else:
        out["support_1"], out["resistance_1"] = pivots(df)
    out["high_52w"] = df["high"].rolling(250, min_periods=20).max()
    out["low_52w"] = df["low"].rolling(250, min_periods=20).min()
    out["dist_ma50_pct"] = (c / out["ma50"] - 1) * 100
    out["ma50_slope"] = (out["ma50"] / out["ma50"].shift(10) - 1) * 100
    out["ma200_slope"] = (out["ma200"] / out["ma200"].shift(20) - 1) * 100
    # ceiling streak: consecutive sessions closing at/near the daily limit
    limit = {"HOSE": 0.07, "HNX": 0.10, "UPCOM": 0.15}.get(exchange, 0.07)
    at_ceiling = (c / c.shift(1) - 1) >= limit * 0.97
    streak = np.zeros(len(c), dtype=int)
    for i in range(1, len(c)):
        streak[i] = streak[i - 1] + 1 if bool(at_ceiling.iloc[i]) else 0
    out["ceiling_streak"] = streak
    # distribution days (spec 4.6c) over the last 20 sessions
    prev = c.shift(1)
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    close_pos = (c - df["low"]) / rng
    dist = ((c < prev * 0.998) & (v > out["vol_ma20"])) | (
        ((c / prev - 1).abs() < 0.005) & (v > 1.5 * out["vol_ma20"]) & (close_pos < 0.4)
    )
    out["distribution_days"] = dist.astype(int).rolling(20).sum()
    out["trend_state"] = out.apply(trend_state, axis=1)
    return out[OUTPUT_COLS]


def rs_ratings(perf: pd.Series) -> pd.Series:
    """Percentile rank 1–99 of a cross-sectional performance series (index = symbol)."""
    r = perf.rank(pct=True) * 98 + 1
    return r.round(0)


def weighted_performance(close: pd.Series) -> float | None:
    """IBD-style RS raw: 40% 3m + 20% 6m + 20% 9m + 20% 12m price change."""
    if len(close) < 70:
        return None

    def ret(n: int) -> float:
        if len(close) <= n:
            n = len(close) - 1
        return close.iloc[-1] / close.iloc[-1 - n] - 1

    return 0.4 * ret(63) + 0.2 * ret(126) + 0.2 * ret(189) + 0.2 * ret(250)

"""Price-base (consolidation) and rally detection — spec 4.6 a/b. Pure pandas, no DB."""

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

DEFAULTS = {
    "min_length": 25,
    "max_depth": 0.35,
    "pivot_wing": 10,
    "breakout_vol_ratio": 1.5,
    "rally_end_drawdown": 0.15,
    "max_length": 300,
}


@dataclass
class BaseInfo:
    start_date: date
    end_date: date | None
    base_high: float
    base_low: float
    depth_pct: float
    length_days: int
    tightness_pct: float | None
    vol_dry_ratio: float | None
    avg_volume: float | None
    pattern: str
    status: str
    breakout_date: date | None = None
    breakout_vol_ratio: float | None = None


@dataclass
class RallyInfo:
    start_date: date
    base_high: float
    peak_date: date | None
    end_date: date | None
    peak_price: float | None
    gain_pct: float | None
    days_to_peak: int | None
    peak_vol_ratio: float | None
    distribution_days: int | None
    pullback_pct: float | None
    status: str
    base_index: int = field(default=-1)


def _classify(window: pd.DataFrame, base_high: float, base_low: float) -> str:
    close = window["close"]
    n = len(close)
    if n < 15:
        return "FLAT"
    lows = window["low"]
    # VCP: contracting ranges across thirds
    thirds = np.array_split(close, 3)
    ranges = [t.max() - t.min() for t in thirds if len(t)]
    if len(ranges) == 3 and ranges[0] > ranges[1] > ranges[2] and ranges[2] < 0.5 * ranges[0]:
        return "VCP"
    # double bottom: two lows within 3% separated by a bounce ≥ 8%
    mins_idx = lows.nsmallest(2).index
    if len(mins_idx) == 2:
        i1, i2 = sorted(window.index.get_loc(i) for i in mins_idx)
        if i2 - i1 >= 8 and abs(lows.iloc[i1] / lows.iloc[i2] - 1) < 0.03:
            mid = close.iloc[i1:i2].max()
            if mid / min(lows.iloc[i1], lows.iloc[i2]) - 1 >= 0.08:
                return "DOUBLE_BOTTOM"
    # cup with handle: low in the middle third, recent small dip (handle) near the rim
    low_pos = int(np.argmin(lows.values)) / n
    if 0.3 <= low_pos <= 0.7:
        handle = close.iloc[-max(5, n // 6) :]
        if handle.min() > base_low + 0.6 * (base_high - base_low) and handle.max() < base_high * 1.01:
            return "CUP_HANDLE"
    return "FLAT"


def detect_bases(df: pd.DataFrame, params: dict | None = None) -> tuple[list[BaseInfo], list[RallyInfo]]:
    """Scan the full adjusted history. Returns completed/forming bases and the rallies that followed breakouts."""
    p = {**DEFAULTS, **(params or {})}
    df = df.sort_index()
    if len(df) < p["min_length"] + p["pivot_wing"] + 5:
        return [], []
    high, low, close, vol = df["high"], df["low"], df["close"], df["volume"].astype(float)
    vol_ma50 = vol.rolling(50, min_periods=10).mean()
    vol_ma20 = vol.rolling(20, min_periods=5).mean()
    w = p["pivot_wing"]
    pivot_high = high == high.rolling(2 * w + 1, center=True).max()
    idx = df.index
    bases: list[BaseInfo] = []
    rallies: list[RallyInfo] = []
    i = w
    n = len(df)
    while i < n - 1:
        if not bool(pivot_high.iloc[i]):
            i += 1
            continue
        H = float(high.iloc[i])
        # walk forward from the pivot until breakout (close > H with volume) or failure (depth too big / too long)
        j = i + 1
        status, breakout_j = "FORMING", None
        while j < n:
            depth = (H - float(low.iloc[i : j + 1].min())) / H
            if depth > p["max_depth"] or j - i > p["max_length"]:
                status = "FAILED"
                break
            if float(close.iloc[j]) > H and (j - i) >= p["min_length"]:
                vr = float(vol.iloc[j] / vol_ma20.iloc[j]) if vol_ma20.iloc[j] and not np.isnan(vol_ma20.iloc[j]) else 0.0
                if vr >= p["breakout_vol_ratio"]:
                    status, breakout_j = "BROKEN_OUT", j
                    break
                # weak breakout → treat as failed base, resume scan from here
                status = "FAILED"
                break
            if float(high.iloc[j]) > H * 1.02 and (j - i) < p["min_length"]:
                status = "FAILED"  # new high before a real base formed
                break
            j += 1
        length = min(j, n - 1) - i
        if status == "FAILED" and length < p["min_length"]:
            i += 1
            continue
        window = df.iloc[i : min(j, n - 1) + 1]
        base_low = float(window["low"].min())
        last10 = window["close"].iloc[-10:]
        tight = float(last10.std() / last10.mean() * 100) if len(last10) >= 5 else None
        vdry = float(window["volume"].iloc[-10:].mean() / vol_ma50.iloc[min(j, n - 1)]) if vol_ma50.iloc[min(j, n - 1)] else None
        info = BaseInfo(
            start_date=idx[i].date() if hasattr(idx[i], "date") else idx[i],
            end_date=(idx[min(j, n - 1)].date() if hasattr(idx[0], "date") else idx[min(j, n - 1)]) if status != "FORMING" else None,
            base_high=H,
            base_low=base_low,
            depth_pct=round((H - base_low) / H * 100, 2),
            length_days=int(length),
            tightness_pct=round(tight, 2) if tight is not None else None,
            vol_dry_ratio=round(vdry, 2) if vdry is not None else None,
            avg_volume=float(window["volume"].mean()),
            pattern=_classify(window, H, base_low),
            status=status,
        )
        if status == "BROKEN_OUT" and breakout_j is not None:
            info.breakout_date = idx[breakout_j].date() if hasattr(idx[0], "date") else idx[breakout_j]
            info.breakout_vol_ratio = round(float(vol.iloc[breakout_j] / vol_ma20.iloc[breakout_j]), 2)
            # rally after breakout
            k = breakout_j
            peak_k, peak = k, float(close.iloc[k])
            end_k = None
            ma50 = close.rolling(50).mean()
            while k < n:
                ck = float(close.iloc[k])
                if ck > peak:
                    peak, peak_k = ck, k
                if k > breakout_j + 3 and (ck < peak * (1 - p["rally_end_drawdown"]) or (not np.isnan(ma50.iloc[k]) and ck < ma50.iloc[k])):
                    end_k = k
                    break
                k += 1
            lo_k, hi_k = max(0, peak_k - 3), min(n, peak_k + 4)
            base_avg_vol = info.avg_volume or 1.0
            prev = close.shift(1)
            dist_window = df.iloc[max(breakout_j, peak_k - 20) : peak_k + 1]
            dist_days = int(((dist_window["close"] < prev.loc[dist_window.index] * 0.998) & (dist_window["volume"] > vol_ma20.loc[dist_window.index])).sum())
            rallies.append(
                RallyInfo(
                    start_date=info.breakout_date,
                    base_high=H,
                    peak_date=idx[peak_k].date() if hasattr(idx[0], "date") else idx[peak_k],
                    end_date=(idx[end_k].date() if hasattr(idx[0], "date") else idx[end_k]) if end_k is not None else None,
                    peak_price=peak,
                    gain_pct=round((peak / H - 1) * 100, 2),
                    days_to_peak=int(peak_k - breakout_j),
                    peak_vol_ratio=round(float(vol.iloc[lo_k:hi_k].mean() / base_avg_vol), 2),
                    distribution_days=dist_days,
                    pullback_pct=round((1 - float(close.iloc[end_k]) / peak) * 100, 2) if end_k is not None else None,
                    status="COMPLETED" if end_k is not None else "ONGOING",
                    base_index=len(bases),
                )
            )
            bases.append(info)
            i = (end_k if end_k is not None else n) + 1 if end_k is not None else n
            continue
        bases.append(info)
        i = j if status == "FAILED" else n
    return bases, rallies


def rally_stats(rallies: list[RallyInfo]) -> dict | None:
    done = [r for r in rallies if r.status == "COMPLETED" and r.gain_pct is not None]
    if len(done) < 3:
        return {"rally_count": len(done)} if done else None
    gains = np.array([r.gain_pct for r in done])
    days = np.array([r.days_to_peak for r in done if r.days_to_peak is not None])
    pv = np.array([r.peak_vol_ratio for r in done if r.peak_vol_ratio is not None])
    pb = np.array([r.pullback_pct for r in done if r.pullback_pct is not None])
    return {
        "rally_count": len(done),
        "median_gain_pct": float(np.median(gains)),
        "p75_gain_pct": float(np.percentile(gains, 75)),
        "mean_gain_pct": float(gains.mean()),
        "median_days": float(np.median(days)) if len(days) else None,
        "median_peak_vol_ratio": float(np.median(pv)) if len(pv) else None,
        "median_pullback_pct": float(np.median(pb)) if len(pb) else None,
    }

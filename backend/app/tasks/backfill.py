"""Historical signal backfill (strategy backtest, BR-12 / 4.6k): replay the live strategies over past sessions,
compute outcomes after 5/10/20/60 sessions from the price history and refresh reliability tables.

python -m app.tasks.backfill --years 4 [--symbols FPT,HPG]"""

import argparse
import asyncio
import logging
import math
import time
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_scope
from app.engines import strategies as strat
from app.engines.bases import detect_bases, rally_stats
from app.engines.indicators import compute_indicators
from app.engines.scoring import trade_plan
from app.models import IndexDaily, Signal, SignalOutcome, Stock, Strategy
from app.services.sysconfig import get_config
from app.tasks.eod import _load_prices, refresh_reliability

log = logging.getLogger(__name__)


def regime_series(idx: pd.DataFrame) -> pd.Series:
    c = idx["close"]
    ma50, ma200 = c.rolling(50).mean(), c.rolling(200).mean()
    vol = idx["volume"].astype(float).fillna(0)
    prev = c.shift(1)
    dist = ((c < prev * 0.998) & (vol > vol.rolling(20).mean())).astype(int).rolling(25).sum()
    rising = ma50 > ma50.shift(10)
    out = pd.Series("UPTREND", index=c.index)
    out[(c < ma50) & (c < ma200)] = "DOWNTREND"
    out[(c < ma50) & ~(c < ma200)] = "CORRECTION"
    out[(c >= ma50) & ((dist >= 5) | ~rising)] = "PRESSURE"
    return out


def outcomes_for(df: pd.DataFrame, t: int, price: float, stop: float | None, tp1: float | None, signal_type: str) -> list[dict]:
    out = []
    highs, lows, closes = df["high"].values, df["low"].values, df["close"].values
    for days in (5, 10, 20, 60):
        if t + days >= len(df):
            break
        h, lo, c = highs[t + 1 : t + 1 + days], lows[t + 1 : t + 1 + days], closes[t + days]
        ret = (c / price - 1) * 100
        hit_tp = bool(tp1 and (h >= tp1).any())
        hit_sl = bool(stop and (lo <= stop).any())
        if hit_tp and hit_sl:
            ft, fs = int(np.argmax(h >= tp1)), int(np.argmax(lo <= stop))
            hit_tp, hit_sl = ft <= fs, fs < ft
        if signal_type in ("SELL", "TAKE_PROFIT"):
            result = "WIN" if ret < 0 else "LOSS"
        else:
            result = "TP_HIT" if hit_tp else ("STOP_HIT" if hit_sl else ("WIN" if ret > 0 else "LOSS"))
        out.append({"days": days, "return_pct": round(float(ret), 2), "max_gain_pct": round(float(h.max() / price * 100 - 100), 2), "max_loss_pct": round(float(lo.min() / price * 100 - 100), 2),
                    "hit_tp1": hit_tp, "hit_stop": hit_sl, "result": result})
    return out


async def backfill(db: AsyncSession, years: int = 4, symbols: list[str] | None = None, min_liq: float = 5e9) -> dict:
    stocks = (await db.execute(select(Stock).where(Stock.is_active))).scalars().all()
    if symbols:
        stocks = [s for s in stocks if s.symbol in set(symbols)]
    params = await get_config(db, "strategy.params")
    base_params = await get_config(db, "base.params")
    enabled = {s.code: s for s in (await db.execute(select(Strategy).where(Strategy.enabled))).scalars()}
    idx_rows = (await db.execute(select(IndexDaily).where(IndexDaily.index_code == "VNINDEX").order_by(IndexDaily.trade_date))).scalars().all()
    idx = pd.DataFrame([{"d": r.trade_date, "close": r.close, "volume": r.volume or 0} for r in idx_rows]).set_index("d")
    regimes = regime_series(idx)
    start_date = date(date.today().year - years, 1, 1)
    existing = {k for (k,) in (await db.execute(select(Signal.dedupe_key).where(Signal.trade_date >= start_date))).all()}
    n_sig = n_out = 0
    t0 = time.time()
    syms = [s.symbol for s in stocks]
    for bi in range(0, len(syms), 60):
        batch = syms[bi : bi + 60]
        frames = await _load_prices(db, batch)
        sig_rows, out_rows = [], []
        for sym, df in frames.items():
            if len(df) < 260:
                continue
            st = next(s for s in stocks if s.symbol == sym)
            ind = compute_indicators(df, st.exchange, pivot_tail=len(df))
            bases, rallies = detect_bases(df, base_params)
            closes = df["close"]
            dates = [d.date() for d in df.index]
            start_i = max(250, next((i for i, d in enumerate(dates) if d >= start_date), len(dates)))
            ind_small = ind[["close", "ma50", "ma200", "rsi14", "high_52w"]]
            for t in range(start_i, len(df) - 1):
                row = ind.iloc[t]
                if (row.value_ma20 or 0) < min_liq or math.isnan(row.ma50 or np.nan):
                    continue
                dt = dates[t]
                # base state at dt
                b_status = b_len = b_tight = b_high = gain = None
                breakout_days = 99
                for b in bases:
                    if b.start_date <= dt and (b.end_date is None or dt <= (b.end_date if b.status == "FORMING" else (b.breakout_date or b.end_date))):
                        b_status, b_len, b_tight, b_high = ("FORMING" if (b.breakout_date is None or dt < b.breakout_date) else "BROKEN_OUT"), min(b.length_days, (dt - b.start_date).days * 5 // 7), b.tightness_pct, b.base_high
                        if b.breakout_date and dt >= b.breakout_date:
                            breakout_days = (dt - b.breakout_date).days
                            gain = (row.close / b.base_high - 1) * 100
                        break
                    if b.breakout_date and b.breakout_date <= dt and (b.end_date is None or dt <= b.end_date):
                        pass
                # rallies completed before dt
                done = [r for r in rallies if r.status == "COMPLETED" and r.end_date and r.end_date < dt]
                rl = rally_stats(done) if len(done) >= 3 else None
                snap = {"price": row.close, "ma50": row.ma50, "ma200": row.ma200, "rsi14": row.rsi14, "vol_ratio": row.vol_ratio, "dist_ma50_pct": row.dist_ma50_pct,
                        "trend_state": row.trend_state, "ma50_slope": row.ma50_slope, "high_52w": row.high_52w, "distribution_days": row.distribution_days,
                        "ceiling_streak": row.ceiling_streak, "support_1": row.support_1, "base_status": b_status, "base_length_days": b_len, "base_tightness": b_tight,
                        "base_high": b_high, "gain_from_base_pct": gain, "breakout_days": breakout_days, "roe": None, "profit_yoy": None, "margin_of_safety": None}
                cands = strat.evaluate(snap, ind_small.iloc[max(0, t - 65) : t + 1], rl, params)
                if not cands:
                    continue
                regime = regimes.get(dt, "UPTREND")
                plan = trade_plan(row.close, row.atr14, row.support_1, row.resistance_1, st.exchange, 7.0, b_high if b_status == "BROKEN_OUT" else None)
                for c in cands:
                    code = c["strategy_code"]
                    s = enabled.get(code)
                    if not s:
                        continue
                    key = f"{sym}:{code}:{dt.isoformat()}"
                    if key in existing:
                        continue
                    existing.add(key)
                    is_chase = s.signal_type == "BUY" and strat.is_chase(gain, row.ceiling_streak, s.horizon, params)
                    sig_rows.append({"symbol": sym, "trade_date": dt, "strategy_code": code, "signal_type": s.signal_type, "horizon": s.horizon, "price": float(row.close),
                                     "entry_low": plan.get("entry_low"), "entry_high": plan.get("entry_high"), "stop_loss": plan.get("stop_loss"), "take_profit_1": plan.get("take_profit_1"),
                                     "take_profit_2": plan.get("take_profit_2"), "risk_reward": plan.get("risk_reward"), "priority": "INFO", "regime_at_signal": regime, "stand_aside": False,
                                     "is_chase": is_chase, "title": strat.signal_title(code, sym, snap, c["facts"], s.horizon, None), "facts": c["facts"], "dedupe_key": key,
                                     "_outs": outcomes_for(df, t, float(row.close), plan.get("stop_loss"), plan.get("take_profit_1"), s.signal_type)})
        # bulk insert signals then outcomes
        for i in range(0, len(sig_rows), 500):
            chunk = sig_rows[i : i + 500]
            vals = [{k: v for k, v in r.items() if k != "_outs"} for r in chunk]
            res = await db.execute(insert(Signal).values(vals).on_conflict_do_nothing(index_elements=["dedupe_key"]).returning(Signal.id, Signal.dedupe_key))
            ids = {k: sid for sid, k in res.all()}
            for r in chunk:
                sid = ids.get(r["dedupe_key"])
                if sid:
                    for o in r["_outs"]:
                        out_rows.append({"signal_id": sid, **o})
            n_sig += len(ids)
        for i in range(0, len(out_rows), 1000):
            await db.execute(insert(SignalOutcome).values(out_rows[i : i + 1000]).on_conflict_do_nothing(index_elements=["signal_id", "days"]))
        n_out += len(out_rows)
        await db.commit()
        log.warning("backfill %d/%d symbols, signals=%d outcomes=%d, %.0fs", min(bi + 60, len(syms)), len(syms), n_sig, n_out, time.time() - t0)
    rel = await refresh_reliability(db)
    await db.commit()
    return {"signals": n_sig, "outcomes": n_out, "reliability_rows": rel, "seconds": int(time.time() - t0)}


async def _main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=4)
    ap.add_argument("--symbols", type=str, default="")
    a = ap.parse_args()
    async with session_scope() as db:
        r = await backfill(db, a.years, [s.strip().upper() for s in a.symbols.split(",") if s.strip()] or None)
    print(r)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(_main())


_ = desc

"""Stop / take-profit placement study (4b): replay the stored BUY signals with alternative stop rules and the realistic
simulation, then rank the rules by least risk (expectancy, stop-hit share, 5th-percentile loss).

python -m app.tasks.stop_study [--years 4] [--days 20] [--top 15]"""

import argparse
import asyncio
import itertools
import time
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select

from app.core.db import session_scope
from app.engines.scoring import plan_levels
from app.engines.simulate import simulate_trade, slippage_for
from app.models import Signal, Stock
from app.tasks.backfill import sim_params
from app.tasks.eod import _load_prices

GRID = {"atr_mult": [1.5, 2.0, 2.5, 3.0], "stop_floor_pct": [5.0, 7.0, 8.0, 10.0], "stop_cap_pct": [12.0, 15.0], "use_support": [True, False], "tp_rr": [1.5, 2.0, 2.5]}


async def load_cases(db, years: int) -> tuple[list[dict], dict[str, pd.DataFrame]]:
    """Stored BUY signals with the indicator row at the signal date, computed on the fly from prices (indicators_daily
    only keeps ~300 sessions; the study needs the whole history)."""
    from app.engines.indicators import compute_indicators

    since = date(date.today().year - years, 1, 1)
    sigs = (await db.execute(select(Signal).where(Signal.signal_type == "BUY", Signal.trade_date >= since).order_by(Signal.symbol, Signal.trade_date))).scalars().all()
    syms = sorted({s.symbol for s in sigs})
    ex = dict((await db.execute(select(Stock.symbol, Stock.exchange).where(Stock.symbol.in_(syms)))).all())
    frames, cases = {}, []
    by_sym: dict[str, list] = {}
    for s in sigs:
        by_sym.setdefault(s.symbol, []).append(s)
    for i in range(0, len(syms), 60):
        batch = syms[i : i + 60]
        fr = await _load_prices(db, batch)
        for sym, df in fr.items():
            if len(df) < 260:
                continue
            frames[sym] = df
            ind = compute_indicators(df, ex.get(sym, "HOSE"), pivot_tail=len(df))
            for s in by_sym.get(sym, []):
                pos = df.index.searchsorted(pd.Timestamp(s.trade_date))
                if pos >= len(df) or df.index[pos].date() != s.trade_date:
                    continue
                r = ind.iloc[pos]
                cases.append({"symbol": sym, "t": int(pos), "close": float(s.price), "atr": r.atr14, "support": r.support_1, "resistance": r.resistance_1, "exchange": ex.get(sym, "HOSE"),
                              "value_ma20": r.value_ma20, "old_stop": s.stop_loss, "old_tp": s.take_profit_1, "regime": s.regime_at_signal, "strategy": s.strategy_code, "date": s.trade_date})
    return cases, frames


def evaluate(cases: list[dict], frames: dict, rule: dict | None, days: int, sim: dict) -> dict:
    rets, stops, tps = [], 0, 0
    for c in cases:
        df = frames[c["symbol"]]
        if rule is None:
            stop, tp = c["old_stop"], c["old_tp"]
        else:
            lv = plan_levels(c["close"], c["atr"], c["support"], c["resistance"], rule)
            stop, tp = lv["stop"], lv["tp1"]
        r = simulate_trade(df["open"].values, df["high"].values, df["low"].values, df["close"].values, c["t"], stop, tp, "BUY", days,
                           fee_pct=sim["fee_pct"], tax_pct=sim["tax_pct"], settlement_sessions=sim["settlement_sessions"], slippage_pct=slippage_for(sim["order_value_vnd"], c["value_ma20"]))
        if r is None:
            continue
        rets.append(r["return_pct"])
        stops += r["hit_stop"]
        tps += r["hit_tp1"]
    a = np.array(rets)
    n = len(a)
    if n == 0:
        return {}
    wins = a[a > 0]
    losses = a[a <= 0]
    return {"n": n, "win_rate": round((a > 0).mean() * 100, 1), "expectancy": round(a.mean(), 2), "stop_rate": round(stops / n * 100, 1), "tp_rate": round(tps / n * 100, 1),
            "p05": round(float(np.percentile(a, 5)), 2), "avg_win": round(float(wins.mean()), 2) if len(wins) else 0.0, "avg_loss": round(float(losses.mean()), 2) if len(losses) else 0.0,
            "profit_factor": round(float(wins.sum() / -losses.sum()), 2) if len(losses) and losses.sum() < 0 else None}


async def run(years: int, days: int, top: int) -> list[dict]:
    t0 = time.time()
    async with session_scope() as db:
        sim = await sim_params(db)
        cases, frames = await load_cases(db, years)
    print(f"{len(cases)} tín hiệu mua, {len(frames)} mã, nạp {time.time() - t0:.0f}s")
    rows = [{"rule": "HIỆN TẠI (đã lưu)", **evaluate(cases, frames, None, days, sim)}]
    for combo in itertools.product(*GRID.values()):
        rule = dict(zip(GRID.keys(), combo, strict=False))
        rows.append({"rule": rule, **evaluate(cases, frames, rule, days, sim)})
    rows.sort(key=lambda r: (-(r.get("expectancy") or -99), r.get("stop_rate") or 99))
    print(f"{'quy tắc':<78} {'n':>5} {'đúng%':>6} {'kỳ vọng':>8} {'cắt lỗ%':>8} {'chốt%':>6} {'p05':>7} {'PF':>5}")
    for r in rows[:top] + [x for x in rows if x["rule"] == "HIỆN TẠI (đã lưu)"]:
        print(f"{r['rule']!s:<78} {r['n']:>5} {r['win_rate']:>6} {r['expectancy']:>8} {r['stop_rate']:>8} {r['tp_rate']:>6} {r['p05']:>7} {r['profit_factor']!s:>5}")
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=4)
    ap.add_argument("--days", type=int, default=20)
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args()
    asyncio.run(run(a.years, a.days, a.top))

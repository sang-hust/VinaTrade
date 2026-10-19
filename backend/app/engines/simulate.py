"""Realistic trade simulation for signal outcomes (backtest and live evaluation share this):
buy at the NEXT session's open (+ slippage), earliest exit after T+2 settlement, stop / take-profit executed at the
open when the session gaps through the level, fees + sell tax, time exit at the close after `days` sessions.
Pure numpy over OHLC arrays — no DB."""

from __future__ import annotations

import numpy as np

HOLD_DAYS = (5, 10, 20, 60)


def simulate_trade(opens, highs, lows, closes, t: int, stop: float | None, tp1: float | None, signal_type: str, days: int,
                   fee_pct: float = 0.15, tax_pct: float = 0.1, slippage_pct: float = 0.3, settlement_sessions: int = 2) -> dict | None:
    """Arrays are ascending sessions; t = signal session index. Returns None when the window is incomplete."""
    e = t + 1  # entry session: next open
    last = e + days  # time exit at this session's close (days sessions after entry)
    if last >= len(closes) or e >= len(opens) or not opens[e] or not closes[t]:
        return None
    slip = slippage_pct / 100
    cost = (fee_pct * 2 + tax_pct) / 100  # buy fee + sell fee + sell tax
    is_sell = signal_type in ("SELL", "TAKE_PROFIT")
    entry = float(opens[e]) * (1 + slip) if not is_sell else float(opens[e]) * (1 - slip)
    exit_px, exit_i, reason = float(closes[last]), last, "TIME"
    if not is_sell:
        first_sell = e + settlement_sessions  # shares usable from T+2 (afternoon) — approximated as that session
        for k in range(first_sell, last + 1):
            o, h, lo = float(opens[k] or closes[k]), float(highs[k]), float(lows[k])
            if stop and (o <= stop or lo <= stop):
                exit_px, exit_i, reason = (min(o, stop) if o <= stop else float(stop)), k, "STOP"
                break
            if tp1 and (o >= tp1 or h >= tp1):
                exit_px, exit_i, reason = (max(o, tp1) if o >= tp1 else float(tp1)), k, "TP"
                break
        exit_px *= 1 - slip
        ret = (exit_px / entry - 1) * 100 - cost * 100
    else:
        # a sell / take-profit signal is "right" when the price falls after the sell at the next open
        ret = (float(closes[last]) / entry - 1) * 100
    path_h, path_l = highs[e : exit_i + 1], lows[e : exit_i + 1]
    max_gain = (float(np.max(path_h)) / entry - 1) * 100 if len(path_h) else 0.0
    max_loss = (float(np.min(path_l)) / entry - 1) * 100 if len(path_l) else 0.0
    if is_sell:
        result = "WIN" if ret < 0 else "LOSS"
    else:
        result = "TP_HIT" if reason == "TP" else ("STOP_HIT" if reason == "STOP" else ("WIN" if ret > 0 else "LOSS"))
    return {"days": days, "return_pct": round(ret, 2), "max_gain_pct": round(max_gain, 2), "max_loss_pct": round(max_loss, 2), "hit_tp1": reason == "TP", "hit_stop": reason == "STOP",
            "result": result, "entry_price": round(entry), "exit_price": round(exit_px), "exit_reason": reason, "exit_sessions": exit_i - e}


def outcomes_for_arrays(opens, highs, lows, closes, t: int, stop, tp1, signal_type: str, **kw) -> list[dict]:
    out = []
    for days in HOLD_DAYS:
        r = simulate_trade(opens, highs, lows, closes, t, stop, tp1, signal_type, days, **kw)
        if r is None:
            break
        out.append(r)
    return out


def slippage_for(order_value: float, value_ma20: float | None) -> float:
    from app.engines.risk import slippage_pct

    return slippage_pct(order_value, value_ma20)

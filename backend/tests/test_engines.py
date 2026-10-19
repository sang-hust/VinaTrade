"""Unit tests for pure engines (no database)."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.core.vntime import floor_lot, is_trading_day, round_tick, tick_size
from app.engines.bases import detect_bases, rally_stats
from app.engines.indicators import compute_indicators
from app.engines.regime import classify_regime
from app.engines.risk import PretradeInput, company_risk, guard_decision, pretrade_check
from app.engines.scoring import composite, rating_for, tech_components, trade_plan
from app.screener.dsl import DslError, describe, evaluate, validate
from app.screener.presets import DEFAULT_FORM, build_dsl, form_to_rules


def _df(n=400, seed=1, start=50000.0):
    rng = np.random.default_rng(seed)
    close = start * np.cumprod(1 + rng.normal(0.0005, 0.015, n))
    idx = pd.bdate_range("2024-01-01", periods=n)
    df = pd.DataFrame({"open": close * (1 + rng.normal(0, 0.003, n)), "close": close}, index=idx)
    df["high"] = df[["open", "close"]].max(axis=1) * (1 + abs(rng.normal(0, 0.006, n)))
    df["low"] = df[["open", "close"]].min(axis=1) * (1 - abs(rng.normal(0, 0.006, n)))
    df["volume"] = rng.integers(500_000, 3_000_000, n)
    df["value"] = df["close"] * df["volume"]
    return df


def test_tick_and_lot():
    assert tick_size(9_000, "HOSE") == 10 and tick_size(20_000, "HOSE") == 50 and tick_size(80_000, "HOSE") == 100
    assert tick_size(20_000, "HNX") == 100
    assert round_tick(128_460, "HOSE") == 128_500 and round_tick(128_460, "HOSE", "down") == 128_400
    assert round_tick(12_345, "HOSE", "up") == 12_350
    assert floor_lot(1_950) == 1_900 and floor_lot(99) == 0


def test_trading_calendar():
    assert not is_trading_day(date(2026, 1, 1))
    assert not is_trading_day(date(2026, 2, 17))  # Tết 2026
    assert is_trading_day(date(2026, 10, 14))
    assert not is_trading_day(date(2026, 10, 17))  # Saturday


def test_indicators_shape_and_ranges():
    out = compute_indicators(_df(), "HOSE")
    assert len(out) == 400
    last = out.iloc[-1]
    assert 0 <= last.rsi14 <= 100
    assert last.ma50 > 0 and last.ma200 > 0
    assert last.trend_state in ("STRONG_UP", "UP", "FLAT", "DOWN", "STRONG_DOWN")
    assert last.support_1 <= last.close <= last.resistance_1 * 1.0001 or last.resistance_1 >= last.close
    assert out["vol_ratio"].dropna().min() > 0


def test_bases_detect_breakout():
    # flat base then breakout with volume
    n = 120
    idx = pd.bdate_range("2025-01-01", periods=n)
    close = np.concatenate([np.full(40, 20000.0) + np.random.default_rng(2).normal(0, 150, 40), np.linspace(20100, 26000, 80)])
    close[40] = 21000  # breakout day
    vol = np.full(n, 1_000_000.0)
    vol[40] = 3_000_000
    df = pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": vol}, index=idx)
    df.loc[idx[20], "high"] = 20700  # pivot high inside base
    bases, rallies = detect_bases(df, {"min_length": 15, "pivot_wing": 5})
    assert bases, "should detect at least one base"
    assert any(b.status == "BROKEN_OUT" for b in bases)
    st = rally_stats(rallies)
    assert st is None or st["rally_count"] >= 0


def test_regime_classification():
    idx = _df(300, seed=7, start=1200.0)
    f = classify_regime(idx[["close", "volume", "value"]], {"pct_above_ma50": 55, "advances": 200, "declines": 100})
    assert f["regime"] in ("UPTREND", "PRESSURE", "CORRECTION", "DOWNTREND")
    assert f["headline_rule"] and str(f["max_equity_pct"]) in f["headline_rule"]


def test_scoring_and_plan():
    row = {"close": 100000, "ma10": 98000, "ma20": 97000, "ma50": 95000, "ma200": 90000, "adx14": 30, "ma50_slope": 2, "ma200_slope": 1, "rsi14": 60,
           "macd": 1, "macd_signal": 0.5, "macd_hist": 0.5, "vol_ratio": 1.4, "change_pct": 1.2, "cmf20": 0.1, "mfi14": 60, "distribution_days": 0, "rs_rating": 85,
           "base_status": "BROKEN_OUT", "gain_from_base_pct": 3, "support_1": 96000, "resistance_1": 115000, "bb_width": 10}
    tc = tech_components(row)
    assert 60 <= tc["tech"] <= 100
    comp = composite(tc["tech"], 60, 55, 70, {"SHORT": {"tech": 55, "fund": 10, "sector": 10, "pattern": 25}, "MID": {"tech": 35, "fund": 30, "sector": 15, "pattern": 20}, "LONG": {"tech": 15, "fund": 55, "sector": 20, "pattern": 10}}, "UPTREND")
    assert rating_for(comp["MID"]) in ("STRONG_BUY", "BUY", "HOLD")
    assert rating_for(82) == "STRONG_BUY" and rating_for(64.9) == "HOLD" and rating_for(10) == "SELL"
    plan = trade_plan(100000, 2500, 96000, 115000, "HOSE", 7.0, base_high=99000)
    assert plan["stop_loss"] < plan["entry_low"] < plan["entry_high"]
    assert plan["take_profit_1"] > 100000 and plan["take_profit_2"] > plan["take_profit_1"]
    assert plan["risk_reward"] >= 2


def test_pretrade_levels():
    limits = {"max_risk_per_trade_pct": 1.5, "max_position_pct": 20, "max_sector_pct": 40, "min_risk_reward": 2}
    base = dict(symbol="FPT", quantity=1000, price=100000, stop_loss=93000, take_profit=115000, horizon="MID", equity=1_000_000_000, position_value=0, sector_value=0,
                regime="UPTREND", guard_mode="NORMAL", status_flags=[], value_ma20=50e9, gain_from_base_pct=3, ceiling_streak=0, earnings_in_days=None, limits=limits)
    assert pretrade_check(PretradeInput(**base))["result"] == "GREEN"
    assert pretrade_check(PretradeInput(**{**base, "regime": "DOWNTREND"}))["result"] == "RED"
    assert pretrade_check(PretradeInput(**{**base, "quantity": 5000}))["result"] == "RED"  # risk per trade 3.5%
    y = pretrade_check(PretradeInput(**{**base, "gain_from_base_pct": 25}))
    assert y["result"] == "YELLOW" and any(i["code"] == "CHASE" and i["level"] == "YELLOW" for i in y["items"])
    g = pretrade_check(PretradeInput(**{**base, "guard_mode": "DEFENSIVE"}))
    assert g["result"] == "RED" and g["items"][0]["code"] == "GUARD"
    assert pretrade_check(PretradeInput(**base))["suggested_qty"] % 100 == 0


def test_guard_decision():
    assert guard_decision("NORMAL", -3.1, -1, 3, 6, date(2026, 10, 14), None, False) == "ON"
    assert guard_decision("NORMAL", -1, -1, 3, 6, date(2026, 10, 14), None, False) is None
    assert guard_decision("DEFENSIVE", 1, 1, 3, 6, date(2026, 10, 21), date(2026, 10, 21), False) == "OFF"
    assert guard_decision("DEFENSIVE", 1, 1, 3, 6, date(2026, 10, 15), date(2026, 10, 21), False) is None


def test_company_risk():
    r = company_risk({"cfo_negative_quarters": 3, "eps_ttm": 1000, "receivable_gap_pt": 30, "market_cap": 1e12, "debt_to_equity": 2.5}, {"status_flags": ["CONTROL"]})
    assert r["level"] in ("MEDIUM", "HIGH") and r["score"] >= 35 and any(f["code"] == "STATUS" for f in r["flags"])
    assert company_risk({}, {})["level"] == "LOW"


def test_dsl_validate_and_evaluate():
    cond = {"all": [{"field": "rsi14", "op": "<", "value": 35}, {"field": "exchange", "op": "in", "value": ["HOSE"]}]}
    validate(cond)
    assert evaluate(cond, {"rsi14": 30, "exchange": "HOSE"})
    assert not evaluate(cond, {"rsi14": 40, "exchange": "HOSE"})
    with pytest.raises(DslError):
        validate({"field": "nope", "op": ">", "value": 1})
    with pytest.raises(DslError):
        validate({"field": "rsi14", "op": "between", "value": 5})
    assert evaluate({"field": "price", "op": "cross_above", "value": {"field": "ma50"}, "lookback": 3}, {"price": 101, "ma50": 100}, {"price": [98, 99, 101], "ma50": [100, 100, 100]})
    assert evaluate({"field": "signal", "op": "has_signal", "value": "BREAKOUT_BASE"}, {"signals_today": [{"code": "BREAKOUT_BASE"}]})
    assert "RSI (14) < 35" in describe(cond)


def test_form_to_dsl():
    rules = form_to_rules({**DEFAULT_FORM, "rsi": "35_55", "roe": 15, "exchange": ["HOSE"]}, "MID")
    fields = {r["field"] for r in rules}
    assert {"rsi14", "roe", "exchange", "value_ma20", "gain_from_base_pct"} <= fields
    dsl = build_dsl([{"field": "ma50_slope", "op": ">", "value": 0}], {"trend": "UP"}, "MID")
    validate(dsl)
    assert any(r["field"] == "trend_state" for r in dsl["all"]) and any(r["field"] == "ma50_slope" for r in dsl["all"])



def test_scheduler_jobs_are_awaitable():
    """Regression: a lambda returning a coroutine is never awaited by APScheduler (alerts/intraday silently never ran)."""
    import inspect

    from app.tasks.scheduler import JOBS

    assert {j[0] for j in JOBS} >= {"eod", "dispatch", "intraday", "news_sync", "backup"}
    for job_id, _, _, fn, _ in JOBS:
        assert inspect.iscoroutinefunction(fn), job_id


def test_total_risk_components_and_ranking():
    from app.engines.risk import DEFAULT_RISK_WEIGHTS, combine_risk, risk_adjusted, total_risk

    calm = total_risk({"price": 50000, "atr14": 750, "drawdown_12m_pct": 12, "value_ma20": 50e9, "min_liquidity_vnd": 5e9, "company_risk": 10, "gain_20d_pct": 4,
                       "ceiling_streak": 0, "vol_ratio": 1.1, "free_float_pct": 45, "news_count_7d": 3, "beta_60": 0.9})
    hot = total_risk({"price": 8000, "atr14": 560, "drawdown_12m_pct": 65, "value_ma20": 1.2e9, "min_liquidity_vnd": 5e9, "company_risk": 70, "gain_20d_pct": 62,
                      "ceiling_streak": 5, "vol_ratio": 4.2, "free_float_pct": 12, "news_count_7d": 0, "earnings_in_days": 3, "beta_60": 1.8})
    assert calm["level"] == "LOW" and calm["score"] < 25
    assert hot["level"] == "HIGH" and hot["score"] > 75
    keys = [c["key"] for c in hot["components"]]
    assert keys == ["volatility", "liquidity", "company", "manipulation", "event", "correlation"]
    assert all(0 <= c["score"] <= 100 and c["note"] for c in hot["components"])
    assert next(c for c in hot["components"] if c["key"] == "manipulation")["score"] == 100
    assert next(c for c in calm["components"] if c["key"] == "event")["score"] == 0
    # holdings correlation overrides the beta proxy
    corr = total_risk({"price": 50000, "atr14": 750, "max_corr": 0.85, "max_corr_symbol": "HPG"})
    assert next(c for c in corr["components"] if c["key"] == "correlation")["score"] == 100
    # weights change the total but not the component scores; ranking prefers 70/20 over 85/60
    heavy = combine_risk(hot["components"], {**DEFAULT_RISK_WEIGHTS, "company": 60}, None)
    assert heavy["score"] != hot["score"]
    assert risk_adjusted(70, 20) > risk_adjusted(85, 60)
    assert risk_adjusted(None, 10) is None


def test_risk_numbers_and_buy_options():
    from app.engines.risk import buy_options, risk_numbers, slippage_pct

    rel = {"samples": 312, "win_rate": 61.0, "stop_rate": 24.0, "p05_return": -11.2, "worst_return": -18.5, "avg_gain": 7.5, "avg_loss": -5.0}
    n = risk_numbers(rel, 50000, 46000, 50_000_000, 20e9)
    assert n["one_in"] == 4 and n["stop_pct"] == 8.0 and n["max_loss"] > 4_000_000 and "1 trên 4 lần chạm cắt lỗ" in n["text"] and "11%" in n["text"]
    assert "50,0 triệu" in n["text"] and n["expectancy"] == round(0.61 * 7.5 - 0.39 * 5.0, 2) and n["short"].startswith("cắt lỗ 1/4")
    assert risk_numbers({**rel, "samples": 12}, 50000, 46000, 1e7) is None
    assert slippage_pct(1e8, 1e10) < slippage_pct(5e8, 1e10) <= 3.0
    opts = buy_options(50000, 46000, 1000, 20e9, 500_000_000)
    assert [o["key"] for o in opts] == ["none", "third", "full"] and opts[0]["max_loss"] == 0 and opts[1]["quantity"] == 300 and opts[2]["quantity"] == 1000
    assert opts[1]["max_loss"] < opts[2]["max_loss"] and opts[2]["risk_pct"] > 0


def test_pretrade_price_and_cash_guards():
    from app.engines.risk import PretradeInput, pretrade_check

    base = dict(symbol="VNM", quantity=5000, price=5600, stop_loss=5000, take_profit=7000, horizon="MID", equity=500e6, position_value=0, sector_value=0, regime="UPTREND",
                guard_mode="NORMAL", status_flags=[], value_ma20=300e9, gain_from_base_pct=2, ceiling_streak=0, earnings_in_days=None, limits={})
    r = pretrade_check(PretradeInput(**base, market_price=56000, cash=20e6))
    items = {it["code"]: it for it in r["items"]}
    assert items["PRICE"]["level"] == "RED" and "56.000" in items["PRICE"]["note"] and r["result"] == "RED"
    assert items["CASH"]["level"] == "RED"
    ok = pretrade_check(PretradeInput(**{**base, "price": 56000, "stop_loss": 52000, "take_profit": 66000, "quantity": 100}, market_price=56000, cash=20e6, uses_margin=False))
    its = {it["code"]: it for it in ok["items"]}
    assert its["PRICE"]["level"] == "GREEN" and its["CASH"]["level"] == "GREEN"
    assert "CASH" not in {it["code"] for it in pretrade_check(PretradeInput(**base, market_price=None, cash=None))["items"]}


def test_portfolio_heat_exposure_and_exit_liquidity():
    from app.engines.risk import PretradeInput, drawdown_cap, pretrade_check

    base = dict(symbol="HPG", quantity=1000, price=20000, stop_loss=18400, take_profit=24000, horizon="MID", equity=100e6, position_value=0, sector_value=0, regime="UPTREND",
                guard_mode="NORMAL", status_flags=[], value_ma20=300e9, gain_from_base_pct=2, ceiling_streak=0, earnings_in_days=None, limits={"max_open_risk_pct": 6.0, "max_risk_per_trade_pct": 2.0})
    # heat: 4.5% already at risk + 1.6% from this order → 6.1% > 6% cap
    r = pretrade_check(PretradeInput(**base, open_risk_vnd=4.5e6))
    its = {it["code"]: it for it in r["items"]}
    assert its["HEAT"]["level"] == "RED" and "EXPOSURE" not in its
    assert {it["code"]: it["level"] for it in pretrade_check(PretradeInput(**base, open_risk_vnd=1e6))["items"]}["HEAT"] == "GREEN"
    # exposure cap from drawdown: 60M stocks + 20M order = 80% > 50%
    r = pretrade_check(PretradeInput(**base, market_value=60e6, equity_cap_pct=50, equity_cap_reason="giảm 6% từ đỉnh"))
    its = {it["code"]: it for it in r["items"]}
    assert its["EXPOSURE"]["level"] == "RED" and its["EXPOSURE"]["note"] == "giảm 6% từ đỉnh"
    # exit liquidity: 20M order vs 150M/session = 13% → RED; vs 300M = 6.7% → YELLOW; vs 3B → GREEN
    assert {it["code"]: it["level"] for it in pretrade_check(PretradeInput(**{**base, "value_ma20": 150e6}))["items"]}["LIQUIDITY"] == "RED"
    assert {it["code"]: it["level"] for it in pretrade_check(PretradeInput(**{**base, "value_ma20": 300e6}))["items"]}["LIQUIDITY"] == "YELLOW"
    assert {it["code"]: it["level"] for it in pretrade_check(PretradeInput(**{**base, "value_ma20": 3e9}))["items"]}["LIQUIDITY"] == "GREEN"
    assert drawdown_cap(3.0, None) == (None, None) and drawdown_cap(6.0, None)[0] == 50 and drawdown_cap(12.0, {"dd2": 10, "cap2": 20})[0] == 20


def test_realistic_simulation_entry_t2_gap_fees():
    import numpy as np

    from app.engines.simulate import outcomes_for_arrays, simulate_trade

    # sessions: 0 = signal day close 100; 1 = next open 101 (entry); 2 = flat; 3 = gap down open 88 (stop 92 → fills at 88)
    o = np.array([99, 101, 101, 88, 90, 92, 93, 94, 95, 96, 97, 98], dtype=float)
    h = o + 2
    lo = o - 2
    c = o + 1
    r = simulate_trade(o, h, lo, c, 0, stop=92, tp1=120, signal_type="BUY", days=10, fee_pct=0.15, tax_pct=0.1, slippage_pct=0.0, settlement_sessions=2)
    assert r["exit_reason"] == "STOP" and r["exit_price"] == 88 and r["entry_price"] == 101 and r["exit_sessions"] == 2
    assert r["return_pct"] == round((88 / 101 - 1) * 100 - 0.4, 2) and r["result"] == "STOP_HIT" and r["hit_stop"]
    # T+2: a stop touched on the entry session or the next one cannot be executed yet
    lo2 = lo.copy()
    lo2[1] = 80
    lo2[2] = 80
    lo2[3:] = 95
    o2 = o.copy()
    o2[3:] = 100
    r2 = simulate_trade(o2, o2 + 2, lo2, o2 + 1, 0, stop=92, tp1=120, signal_type="BUY", days=10, slippage_pct=0.0)
    assert r2["exit_reason"] == "TIME" and not r2["hit_stop"]
    # take profit through a gap up fills at the open; slippage lowers the result
    o3 = np.array([99, 101, 101, 125, 126, 127, 128, 129, 130, 131, 132, 133], dtype=float)
    r3 = simulate_trade(o3, o3 + 1, o3 - 1, o3, 0, stop=92, tp1=120, signal_type="BUY", days=10, slippage_pct=0.0)
    r3s = simulate_trade(o3, o3 + 1, o3 - 1, o3, 0, stop=92, tp1=120, signal_type="BUY", days=10, slippage_pct=1.0)
    assert r3["exit_reason"] == "TP" and r3["exit_price"] == 125 and r3s["return_pct"] < r3["return_pct"]
    # sell signals: right when the price is lower than the next open after `days`
    rs = simulate_trade(o, h, lo, c, 0, stop=None, tp1=None, signal_type="SELL", days=5, slippage_pct=0.0)
    assert rs["result"] == "WIN"
    # window shorter than days → nothing
    assert outcomes_for_arrays(o, h, lo, c, 0, 92, 120, "BUY", slippage_pct=0.0)[-1]["days"] == 10

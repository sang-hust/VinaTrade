"""Fundamental ratios (TTM) from quarterly statements + price + shares (spec 3.3 a/b, valuation_daily)."""

import math
from datetime import date

import numpy as np


def _f(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def _sum(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None


def _cagr(first, last, years):
    if not first or not last or first <= 0 or last <= 0 or years <= 0:
        return None
    return (last / first) ** (1 / years) - 1


def compute_ratios(quarters: list[dict], years: list[dict], price: float, shares: float | None, as_of: date,
                   dps: float | None = None, is_bank: bool = False) -> dict:
    """quarters: rows with year, quarter(1-4) sorted ascending; years: rows with quarter==5 ascending.
    Monetary values in VND. Returns a dict matching FinancialRatio columns."""
    q = [r for r in quarters if r.get("quarter") in (1, 2, 3, 4)]
    q.sort(key=lambda r: (r["year"], r["quarter"]))
    y = sorted([r for r in years if r.get("quarter") == 5], key=lambda r: r["year"])
    out: dict = {"as_of": as_of}
    if not q and not y:
        return out
    last4 = q[-4:] if len(q) >= 4 else []
    latest = q[-1] if q else (y[-1] if y else {})
    out["latest_year"], out["latest_quarter"] = latest.get("year"), latest.get("quarter")
    rev_ttm = _sum([r.get("revenue") for r in last4]) if last4 else (y[-1].get("revenue") if y else None)
    np_ttm = _sum([r.get("net_profit") for r in last4]) if last4 else (y[-1].get("net_profit") if y else None)
    gp_ttm = _sum([r.get("gross_profit") for r in last4]) if last4 else (y[-1].get("gross_profit") if y else None)
    cfo_ttm = _sum([r.get("cfo") for r in last4]) if last4 else (y[-1].get("cfo") if y else None)
    equity = _f(latest.get("equity"))
    assets = _f(latest.get("total_assets"))
    out["eps_ttm"] = np_ttm / shares if np_ttm is not None and shares else _f(latest.get("eps"))
    out["bvps"] = equity / shares if equity and shares else None
    out["market_cap"] = price * shares if shares else None
    out["pe"] = price / out["eps_ttm"] if out["eps_ttm"] and out["eps_ttm"] > 0 else None
    out["pb"] = price / out["bvps"] if out["bvps"] and out["bvps"] > 0 else None
    out["ps"] = out["market_cap"] / rev_ttm if out["market_cap"] and rev_ttm and rev_ttm > 0 else None
    # average equity/assets over the year for ROE/ROA
    eq_hist = [_f(r.get("equity")) for r in q[-5:] if r.get("equity")] or ([equity] if equity else [])
    as_hist = [_f(r.get("total_assets")) for r in q[-5:] if r.get("total_assets")] or ([assets] if assets else [])
    out["roe"] = np_ttm / np.mean(eq_hist) * 100 if np_ttm is not None and eq_hist and np.mean(eq_hist) > 0 else None
    out["roa"] = np_ttm / np.mean(as_hist) * 100 if np_ttm is not None and as_hist and np.mean(as_hist) > 0 else None
    out["gross_margin"] = gp_ttm / rev_ttm * 100 if gp_ttm is not None and rev_ttm else None
    out["net_margin"] = np_ttm / rev_ttm * 100 if np_ttm is not None and rev_ttm else None
    debt = _sum([_f(latest.get("short_debt")), _f(latest.get("long_debt"))])
    out["debt_to_equity"] = debt / equity if debt is not None and equity and equity > 0 else None
    ca, cl = _f(latest.get("current_assets")), _f(latest.get("current_liabilities"))
    out["current_ratio"] = ca / cl if ca and cl and cl > 0 else None
    out["cfo_to_profit"] = cfo_ttm / np_ttm if cfo_ttm is not None and np_ttm and np_ttm > 0 else None
    # YoY of latest quarter vs same quarter last year
    if q:
        same = [r for r in q if r["year"] == latest["year"] - 1 and r["quarter"] == latest["quarter"]]
        if same:
            s = same[0]
            if s.get("revenue") and latest.get("revenue") is not None:
                out["revenue_yoy"] = (latest["revenue"] / s["revenue"] - 1) * 100 if s["revenue"] > 0 else None
            if s.get("net_profit") and latest.get("net_profit") is not None:
                out["profit_yoy"] = (latest["net_profit"] / s["net_profit"] - 1) * 100 if s["net_profit"] > 0 else None
    if len(y) >= 4:
        out["revenue_cagr_3y"] = (_cagr(y[-4].get("revenue"), y[-1].get("revenue"), 3) or 0) * 100 if _cagr(y[-4].get("revenue"), y[-1].get("revenue"), 3) is not None else None
        out["profit_cagr_3y"] = (_cagr(y[-4].get("net_profit"), y[-1].get("net_profit"), 3) or 0) * 100 if _cagr(y[-4].get("net_profit"), y[-1].get("net_profit"), 3) is not None else None
    growth = out.get("profit_cagr_3y") if out.get("profit_cagr_3y") is not None else out.get("profit_yoy")
    out["peg"] = out["pe"] / growth if out.get("pe") and growth and growth > 0 else None
    out["dividend_yield"] = dps / price * 100 if dps and price else None
    # valuation (3.3b): PE-target uses stock's own 5y median PE proxy = 12 (sector-adjusted later), PB-target for banks
    eps, bvps = out.get("eps_ttm"), out.get("bvps")
    fv_pe = eps * 12 if eps and eps > 0 else None
    fv_pb = bvps * (1.5 if is_bank else 1.8) if bvps and bvps > 0 else None
    fv_graham = math.sqrt(22.5 * eps * bvps) if eps and bvps and eps > 0 and bvps > 0 else None
    cands = [v for v in (fv_pe, fv_pb if is_bank else None, fv_graham) if v]
    out["fair_value_pe"], out["fair_value_pb"], out["fair_value_graham"] = fv_pe, fv_pb, fv_graham
    out["fair_value"] = float(np.median(cands)) if cands else None
    out["margin_of_safety"] = (out["fair_value"] - price) / out["fair_value"] * 100 if out["fair_value"] and price else None
    # risk inputs (4.6h)
    neg = 0
    for r in reversed(q[-6:]):
        if r.get("cfo") is not None and r["cfo"] < 0 and (r.get("net_profit") or 0) > 0:
            neg += 1
        else:
            break
    out["cfo_negative_quarters"] = neg
    if len(q) >= 5 and q[-5].get("revenue") and q[-1].get("revenue"):
        rev_g = (q[-1]["revenue"] / q[-5]["revenue"] - 1) * 100 if q[-5]["revenue"] > 0 else None
        for key, col in (("receivable_gap_pt", "receivables"), ("inventory_gap_pt", "inventory")):
            a, b = q[-5].get(col), q[-1].get(col)
            if rev_g is not None and a and b and a > 0:
                out[key] = (b / a - 1) * 100 - rev_g
    return out

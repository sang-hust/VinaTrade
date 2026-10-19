"""End-of-day pipeline (spec 4.3). Each step is a job (JobRun) so the admin console can show the chain.

Steps: universe → prices/indexes → indicators → bases & rallies → RS/beta → ratios → regime & headline → sectors
→ scores → company risk → signals → snapshot → outcomes & reliability → presets, alerts, action items, reports."""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import delete, desc, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.vntime import last_closed_trading_day, today_vn
from app.engines import strategies as strat
from app.engines.bases import detect_bases, rally_stats
from app.engines.indicators import OUTPUT_COLS, compute_indicators, rs_ratings, weighted_performance
from app.engines.ratios import compute_ratios
from app.engines.regime import classify_regime
from app.engines.risk import beta as calc_beta
from app.engines.risk import company_risk, nan_to_none, reliability_label, risk_adjusted, total_risk
from app.engines.scoring import (
    RATING_VI,
    composite,
    downgrade,
    fund_components,
    pattern_ai_score,
    percentile_within_groups,
    rating_for,
    tech_components,
    trade_plan,
)
from app.ingestion.prices import sync_indexes, sync_prices
from app.ingestion.universe import sync_universe
from app.models import (
    CompanyRiskScore,
    CorporateAction,
    FinancialRatio,
    FinancialStatement,
    IndexDaily,
    IndicatorDaily,
    MarketRegime,
    PriceBase,
    PriceDaily,
    Rally,
    RallyStat,
    Screener,
    SectorScore,
    Signal,
    SignalOutcome,
    SignalReliability,
    Stock,
    StockScore,
    StockSnapshot,
    Strategy,
)
from app.services import ai
from app.services.jobs import run_job
from app.services.sysconfig import get_config

log = logging.getLogger(__name__)
KEEP_INDICATOR_SESSIONS = 300
MIN_SESSIONS = 30


def _f(v):
    return nan_to_none(v)


async def _active_symbols(db: AsyncSession) -> list[Stock]:
    q = select(Stock).where(Stock.is_active).order_by(Stock.symbol)
    if settings.universe_limit:
        q = q.limit(settings.universe_limit)
    return list((await db.execute(q)).scalars())


async def _load_prices(db: AsyncSession, symbols: list[str], since: date | None = None) -> dict[str, pd.DataFrame]:
    q = select(PriceDaily.symbol, PriceDaily.trade_date, PriceDaily.open, PriceDaily.high, PriceDaily.low, PriceDaily.close, PriceDaily.volume, PriceDaily.value).where(PriceDaily.symbol.in_(symbols))
    if since:
        q = q.where(PriceDaily.trade_date >= since)
    rows = (await db.execute(q)).all()
    if not rows:
        return {}
    df = pd.DataFrame(rows, columns=["symbol", "trade_date", "open", "high", "low", "close", "volume", "value"])
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    out = {}
    for sym, g in df.groupby("symbol"):
        g = g.drop(columns="symbol").set_index("trade_date").sort_index()
        out[sym] = g
    return out


# ------------------------------------------------------------------ steps
async def step_universe(db: AsyncSession) -> dict:
    return await sync_universe(db, limit=settings.universe_limit)


async def step_prices(db: AsyncSession) -> dict:
    syms = [s.symbol for s in await _active_symbols(db)]
    r = await sync_prices(db, symbols=syms)
    r2 = await sync_indexes(db)
    r["index_rows"] = r2["rows"]
    if r["failed"] > max(20, len(syms) * 0.05):
        r["warn"] = True
    return r


async def step_extras(db: AsyncSession) -> dict:
    """Events + exchange alerts, foreign/proprietary flows, broker recommendations, insider deals (free sources, see docs/NGUON-DU-LIEU.md)."""
    from app.ingestion import extras

    out = {}
    for name, coro in (("events", extras.sync_events(db)), ("flows", extras.sync_flows(db, extras.trading_days_back(3))),
                       ("recommendations", extras.sync_recommendations(db)), ("insiders", extras.sync_insiders(db))):
        try:
            r = await coro
            out[name] = r
        except Exception as e:  # noqa: BLE001
            log.warning("extras %s failed: %s", name, e)
            out[name] = {"error": str(e)[:200]}
            out["warn"] = True
    out["summary"] = ", ".join(f"{k}={next(iter(v.values())) if isinstance(v, dict) and v else v}" for k, v in out.items() if k not in ("warn",))
    return out


async def step_enrich(db: AsyncSession) -> dict:
    from app.ingestion.extras import enrich_snapshots

    return await enrich_snapshots(db)


async def step_indicators(db: AsyncSession, full: bool = False) -> dict:
    stocks = await _active_symbols(db)
    ex = {s.symbol: s.exchange for s in stocks}
    symbols = [s.symbol for s in stocks]
    n_rows, n_sym = 0, 0
    last_date = (await db.execute(select(func.max(IndicatorDaily.trade_date)))).scalar()
    for i in range(0, len(symbols), 120):
        batch = symbols[i : i + 120]
        frames = await _load_prices(db, batch)
        rows = []
        for sym, df in frames.items():
            if len(df) < MIN_SESSIONS:
                continue
            ind = compute_indicators(df, ex.get(sym, "HOSE"))
            keep = ind.iloc[-KEEP_INDICATOR_SESSIONS:] if (full or last_date is None) else ind.iloc[-6:]
            for d, r in keep.iterrows():
                rec = {"symbol": sym, "trade_date": d.date()}
                for c in OUTPUT_COLS:
                    v = r[c]
                    rec[c] = None if (v is None or (isinstance(v, float) and math.isnan(v))) else (int(v) if c in ("ceiling_streak", "distribution_days") else v)
                rows.append(rec)
            n_sym += 1
        if rows:
            for j in range(0, len(rows), 800):
                chunk = rows[j : j + 800]
                stmt = insert(IndicatorDaily).values(chunk)
                stmt = stmt.on_conflict_do_update(index_elements=["symbol", "trade_date"], set_={c: getattr(stmt.excluded, c) for c in OUTPUT_COLS})
                await db.execute(stmt)
            n_rows += len(rows)
        await db.flush()
    # prune old indicator rows
    cutoff = today_vn() - timedelta(days=int(KEEP_INDICATOR_SESSIONS * 1.6))
    await db.execute(delete(IndicatorDaily).where(IndicatorDaily.trade_date < cutoff))
    return {"symbols": n_sym, "rows": n_rows}


async def step_bases(db: AsyncSession) -> dict:
    stocks = await _active_symbols(db)
    params = await get_config(db, "base.params")
    n_b = n_r = 0
    symbols = [s.symbol for s in stocks]
    for i in range(0, len(symbols), 150):
        batch = symbols[i : i + 150]
        frames = await _load_prices(db, batch)
        for sym, df in frames.items():
            if len(df) < 60:
                continue
            bases, rallies = detect_bases(df, params)
            await db.execute(delete(Rally).where(Rally.symbol == sym))
            await db.execute(delete(PriceBase).where(PriceBase.symbol == sym))
            base_ids = []
            for b in bases[-12:]:
                pb = PriceBase(symbol=sym, start_date=b.start_date, end_date=b.end_date, base_high=b.base_high, base_low=b.base_low, depth_pct=b.depth_pct,
                               length_days=b.length_days, tightness_pct=b.tightness_pct, vol_dry_ratio=b.vol_dry_ratio, avg_volume=b.avg_volume, pattern=b.pattern,
                               status=b.status, breakout_date=b.breakout_date, breakout_vol_ratio=b.breakout_vol_ratio)
                db.add(pb)
                base_ids.append(pb)
            await db.flush()
            offset = len(bases) - len(bases[-12:])
            for r in rallies:
                bi = r.base_index - offset
                db.add(Rally(symbol=sym, base_id=base_ids[bi].id if 0 <= bi < len(base_ids) else None, start_date=r.start_date, peak_date=r.peak_date, end_date=r.end_date,
                             base_high=r.base_high, peak_price=r.peak_price, gain_pct=r.gain_pct, days_to_peak=r.days_to_peak, peak_vol_ratio=r.peak_vol_ratio,
                             distribution_days=r.distribution_days, pullback_pct=r.pullback_pct, status=r.status))
            st = rally_stats(rallies)
            if st:
                stmt = insert(RallyStat).values(symbol=sym, **st)
                await db.execute(stmt.on_conflict_do_update(index_elements=["symbol"], set_=st))
            n_b += len(bases)
            n_r += len(rallies)
        await db.flush()
    return {"bases": n_b, "rallies": n_r}


async def step_rs_beta(db: AsyncSession) -> dict:
    """Cross-sectional RS rating (1–99) and 60-session beta vs VN-Index, written to the latest indicator row."""
    stocks = await _active_symbols(db)
    symbols = [s.symbol for s in stocks]
    since = today_vn() - timedelta(days=420)
    idx_rows = (await db.execute(select(IndexDaily.trade_date, IndexDaily.close).where(IndexDaily.index_code == "VNINDEX", IndexDaily.trade_date >= since).order_by(IndexDaily.trade_date))).all()
    idx = pd.Series({pd.Timestamp(d): c for d, c in idx_rows}).sort_index()
    idx_ret = idx.pct_change().iloc[-60:]
    perf, betas = {}, {}
    for i in range(0, len(symbols), 200):
        frames = await _load_prices(db, symbols[i : i + 200], since)
        for sym, df in frames.items():
            p = weighted_performance(df["close"])
            if p is not None:
                perf[sym] = p
            b = calc_beta(df["close"].pct_change().iloc[-60:], idx_ret)
            if b is not None:
                betas[sym] = b
    rs = rs_ratings(pd.Series(perf)) if perf else pd.Series(dtype=float)
    last = (await db.execute(select(func.max(IndicatorDaily.trade_date)))).scalar()
    n = 0
    for sym, r in rs.items():
        await db.execute(text("UPDATE indicators_daily SET rs_rating=:r WHERE symbol=:s AND trade_date=:d"), {"r": float(r), "s": sym, "d": last})
        n += 1
    db.info["betas"] = betas
    # cache betas in a temp table-free way: store on snapshot later; keep in module cache
    _BETA_CACHE.clear()
    _BETA_CACHE.update(betas)
    return {"rs": n, "beta": len(betas)}


_BETA_CACHE: dict[str, float] = {}


async def step_ratios(db: AsyncSession) -> dict:
    stocks = await _active_symbols(db)
    latest_px = {s: c for s, c in (await db.execute(text(
        "SELECT DISTINCT ON (symbol) symbol, close FROM price_daily WHERE symbol = ANY(:syms) ORDER BY symbol, trade_date DESC"), {"syms": [s.symbol for s in stocks]})).all()}
    as_of = last_closed_trading_day()
    n = 0
    for i in range(0, len(stocks), 200):
        batch = stocks[i : i + 200]
        rows = (await db.execute(select(FinancialStatement).where(FinancialStatement.symbol.in_([s.symbol for s in batch]), FinancialStatement.year >= as_of.year - 6))).scalars().all()
        by: dict[str, list] = {}
        for r in rows:
            by.setdefault(r.symbol, []).append({c: getattr(r, c) for c in ("year", "quarter", "revenue", "gross_profit", "net_profit", "eps", "total_assets", "equity", "short_debt", "long_debt", "current_assets", "current_liabilities", "cfo", "receivables", "inventory")})
        for s in batch:
            recs = by.get(s.symbol)
            px = latest_px.get(s.symbol)
            if not recs or not px:
                continue
            dps = None
            try:
                dps = float((s.source_meta or {}).get("dps")) if (s.source_meta or {}).get("dps") else None
            except (TypeError, ValueError):
                dps = None
            out = compute_ratios([r for r in recs if r["quarter"] <= 4], [r for r in recs if r["quarter"] == 5], px, s.listed_shares, as_of, dps=dps, is_bank=s.is_bank)
            if not out or len(out) <= 1:
                continue
            vals = {k: _f(v) for k, v in out.items()}
            for k in list(vals):
                if isinstance(vals[k], float) and (math.isinf(vals[k]) or abs(vals[k]) > 1e15):
                    vals[k] = None
            stmt = insert(FinancialRatio).values(symbol=s.symbol, **vals)
            await db.execute(stmt.on_conflict_do_update(index_elements=["symbol"], set_=vals))
            n += 1
        await db.flush()
    return {"ratios": n}


async def _breadth(db: AsyncSession, d: date) -> dict:
    row = (await db.execute(text("""
        SELECT count(*) n,
               sum(case when close > ma50 then 1 else 0 end) above50,
               sum(case when close > ma200 then 1 else 0 end) above200,
               sum(case when change_pct > 0.05 then 1 else 0 end) adv,
               sum(case when change_pct < -0.05 then 1 else 0 end) dec
        FROM indicators_daily i JOIN stocks s ON s.symbol=i.symbol
        WHERE i.trade_date=:d AND s.is_active AND i.value_ma20 >= 1e9"""), {"d": d})).one()
    n = row.n or 1
    return {"pct_above_ma50": round((row.above50 or 0) / n * 100, 1), "pct_above_ma200": round((row.above200 or 0) / n * 100, 1),
            "advances": int(row.adv or 0), "declines": int(row.dec or 0), "unchanged": int(n - (row.adv or 0) - (row.dec or 0))}


async def step_regime(db: AsyncSession) -> dict:
    rows = (await db.execute(select(IndexDaily).where(IndexDaily.index_code == "VNINDEX").order_by(desc(IndexDaily.trade_date)).limit(320))).scalars().all()
    if not rows:
        return {"warn": True, "summary": "no VNINDEX data"}
    df = pd.DataFrame([{"trade_date": r.trade_date, "close": r.close, "volume": r.volume or 0, "value": r.value} for r in reversed(rows)]).set_index("trade_date")
    d = rows[0].trade_date
    br = await _breadth(db, (await db.execute(select(func.max(IndicatorDaily.trade_date)))).scalar() or d)
    facts = classify_regime(df, br)
    equity = await get_config(db, "regime.equity")
    facts["max_equity_pct"] = int(equity.get(facts["regime"], facts["max_equity_pct"]))
    draft = facts["headline_rule"].replace(f"{facts['max_equity_pct']}%", f"{facts['max_equity_pct']}%")
    headline = await ai.rewrite_headline(draft, {k: facts[k] for k in ("vnindex", "vnindex_change_pct", "pct_above_ma50", "dist_days", "max_equity_pct", "regime_vi")})
    reg = await db.get(MarketRegime, d)
    if reg is None:
        reg = MarketRegime(trade_date=d)
        db.add(reg)
    reg.regime, reg.max_equity_pct = facts["regime"], facts["max_equity_pct"]
    reg.vnindex, reg.vnindex_change_pct = facts["vnindex"], facts["vnindex_change_pct"]
    reg.pct_above_ma50, reg.pct_above_ma200 = br["pct_above_ma50"], br["pct_above_ma200"]
    reg.advances, reg.declines, reg.distribution_days, reg.liquidity_ratio = br["advances"], br["declines"], facts["dist_days"], facts["liquidity_ratio"]
    reg.headline, reg.note, reg.facts = headline, draft, facts
    # breadth onto index_daily
    idx = await db.get(IndexDaily, ("VNINDEX", d))
    if idx:
        idx.advances, idx.declines, idx.unchanged, idx.pct_above_ma50, idx.pct_above_ma200 = br["advances"], br["declines"], br["unchanged"], br["pct_above_ma50"], br["pct_above_ma200"]
    await db.flush()
    return {"regime": facts["regime"], "headline": headline, "vnindex": facts["vnindex"]}


async def step_sectors(db: AsyncSession) -> dict:
    stocks = await _active_symbols(db)
    by_ind: dict[str, list[str]] = {}
    for s in stocks:
        if s.industry_code:
            by_ind.setdefault(s.industry_code, []).append(s.symbol)
    d = (await db.execute(select(func.max(IndicatorDaily.trade_date)))).scalar()
    since = today_vn() - timedelta(days=120)
    rules = await get_config(db, "macro.sector_rules")
    active = set(await get_config(db, "macro.active_factors") or [])
    macro_pts: dict[str, int] = {}
    macro_note: dict[str, list[str]] = {}
    for r in rules:
        if r["factor"] in active:
            for c in r.get("benefit", []):
                macro_pts[c] = macro_pts.get(c, 0) + 1
                macro_note.setdefault(c, []).append(r["factor"])
            for c in r.get("hurt", []):
                macro_pts[c] = macro_pts.get(c, 0) - 1
    results = []
    for code, syms in by_ind.items():
        frames = await _load_prices(db, syms, since)
        if not frames:
            continue
        perf = {k: [] for k in (5, 21, 63)}
        flow = []
        for sym, df in frames.items():
            c = df["close"]
            if len(c) < 25:
                continue
            for k in perf:
                if len(c) > k:
                    perf[k].append(c.iloc[-1] / c.iloc[-1 - k] - 1)
            val = df["value"].fillna(df["close"] * df["volume"])
            if val.iloc[-20:].mean():
                flow.append(val.iloc[-5:].mean() / val.iloc[-20:].mean() - 1)
        ind_rows = (await db.execute(select(IndicatorDaily.symbol, IndicatorDaily.close, IndicatorDaily.ma50).where(IndicatorDaily.symbol.in_(syms), IndicatorDaily.trade_date == d))).all()
        above = [1 if (c and m and c > m) else 0 for _, c, m in ind_rows if m]
        breadth = sum(above) / len(above) * 100 if above else 50.0
        p1w = float(np.median(perf[5])) * 100 if perf[5] else 0.0
        p1m = float(np.median(perf[21])) * 100 if perf[21] else 0.0
        p3m = float(np.median(perf[63])) * 100 if perf[63] else 0.0
        mflow = float(np.median(flow)) * 100 if flow else 0.0
        # score: 30 momentum (1m,3m) + 25 breadth + 20 money flow + 25 macro
        mom = 50 + max(-25, min(25, p1m * 1.5)) + max(-15, min(15, p3m * 0.5))
        score = 0.30 * max(0, min(100, mom)) + 0.25 * breadth + 0.20 * max(0, min(100, 50 + mflow)) + 0.25 * (50 + 25 * macro_pts.get(code, 0))
        results.append((code, round(max(0, min(100, score)), 1), p1w, p1m, p3m, mflow, breadth, len(syms), "; ".join(macro_note.get(code, []))))
    for code, score, p1w, p1m, p3m, mflow, breadth, n, note in results:
        vals = dict(score=score, perf_1w=round(p1w, 2), perf_1m=round(p1m, 2), perf_3m=round(p3m, 2), money_flow=round(mflow, 2), breadth=round(breadth, 1), stock_count=n, macro_note=note or None)
        stmt = insert(SectorScore).values(industry_code=code, trade_date=d, **vals)
        await db.execute(stmt.on_conflict_do_update(index_elements=["industry_code", "trade_date"], set_=vals))
    await db.flush()
    return {"sectors": len(results)}


FUND_PCT_COLS = ["profit_yoy", "revenue_yoy", "profit_cagr_3y", "revenue_cagr_3y", "roe", "roa", "net_margin", "gross_margin", "debt_to_equity", "current_ratio", "cfo_to_profit", "pe", "pb", "peg", "dividend_yield"]


async def _latest_rows(db: AsyncSession, model, symbols: list[str], date_col: str = "trade_date", since: date | None = None) -> dict[str, object]:
    base_q = select(model.symbol, func.max(getattr(model, date_col)).label("d")).where(model.symbol.in_(symbols))
    if since is not None:
        base_q = base_q.where(getattr(model, date_col) >= since)
    sub = base_q.group_by(model.symbol).subquery()
    rows = (await db.execute(select(model).join(sub, (model.symbol == sub.c.symbol) & (getattr(model, date_col) == sub.c.d)))).scalars().all()
    return {r.symbol: r for r in rows}


async def step_scores(db: AsyncSession) -> dict:
    stocks = await _active_symbols(db)
    symbols = [s.symbol for s in stocks]
    by_sym = {s.symbol: s for s in stocks}
    d = (await db.execute(select(func.max(IndicatorDaily.trade_date)))).scalar()
    ind = await _latest_rows(db, IndicatorDaily, symbols, since=d - timedelta(days=7))
    ratios = {r.symbol: r for r in (await db.execute(select(FinancialRatio).where(FinancialRatio.symbol.in_(symbols)))).scalars()}
    bases = {}
    for b in (await db.execute(select(PriceBase).where(PriceBase.symbol.in_(symbols), PriceBase.status.in_(["FORMING", "BROKEN_OUT"])).order_by(PriceBase.symbol, desc(PriceBase.start_date)))).scalars():
        bases.setdefault(b.symbol, b)  # latest per symbol
    rallies = {r.symbol: r for r in (await db.execute(select(RallyStat).where(RallyStat.symbol.in_(symbols)))).scalars()}
    sect = {r.industry_code: r.score for r in (await db.execute(select(SectorScore).where(SectorScore.trade_date == (await db.scalar(select(func.max(SectorScore.trade_date))))))).scalars()}
    regime_row = (await db.execute(select(MarketRegime).order_by(desc(MarketRegime.trade_date)).limit(1))).scalar_one_or_none()
    regime = regime_row.regime if regime_row else "UPTREND"
    weights = await get_config(db, "scoring.weights")
    risk_th = await get_config(db, "risk.company_thresholds")
    chase = await get_config(db, "risk.chase")
    risk_rows = {r.symbol: r for r in (await db.execute(select(CompanyRiskScore).where(CompanyRiskScore.symbol.in_(symbols)))).scalars()}
    # fundamental percentiles within industry
    fdf = pd.DataFrame([{"symbol": s, "industry": by_sym[s].industry_code or "NA", **{c: getattr(r, c) for c in FUND_PCT_COLS}} for s, r in ratios.items()]).set_index("symbol") if ratios else pd.DataFrame()
    pct = percentile_within_groups(fdf, "industry", FUND_PCT_COLS) if not fdf.empty else pd.DataFrame()
    n = 0
    prev_scores = await _latest_rows(db, StockScore, symbols)
    for s in stocks:
        i = ind.get(s.symbol)
        if not i or not i.close:
            continue
        b = bases.get(s.symbol)
        gain_from_base = (i.close / b.base_high - 1) * 100 if b and b.status == "BROKEN_OUT" and b.base_high else None
        row = {c: getattr(i, c) for c in OUTPUT_COLS}
        row.update({"base_status": b.status if b else None, "base_tightness": b.tightness_pct if b else None, "gain_from_base_pct": gain_from_base,
                    "vol_dry_ratio": b.vol_dry_ratio if b else None})
        tc = tech_components(row)
        r = ratios.get(s.symbol)
        if r is not None and s.symbol in pct.index:
            fc = fund_components({c: getattr(r, c) for c in FUND_PCT_COLS}, pct.loc[s.symbol].to_dict())
        else:
            fc = {"fund": 45.0, "fund_growth": 45.0, "fund_profitability": 45.0, "fund_health": 45.0, "fund_valuation": 45.0}
        rl = rallies.get(s.symbol)
        pa = pattern_ai_score(row, {"median_gain_pct": rl.median_gain_pct, "rally_count": rl.rally_count} if rl else None)
        sector_score = sect.get(s.industry_code, 50.0) if s.industry_code else 50.0
        comp = composite(tc["tech"], fc["fund"], sector_score, pa, weights, regime)
        risk = risk_rows.get(s.symbol)
        risk_score = risk.score if risk else 0.0
        ratings = {hz: rating_for(comp[hz]) for hz in comp}
        if risk_score >= risk_th.get("downgrade", 60):
            ratings = {hz: downgrade(v) for hz, v in ratings.items()}
        limit = chase.get("SHORT", 15) if False else chase.get("MID", 20)
        is_chase = strat.is_chase(gain_from_base, i.ceiling_streak, "MID", {"chase_short": chase.get("SHORT", 15), "chase_mid": limit})
        plan = trade_plan(i.close, i.atr14, i.support_1, i.resistance_1, s.exchange, stop_pct=7.0, base_high=b.base_high if b and b.status == "BROKEN_OUT" else None)
        trend3 = _trend3(i)
        reasons, drawbacks = _reasons(i, r, b, rl, gain_from_base, risk, sector_score, s)
        vals = dict(**tc, **fc, sector=round(sector_score, 1), pattern_ai=round(pa, 1), score_short=comp["SHORT"], score_mid=comp["MID"], score_long=comp["LONG"],
                    rating_short=ratings["SHORT"], rating_mid=ratings["MID"], rating_long=ratings["LONG"], trend_short=trend3[0], trend_mid=trend3[1], trend_long=trend3[2],
                    entry_low=plan.get("entry_low"), entry_high=plan.get("entry_high"), stop_loss=plan.get("stop_loss"), take_profit_1=plan.get("take_profit_1"),
                    take_profit_2=plan.get("take_profit_2"), risk_reward=plan.get("risk_reward"), reasons=reasons, drawbacks=drawbacks)
        stmt = insert(StockScore).values(symbol=s.symbol, trade_date=i.trade_date, **vals)
        await db.execute(stmt.on_conflict_do_update(index_elements=["symbol", "trade_date"], set_=vals))
        _SCORE_CACHE[s.symbol] = {**vals, "is_chase": is_chase, "gain_from_base_pct": gain_from_base, "base": b, "prev_rating": (prev_scores[s.symbol].rating_mid if s.symbol in prev_scores and prev_scores[s.symbol].trade_date != i.trade_date else None)}
        n += 1
    await db.flush()
    # sector leaders
    sect_date = await db.scalar(select(func.max(SectorScore.trade_date)))
    leaders: dict[str, list] = {}
    for s in stocks:
        sc = _SCORE_CACHE.get(s.symbol)
        if sc and s.industry_code:
            leaders.setdefault(s.industry_code, []).append((sc["score_mid"], s.symbol))
    for code, lst in leaders.items():
        row = await db.get(SectorScore, (code, sect_date))
        if row:
            row.leaders = [{"symbol": sym, "score": sc} for sc, sym in sorted(lst, reverse=True)[:5]]
    await db.flush()
    return {"scored": n, "regime": regime}


_SCORE_CACHE: dict[str, dict] = {}


def _days_to_filing_deadline(today: date) -> int:
    """Days until the next quarterly BCTC filing deadline (20/1, 20/4, 20/7, 20/10 for listed companies)."""
    for m in (1, 4, 7, 10):
        dl = date(today.year, m, 20)
        if dl >= today:
            return (dl - today).days
    return (date(today.year + 1, 1, 20) - today).days


def _days_to_derivatives_expiry(today: date) -> int:
    """Days until the next VN30 futures expiry (third Thursday of the month)."""
    for k in (0, 1):
        y, m = (today.year + (today.month + k - 1) // 12, (today.month + k - 1) % 12 + 1)
        first = date(y, m, 1)
        third_thu = first + timedelta(days=(3 - first.weekday()) % 7 + 14)
        if third_thu >= today:
            return (third_thu - today).days
    return 30


async def _betas_from_prices(db: AsyncSession, symbols: list[str], sessions: int = 60) -> dict[str, float]:
    """60-session beta vs VN-Index from price_daily (used when the in-process cache from step_rs_beta is empty)."""
    since = today_vn() - timedelta(days=int(sessions * 1.6) + 10)
    idx = pd.Series({d: c for d, c in (await db.execute(select(IndexDaily.trade_date, IndexDaily.close).where(IndexDaily.index_code == "VNINDEX", IndexDaily.trade_date >= since))).all()}).sort_index()
    rows = (await db.execute(select(PriceDaily.symbol, PriceDaily.trade_date, PriceDaily.close).where(PriceDaily.symbol.in_(symbols), PriceDaily.trade_date >= since))).all()
    if idx.empty or not rows:
        return {}
    px = pd.DataFrame(rows, columns=["symbol", "d", "c"]).pivot(index="d", columns="symbol", values="c").sort_index()
    idx_ret = idx.pct_change().iloc[-sessions:]
    out = {}
    for sym in px.columns:
        b = calc_beta(px[sym].pct_change().iloc[-sessions:], idx_ret)
        if b is not None:
            out[sym] = b
    return out


async def step_risk_total(db: AsyncSession) -> dict:
    """Total risk score per stock (6 components, engines.risk.total_risk) + risk-adjusted ranking scores on the latest
    stock_scores row; risk ≥ downgrade_from lowers the rating one step (also in the in-process score cache)."""
    stocks = await _active_symbols(db)
    symbols = [s.symbol for s in stocks]
    d = (await db.execute(select(func.max(IndicatorDaily.trade_date)))).scalar()
    if d is None:
        return {"scored": 0}
    ind = await _latest_rows(db, IndicatorDaily, symbols, since=d - timedelta(days=7))
    scores = await _latest_rows(db, StockScore, symbols, since=d - timedelta(days=7))
    weights = await get_config(db, "risk.score_weights")
    params = await get_config(db, "risk.score_params")
    min_liq = float(await get_config(db, "market.min_liquidity") or 0)
    dates = [x for (x,) in (await db.execute(select(IndicatorDaily.trade_date).distinct().order_by(desc(IndicatorDaily.trade_date)).limit(21))).all()]
    d20 = dates[-1] if len(dates) >= 21 else None
    close20 = dict((await db.execute(select(IndicatorDaily.symbol, IndicatorDaily.close).where(IndicatorDaily.trade_date == d20, IndicatorDaily.symbol.in_(symbols)))).all()) if d20 else {}
    dd = dict((await db.execute(text("""SELECT symbol, -min(close / nullif(mx, 0) - 1) * 100 FROM (
        SELECT symbol, close, max(close) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) mx
        FROM price_daily WHERE trade_date >= :since) t GROUP BY symbol"""), {"since": d - timedelta(days=365)})).all())
    risks = {r.symbol: r.score for r in (await db.execute(select(CompanyRiskScore).where(CompanyRiskScore.symbol.in_(symbols)))).scalars()}
    news = dict((await db.execute(text("""SELECT l.symbol, count(*) FROM news_stock_links l JOIN news_articles a ON a.id = l.article_id
                                           WHERE a.published_at >= now() - interval '7 days' GROUP BY 1"""))).all())
    today = today_vn()
    ex = {sym: (x - today).days for sym, x in (await db.execute(select(CorporateAction.symbol, func.min(CorporateAction.ex_date)).where(CorporateAction.ex_date >= today, CorporateAction.kind.in_(["CASH_DIVIDEND", "STOCK_DIVIDEND", "BONUS", "ISSUE"])).group_by(CorporateAction.symbol))).all()}
    agm = {sym: (x - today).days for sym, x in (await db.execute(select(CorporateAction.symbol, func.min(CorporateAction.event_date)).where(CorporateAction.event_date >= today, CorporateAction.kind.in_(["AGM", "AGM_RECORD"])).group_by(CorporateAction.symbol))).all()}
    if not _BETA_CACHE:  # standalone run (recompute / admin "chạy lại"): rs_beta did not run in this process
        _BETA_CACHE.update(await _betas_from_prices(db, symbols))
    filing, expiry = _days_to_filing_deadline(today), _days_to_derivatives_expiry(today)
    downgrade_from = float(params.get("downgrade_from", 70))
    n = levels = 0
    counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
    for s in stocks:
        i, sc = ind.get(s.symbol), scores.get(s.symbol)
        if not i or not sc:
            continue
        c20 = close20.get(s.symbol)
        res = total_risk({
            "price": i.close, "atr14": i.atr14, "drawdown_12m_pct": dd.get(s.symbol), "value_ma20": i.value_ma20, "min_liquidity_vnd": min_liq,
            "company_risk": risks.get(s.symbol), "gain_20d_pct": (i.close / c20 - 1) * 100 if c20 and i.close else None, "ceiling_streak": i.ceiling_streak,
            "vol_ratio": i.vol_ratio, "free_float_pct": s.free_float_pct, "news_count_7d": news.get(s.symbol, 0), "earnings_in_days": filing,
            "ex_date_in_days": ex.get(s.symbol), "agm_in_days": agm.get(s.symbol), "expiry_in_days": expiry, "in_vn30": s.in_vn30,
            "beta_60": _BETA_CACHE.get(s.symbol),
        }, weights, params)
        sc.risk_total, sc.risk_total_level, sc.risk_components = res["score"], res["level"], res["components"]
        if res["score"] >= downgrade_from:
            sc.rating_short, sc.rating_mid, sc.rating_long = downgrade(sc.rating_short), downgrade(sc.rating_mid), downgrade(sc.rating_long)
            levels += 1
        sc.score_adj_short, sc.score_adj_mid, sc.score_adj_long = risk_adjusted(sc.score_short, res["score"]), risk_adjusted(sc.score_mid, res["score"]), risk_adjusted(sc.score_long, res["score"])
        cache = _SCORE_CACHE.get(s.symbol)
        if cache is not None:
            cache.update(rating_short=sc.rating_short, rating_mid=sc.rating_mid, rating_long=sc.rating_long, risk_total=res["score"], risk_total_level=res["level"])
        counts[res["level"]] += 1
        n += 1
    await db.flush()
    return {"scored": n, "downgraded": levels, **{k.lower(): v for k, v in counts.items()}, "summary": f"{n} mã · thấp {counts['LOW']}, trung bình {counts['MEDIUM']}, cao {counts['HIGH']} · hạ bậc {levels}"}



def _trend3(i: IndicatorDaily) -> tuple[str, str, str]:
    c = i.close

    def t(ma, slope=None):
        if not ma:
            return "FLAT"
        if c > ma * 1.01 and (slope is None or slope >= 0):
            return "UP"
        if c < ma * 0.99 and (slope is None or slope <= 0):
            return "DOWN"
        return "FLAT"

    return t(i.ma10), t(i.ma50, i.ma50_slope), t(i.ma200, i.ma200_slope)


def _reasons(i: IndicatorDaily, r: FinancialRatio | None, b: PriceBase | None, rl: RallyStat | None, gain: float | None, risk, sector_score: float, s: Stock) -> tuple[list, list]:
    reasons, draw = [], []
    if i.ma50 and i.ma200 and i.close > i.ma50 > i.ma200:
        reasons.append({"code": "TREND", "text": "Giá > MA50 > MA200" + (", MA200 dốc lên" if (i.ma200_slope or 0) > 0 else "")})
    elif i.ma50 and i.close > i.ma50:
        reasons.append({"code": "TREND", "text": "Giá đang trên MA50"})
    elif i.ma50 and i.close < i.ma50:
        draw.append({"code": "TREND", "text": "Giá dưới MA50" + (" và MA200" if i.ma200 and i.close < i.ma200 else "")})
    if b and b.status == "BROKEN_OUT" and gain is not None:
        reasons.append({"code": "BREAKOUT_BASE", "text": f"Phá nền {b.length_days} phiên, KL gấp {b.breakout_vol_ratio or 0:.1f} lần TB20, đã tăng {gain:.0f}% từ nền"})
    elif b and b.status == "FORMING":
        reasons.append({"code": "BASE", "text": f"Đang đi nền {b.length_days} phiên, biên độ {b.depth_pct:.0f}%" + (", nền chặt" if (b.tightness_pct or 9) < 3 else "")})
    if i.rs_rating and i.rs_rating >= 80:
        reasons.append({"code": "RS", "text": f"Sức mạnh tương đối RS {i.rs_rating:.0f}, mạnh hơn {i.rs_rating:.0f}% thị trường"})
    elif i.rs_rating and i.rs_rating <= 30:
        draw.append({"code": "RS", "text": f"RS {i.rs_rating:.0f}, yếu hơn thị trường"})
    if i.rsi14 and i.rsi14 > 75:
        draw.append({"code": "RSI", "text": f"RSI {i.rsi14:.0f} quá mua"})
    if (i.distribution_days or 0) >= 4:
        draw.append({"code": "DIST", "text": f"{i.distribution_days} phiên phân phối trong 20 phiên"})
    if r:
        if r.profit_yoy is not None and r.profit_yoy >= 20:
            reasons.append({"code": "EARNINGS", "text": f"LNST quý gần nhất {r.profit_yoy:+.0f}% so cùng kỳ"})
        elif r.profit_yoy is not None and r.profit_yoy < 0:
            draw.append({"code": "EARNINGS", "text": f"LNST quý gần nhất {r.profit_yoy:+.0f}% so cùng kỳ"})
        if r.roe is not None and r.roe >= 15:
            reasons.append({"code": "ROE", "text": f"ROE {r.roe:.0f}%"})
        if r.margin_of_safety is not None and r.margin_of_safety >= 20:
            reasons.append({"code": "VALUE", "text": f"Giá thấp hơn giá trị thực {r.margin_of_safety:.0f}%"})
        elif r.margin_of_safety is not None and r.margin_of_safety <= -25:
            draw.append({"code": "VALUE", "text": f"Định giá cao hơn giá trị thực {-r.margin_of_safety:.0f}%"})
        if r.pe and r.pe > 30:
            draw.append({"code": "PE", "text": f"P/E {r.pe:.1f} cao"})
    if rl and rl.rally_count and rl.median_gain_pct and gain is not None:
        reasons.append({"code": "RALLY", "text": f"{rl.rally_count} đợt tăng trước tăng trung vị {rl.median_gain_pct:.0f}% từ nền"})
    if sector_score >= 65:
        reasons.append({"code": "SECTOR", "text": "Ngành đang hút dòng tiền"})
    if risk and risk.score >= 60:
        draw.append({"code": "RISK", "text": f"Điểm rủi ro doanh nghiệp {risk.score:.0f}/100"})
    if s.status_flags:
        draw.append({"code": "STATUS", "text": "Cổ phiếu thuộc diện cảnh báo/kiểm soát"})
    return reasons[:5], draw[:3]


async def step_company_risk(db: AsyncSession) -> dict:
    from app.ingestion.extras import risk_inputs

    stocks = await _active_symbols(db)
    ratios = {r.symbol: r for r in (await db.execute(select(FinancialRatio).where(FinancialRatio.symbol.in_([s.symbol for s in stocks])))).scalars()}
    extra = await risk_inputs(db)
    as_of = last_closed_trading_day()
    n = 0
    for s in stocks:
        r = ratios.get(s.symbol)
        rd = {c: getattr(r, c) for c in ("cfo_negative_quarters", "eps_ttm", "receivable_gap_pt", "inventory_gap_pt", "market_cap", "dilution_pct", "debt_to_equity")} if r else {}
        x = extra.get(s.symbol, {})
        if x.get("dilution_pct"):
            rd["dilution_pct"] = x["dilution_pct"]
        res = company_risk(rd, {"status_flags": s.status_flags, "is_bank": s.is_bank}, insider_net_sell_vnd=x.get("insider_net_sell_vnd", 0.0),
                           audit_qualified=bool(x.get("audit_qualified")), late_filing=bool(x.get("late_filing")))
        vals = dict(as_of=as_of, score=res["score"], level=res["level"], flags=res["flags"])
        stmt = insert(CompanyRiskScore).values(symbol=s.symbol, **vals)
        await db.execute(stmt.on_conflict_do_update(index_elements=["symbol"], set_=vals))
        n += 1
    await db.flush()
    return {"scored": n}


async def step_signals(db: AsyncSession) -> dict:
    stocks = await _active_symbols(db)
    symbols = [s.symbol for s in stocks]
    d = (await db.execute(select(func.max(IndicatorDaily.trade_date)))).scalar()
    params = await get_config(db, "strategy.params")
    risk_th = await get_config(db, "risk.company_thresholds")
    min_liq = float(await get_config(db, "market.min_liquidity") or 0)
    regime_row = (await db.execute(select(MarketRegime).order_by(desc(MarketRegime.trade_date)).limit(1))).scalar_one_or_none()
    regime = regime_row.regime if regime_row else "UPTREND"
    enabled = {s.code: s for s in (await db.execute(select(Strategy).where(Strategy.enabled))).scalars()}
    rel = {(r.strategy_code, r.regime, r.horizon): r for r in (await db.execute(select(SignalReliability).where(SignalReliability.days == 20))).scalars()}
    risk_rows = {r.symbol: r.score for r in (await db.execute(select(CompanyRiskScore).where(CompanyRiskScore.symbol.in_(symbols)))).scalars()}
    rallies = {r.symbol: r for r in (await db.execute(select(RallyStat).where(RallyStat.symbol.in_(symbols)))).scalars()}
    bases = {}
    for b in (await db.execute(select(PriceBase).where(PriceBase.symbol.in_(symbols), PriceBase.status.in_(["FORMING", "BROKEN_OUT"])).order_by(PriceBase.symbol, desc(PriceBase.start_date)))).scalars():
        bases.setdefault(b.symbol, b)
    since = d - timedelta(days=130)
    n_new = 0
    for i in range(0, len(symbols), 150):
        batch = symbols[i : i + 150]
        rows = (await db.execute(select(IndicatorDaily).where(IndicatorDaily.symbol.in_(batch), IndicatorDaily.trade_date >= since).order_by(IndicatorDaily.symbol, IndicatorDaily.trade_date))).scalars().all()
        by: dict[str, list] = {}
        for r in rows:
            by.setdefault(r.symbol, []).append(r)
        for sym, hist in by.items():
            last = hist[-1]
            if (d - last.trade_date).days > 7 or len(hist) < 30:
                continue
            if (last.value_ma20 or 0) < min_liq:
                continue
            sc = _SCORE_CACHE.get(sym) or {}
            b = bases.get(sym)
            ind_df = pd.DataFrame([{c: getattr(h, c) for c in ("close", "ma50", "ma200", "rsi14", "high_52w")} for h in hist], index=[h.trade_date for h in hist])
            snap = {"price": last.close, **{c: getattr(last, c) for c in OUTPUT_COLS if c != "close"},
                    "base_status": b.status if b else None, "base_length_days": b.length_days if b else None, "base_tightness": b.tightness_pct if b else None,
                    "base_high": b.base_high if b else None, "gain_from_base_pct": sc.get("gain_from_base_pct"),
                    "breakout_days": ((d - b.breakout_date).days if b and b.breakout_date else 99),
                    "roe": None, "profit_yoy": None, "margin_of_safety": None}
            ratio = await db.get(FinancialRatio, sym)
            if ratio:
                snap.update({"roe": ratio.roe, "profit_yoy": ratio.profit_yoy, "margin_of_safety": ratio.margin_of_safety})
            rl = rallies.get(sym)
            cands = strat.evaluate(snap, ind_df, {"median_gain_pct": rl.median_gain_pct, "rally_count": rl.rally_count, "median_peak_vol_ratio": rl.median_peak_vol_ratio} if rl else None, params)
            risk_score = risk_rows.get(sym, 0.0)
            for c in cands:
                code = c["strategy_code"]
                st = enabled.get(code)
                if not st:
                    continue
                if st.signal_type == "BUY" and risk_score >= risk_th.get("no_buy", 80):
                    continue
                if st.signal_type == "BUY" and regime == "DOWNTREND" and st.horizon == "SHORT":
                    continue
                hz = st.horizon
                rating = sc.get(f"rating_{hz.lower()}")
                score = sc.get(f"score_{hz.lower()}")
                r = rel.get((code, regime, hz))
                stand_aside, _ = reliability_label(r.win_rate if r else None, r.samples if r else None)
                is_chase = st.signal_type == "BUY" and strat.is_chase(sc.get("gain_from_base_pct"), last.ceiling_streak, hz, params)
                dedupe = f"{sym}:{code}:{last.trade_date.isoformat()}"
                exists = await db.scalar(select(Signal.id).where(Signal.dedupe_key == dedupe))
                if exists:
                    continue
                priority = "URGENT" if st.signal_type == "STOP_LOSS" else ("HIGH" if st.signal_type in ("BUY", "SELL", "TAKE_PROFIT") else "INFO")
                sig = Signal(symbol=sym, trade_date=last.trade_date, strategy_code=code, signal_type=st.signal_type, horizon=hz, rating=rating, score=score, price=last.close,
                             entry_low=sc.get("entry_low"), entry_high=sc.get("entry_high"), stop_loss=sc.get("stop_loss"), take_profit_1=sc.get("take_profit_1"),
                             take_profit_2=sc.get("take_profit_2"), risk_reward=sc.get("risk_reward"), priority=priority, regime_at_signal=regime,
                             reliability_pct=r.win_rate if r and r.samples >= 30 else None, reliability_samples=r.samples if r else None,
                             stand_aside=stand_aside, is_chase=is_chase, risk_score=risk_score,
                             title=strat.signal_title(code, sym, snap, c["facts"], hz, RATING_VI.get(rating) if st.signal_type == "BUY" else None),
                             reasons=(sc.get("reasons") or [])[:4], facts=c["facts"], dedupe_key=dedupe)
                db.add(sig)
                n_new += 1
        await db.flush()
    return {"signals": n_new, "date": d.isoformat()}


async def step_snapshot(db: AsyncSession) -> dict:
    stocks = await _active_symbols(db)
    symbols = [s.symbol for s in stocks]
    d = (await db.execute(select(func.max(IndicatorDaily.trade_date)))).scalar()
    ind = await _latest_rows(db, IndicatorDaily, symbols, since=d - timedelta(days=7))
    prev_ind = {}
    for r in (await db.execute(select(IndicatorDaily).where(IndicatorDaily.symbol.in_(symbols), IndicatorDaily.trade_date >= d - timedelta(days=20)).order_by(IndicatorDaily.symbol, desc(IndicatorDaily.trade_date)))).scalars():
        if r.symbol in ind and r.trade_date < ind[r.symbol].trade_date and r.symbol not in prev_ind:
            prev_ind[r.symbol] = r
    ratios = {r.symbol: r for r in (await db.execute(select(FinancialRatio).where(FinancialRatio.symbol.in_(symbols)))).scalars()}
    risks = {r.symbol: r for r in (await db.execute(select(CompanyRiskScore).where(CompanyRiskScore.symbol.in_(symbols)))).scalars()}
    rallies = {r.symbol: r for r in (await db.execute(select(RallyStat).where(RallyStat.symbol.in_(symbols)))).scalars()}
    scores = await _latest_rows(db, StockScore, symbols, since=d - timedelta(days=7))
    sigs: dict[str, list] = {}
    for s in (await db.execute(select(Signal).where(Signal.trade_date >= d - timedelta(days=5)))).scalars():
        sigs.setdefault(s.symbol, []).append({"code": s.strategy_code, "type": s.signal_type, "date": s.trade_date.isoformat()})
    prev_snap = {r.symbol: r for r in (await db.execute(select(StockSnapshot).where(StockSnapshot.symbol.in_(symbols)))).scalars()}
    # cross events: sessions since MA50/MA200 cross from indicator history (last 15 rows)
    cross_rows = (await db.execute(select(IndicatorDaily.symbol, IndicatorDaily.trade_date, IndicatorDaily.ma50, IndicatorDaily.ma200).where(IndicatorDaily.symbol.in_(symbols), IndicatorDaily.trade_date >= d - timedelta(days=25)).order_by(IndicatorDaily.symbol, IndicatorDaily.trade_date))).all()
    cross: dict[str, tuple[int | None, int | None]] = {}
    buf: dict[str, list] = {}
    for sym, td, m50, m200 in cross_rows:
        buf.setdefault(sym, []).append((m50, m200))
    for sym, seq in buf.items():
        g = dd = None
        diffs = [(a - b) if a and b else None for a, b in seq]
        for k in range(len(diffs) - 1, 0, -1):
            if diffs[k] is None or diffs[k - 1] is None:
                continue
            if diffs[k] > 0 and diffs[k - 1] <= 0:
                g = len(diffs) - 1 - k
                break
            if diffs[k] < 0 and diffs[k - 1] >= 0:
                dd = len(diffs) - 1 - k
                break
        cross[sym] = (g, dd)
    # upcoming events
    ev = {}
    for sym, ex in (await db.execute(select(CorporateAction.symbol, func.min(CorporateAction.ex_date)).where(CorporateAction.ex_date >= today_vn(), CorporateAction.symbol.in_(symbols)).group_by(CorporateAction.symbol))).all():
        ev[sym] = (ex - today_vn()).days
    n = 0
    rating_changes = []
    for s in stocks:
        i = ind.get(s.symbol)
        if not i:
            continue
        pi = prev_ind.get(s.symbol)
        sc = scores.get(s.symbol)
        r = ratios.get(s.symbol)
        rk = risks.get(s.symbol)
        rl = rallies.get(s.symbol)
        cache = _SCORE_CACHE.get(s.symbol, {})
        b = cache.get("base")
        ref = pi.close if pi else i.close
        lim = {"HOSE": 0.07, "HNX": 0.10, "UPCOM": 0.15}.get(s.exchange, 0.07)
        prev = prev_snap.get(s.symbol)
        rating_mid = sc.rating_mid if sc else None
        prev_rating = prev.rating if prev and prev.trade_date != i.trade_date else (prev.prev_rating if prev else None)
        changed = bool(prev_rating and rating_mid and prev_rating != rating_mid)
        g, dd = cross.get(s.symbol, (None, None))
        gain = cache.get("gain_from_base_pct")
        vals = dict(
            trade_date=i.trade_date, exchange=s.exchange, industry_code=s.industry_code, in_vn30=s.in_vn30, price=i.close, change=(i.close - ref) if ref else None, change_pct=i.change_pct,
            ref_price=ref, ceiling=ref * (1 + lim) if ref else None, floor=ref * (1 - lim) if ref else None, volume=None, value=None,
            vol_ratio=i.vol_ratio, value_ma20=i.value_ma20, high_52w=i.high_52w, low_52w=i.low_52w, ma10=i.ma10, ma20=i.ma20, ma50=i.ma50, ma200=i.ma200, rsi14=i.rsi14,
            macd=i.macd, macd_signal=i.macd_signal, macd_hist=i.macd_hist, adx14=i.adx14, atr14=i.atr14, bb_upper=i.bb_upper, bb_lower=i.bb_lower, bb_width=i.bb_width,
            mfi14=i.mfi14, cmf20=i.cmf20, stoch_k=i.stoch_k, rs_rating=i.rs_rating, trend_state=i.trend_state, support_1=i.support_1, resistance_1=i.resistance_1,
            dist_ma50_pct=i.dist_ma50_pct, ma50_slope=i.ma50_slope, ceiling_streak=i.ceiling_streak, golden_cross_days=g, death_cross_days=dd,
            pe=r.pe if r else None, pb=r.pb if r else None, ps=r.ps if r else None, peg=r.peg if r else None, market_cap=r.market_cap if r else None,
            fair_value=r.fair_value if r else None, margin_of_safety=r.margin_of_safety if r else None, dividend_yield=r.dividend_yield if r else None,
            roe=r.roe if r else None, roa=r.roa if r else None, gross_margin=r.gross_margin if r else None, net_margin=r.net_margin if r else None,
            debt_to_equity=r.debt_to_equity if r else None, current_ratio=r.current_ratio if r else None, revenue_yoy=r.revenue_yoy if r else None,
            profit_yoy=r.profit_yoy if r else None, revenue_cagr_3y=r.revenue_cagr_3y if r else None, profit_cagr_3y=r.profit_cagr_3y if r else None,
            cfo_to_profit=r.cfo_to_profit if r else None,
            score_short=sc.score_short if sc else None, score_mid=sc.score_mid if sc else None, score_long=sc.score_long if sc else None,
            rating_short=sc.rating_short if sc else None, rating_mid=rating_mid, rating_long=sc.rating_long if sc else None, rating=rating_mid,
            trend_short=sc.trend_short if sc else None, trend_mid=sc.trend_mid if sc else None, trend_long=sc.trend_long if sc else None,
            base_status=b.status if b else None, base_length_days=b.length_days if b else None, base_tightness=b.tightness_pct if b else None, base_high=b.base_high if b else None,
            gain_from_base_pct=gain, rally_gain_vs_median=(gain / rl.median_gain_pct * 100) if (gain is not None and rl and rl.median_gain_pct) else None,
            risk_score=rk.score if rk else None, risk_level=rk.level if rk else None, beta_60=_BETA_CACHE.get(s.symbol), earnings_in_days=ev.get(s.symbol),
            risk_total=sc.risk_total if sc else None, risk_total_level=sc.risk_total_level if sc else None, risk_components=sc.risk_components if sc else None,
            score_adj_short=sc.score_adj_short if sc else None, score_adj_mid=sc.score_adj_mid if sc else None, score_adj_long=sc.score_adj_long if sc else None,
            is_chase=cache.get("is_chase"), signals_today=sigs.get(s.symbol, []), entry_low=sc.entry_low if sc else None, entry_high=sc.entry_high if sc else None,
            stop_loss=sc.stop_loss if sc else None, take_profit_1=sc.take_profit_1 if sc else None, rating_changed=changed, prev_rating=prev_rating if changed else (prev.prev_rating if prev and not changed and prev.trade_date == i.trade_date else prev_rating),
        )
        # volume/value from price_daily latest
        vals = {k: _f(v) for k, v in vals.items()}
        stmt = insert(StockSnapshot).values(symbol=s.symbol, **vals)
        await db.execute(stmt.on_conflict_do_update(index_elements=["symbol"], set_=vals))
        if changed:
            rating_changes.append((s.symbol, prev_rating, rating_mid))
        n += 1
    await db.execute(text("""UPDATE stock_snapshots ss SET volume=p.volume, value=p.value FROM price_daily p
                             WHERE p.symbol=ss.symbol AND p.trade_date=ss.trade_date"""))
    await db.flush()
    _RATING_CHANGES.clear()
    _RATING_CHANGES.extend(rating_changes)
    return {"snapshots": n, "rating_changes": len(rating_changes)}


_RATING_CHANGES: list[tuple[str, str, str]] = []


async def step_outcomes(db: AsyncSession, limit: int = 3000) -> dict:
    """Evaluate signal outcomes after 5/10/20/60 sessions and refresh reliability (4.6k)."""
    d = last_closed_trading_day()
    n = 0
    for days in (5, 10, 20, 60):
        cutoff = d - timedelta(days=int(days * 1.45) + 3)
        done = select(SignalOutcome.signal_id).where(SignalOutcome.days == days)
        sigs = (await db.execute(select(Signal).where(Signal.trade_date <= cutoff, Signal.id.notin_(done)).order_by(Signal.trade_date).limit(limit))).scalars().all()
        for s in sigs:
            rows = (await db.execute(select(PriceDaily.close, PriceDaily.high, PriceDaily.low).where(PriceDaily.symbol == s.symbol, PriceDaily.trade_date > s.trade_date).order_by(PriceDaily.trade_date).limit(days))).all()
            if len(rows) < days:
                continue
            closes = [r[0] for r in rows]
            ret = (closes[-1] / s.price - 1) * 100
            mg = (max(r[1] for r in rows) / s.price - 1) * 100
            ml = (min(r[2] for r in rows) / s.price - 1) * 100
            hit_tp = bool(s.take_profit_1 and any(r[1] >= s.take_profit_1 for r in rows))
            hit_stop = bool(s.stop_loss and any(r[2] <= s.stop_loss for r in rows))
            if hit_tp and hit_stop:
                # which first?
                first_tp = next(k for k, r in enumerate(rows) if r[1] >= s.take_profit_1)
                first_sl = next(k for k, r in enumerate(rows) if r[2] <= s.stop_loss)
                hit_tp, hit_stop = first_tp <= first_sl, first_sl < first_tp
            if s.signal_type in ("SELL", "TAKE_PROFIT"):
                result = "WIN" if ret < 0 else "LOSS"
            else:
                result = "TP_HIT" if hit_tp else ("STOP_HIT" if hit_stop else ("WIN" if ret > 0 else "LOSS"))
            db.add(SignalOutcome(signal_id=s.id, days=days, return_pct=round(ret, 2), max_gain_pct=round(mg, 2), max_loss_pct=round(ml, 2), hit_tp1=hit_tp, hit_stop=hit_stop, result=result))
            n += 1
        await db.flush()
    rel = await refresh_reliability(db)
    return {"outcomes": n, "reliability_rows": rel}


async def refresh_reliability(db: AsyncSession) -> int:
    rows = (await db.execute(text("""
        SELECT s.strategy_code, s.regime_at_signal AS regime, s.horizon, o.days, count(*) AS samples,
               avg(case when o.result in ('TP_HIT','WIN') then 1.0 else 0.0 end)*100 AS win_rate, avg(o.return_pct) AS avg_return,
               avg(case when o.result = 'STOP_HIT' or o.hit_stop then 1.0 else 0.0 end)*100 AS stop_rate,
               avg(case when o.result = 'TP_HIT' or o.hit_tp1 then 1.0 else 0.0 end)*100 AS tp1_rate,
               percentile_cont(0.05) WITHIN GROUP (ORDER BY o.return_pct) AS p05_return, min(o.return_pct) AS worst_return,
               avg(o.return_pct) FILTER (WHERE o.return_pct > 0) AS avg_gain, avg(o.return_pct) FILTER (WHERE o.return_pct < 0) AS avg_loss
        FROM signals s JOIN signal_outcomes o ON o.signal_id = s.id
        WHERE s.regime_at_signal IS NOT NULL GROUP BY 1,2,3,4"""))).all()
    f2 = lambda x: round(float(x), 2) if x is not None else None
    for r in rows:
        vals = dict(samples=int(r.samples), win_rate=round(float(r.win_rate), 1), avg_return=round(float(r.avg_return), 2), stop_rate=f2(r.stop_rate), tp1_rate=f2(r.tp1_rate),
                    p05_return=f2(r.p05_return), worst_return=f2(r.worst_return), avg_gain=f2(r.avg_gain), avg_loss=f2(r.avg_loss))
        stmt = insert(SignalReliability).values(strategy_code=r.strategy_code, regime=r.regime, horizon=r.horizon, days=int(r.days), **vals)
        await db.execute(stmt.on_conflict_do_update(index_elements=["strategy_code", "regime", "horizon", "days"], set_=vals))
    # strategy aggregate
    agg = (await db.execute(text("""
        SELECT s.strategy_code, count(*) n, avg(case when o.result in ('TP_HIT','WIN') then 1.0 else 0.0 end)*100 wr, avg(o.return_pct) ar, min(o.return_pct) mdd
        FROM signals s JOIN signal_outcomes o ON o.signal_id=s.id AND o.days=20 GROUP BY 1"""))).all()
    for r in agg:
        st = await db.get(Strategy, r.strategy_code)
        if st:
            st.trades, st.win_rate, st.avg_return, st.max_drawdown = int(r.n), round(float(r.wr), 1), round(float(r.ar), 2), round(float(r.mdd), 2)
    await db.flush()
    return len(rows)


async def step_presets(db: AsyncSession) -> dict:
    from app.screener.dsl import to_sql
    from app.screener.presets import build_dsl

    presets = (await db.execute(select(Screener).where(Screener.is_preset))).scalars().all()
    d = await db.scalar(select(func.max(StockSnapshot.trade_date)))
    for p in presets:
        dsl = build_dsl(p.conditions.get("all", []) if p.form_state is not None else [], p.form_state, p.horizon) if p.form_state is not None else p.conditions
        try:
            col = {"SHORT": StockSnapshot.score_short, "LONG": StockSnapshot.score_long}.get(p.horizon, StockSnapshot.score_mid)
            syms = [s for (s,) in (await db.execute(select(StockSnapshot.symbol).where(to_sql(dsl)).order_by(desc(col)).limit(200))).all()]
            p.last_result = {"count": len(syms), "symbols": syms[:50], "date": d.isoformat() if d else None}
        except Exception as e:  # noqa: BLE001
            log.warning("preset %s failed: %s", p.code, e)
    await db.flush()
    return {"presets": len(presets)}


async def step_explain(db: AsyncSession) -> dict:
    """AI conclusions for symbols with a signal today (budgeted), stored in stock_scores.reasons[0] as 'AI' entry."""
    if not await get_config(db, "signals.explain_with_ai") or not ai.available():
        return {"explained": 0, "summary": "AI off"}
    d = await db.scalar(select(func.max(Signal.trade_date)))
    sigs = (await db.execute(select(Signal).where(Signal.trade_date == d, Signal.signal_type.in_(["BUY", "TAKE_PROFIT", "SELL"])).order_by(desc(Signal.score)).limit(60))).scalars().all()
    items, seen = [], set()
    for s in sigs:
        if s.symbol in seen:
            continue
        seen.add(s.symbol)
        snap = await db.get(StockSnapshot, s.symbol)
        if not snap:
            continue
        items.append({"symbol": s.symbol, "signal": s.title, "price": snap.price, "score_mid": snap.score_mid, "rating": RATING_VI.get(snap.rating), "trend": snap.trend_state,
                      "rsi14": snap.rsi14, "dist_ma50_pct": snap.dist_ma50_pct, "pe": snap.pe, "roe": snap.roe, "profit_yoy": snap.profit_yoy, "risk_score": snap.risk_score,
                      "reasons": [r["text"] for r in (s.reasons or [])]})
    texts = await ai.explain_stocks(items)
    n = 0
    for sym, t in texts.items():
        sc = await db.get(StockScore, (sym, d))
        if sc:
            sc.reasons = [{"code": "AI", "text": t}] + [r for r in (sc.reasons or []) if r.get("code") != "AI"]
            n += 1
    await db.flush()
    return {"explained": n}


# ------------------------------------------------------------------ chain
# Vietnamese label + nominal start time per step (A01 "chuỗi xử lý cuối ngày"; chain starts 15:05).
EOD_STEP_INFO: dict[str, tuple[str, str]] = {
    "eod.universe": ("Cập nhật danh sách mã", "15:05"),
    "eod.prices": ("Lấy giá đóng cửa", "15:06"),
    "eod.extras": ("Sự kiện, giao dịch nội bộ, dòng tiền", "15:10"),
    "eod.indicators": ("Tính chỉ báo kỹ thuật", "15:15"),
    "eod.bases": ("Nền giá, đợt tăng", "15:20"),
    "eod.rs_beta": ("Sức mạnh tương đối, beta", "15:25"),
    "eod.ratios": ("Chỉ số tài chính, định giá", "15:28"),
    "eod.regime": ("Trạng thái thị trường", "15:30"),
    "eod.sectors": ("Điểm ngành", "15:32"),
    "eod.company_risk": ("Điểm rủi ro doanh nghiệp", "15:34"),
    "eod.scores": ("Chấm điểm 3 khung", "15:36"),
    "eod.risk_total": ("Điểm rủi ro tổng hợp", "15:38"),
    "eod.signals": ("Chạy chiến lược, phát tín hiệu", "15:40"),
    "eod.snapshot": ("Ghi ảnh chụp cuối ngày", "15:45"),
    "eod.enrich": ("Bổ sung tin tức, khuyến nghị CTCK", "15:48"),
    "eod.outcomes": ("Cập nhật kết quả tín hiệu", "15:50"),
    "eod.presets": ("Đếm mã khớp bộ lọc mẫu", "15:52"),
    "eod.explain": ("AI viết nhận định", "15:55"),
    "eod.users": ("Đánh giá cảnh báo, gửi báo cáo cuối ngày", "16:00"),
}

EOD_STEPS = [
    ("eod.universe", step_universe),
    ("eod.prices", step_prices),
    ("eod.extras", step_extras),
    ("eod.indicators", step_indicators),
    ("eod.bases", step_bases),
    ("eod.rs_beta", step_rs_beta),
    ("eod.ratios", step_ratios),
    ("eod.regime", step_regime),
    ("eod.sectors", step_sectors),
    ("eod.company_risk", step_company_risk),
    ("eod.scores", step_scores),
    ("eod.risk_total", step_risk_total),
    ("eod.signals", step_signals),
    ("eod.snapshot", step_snapshot),
    ("eod.enrich", step_enrich),
    ("eod.outcomes", step_outcomes),
    ("eod.presets", step_presets),
    ("eod.explain", step_explain),
    ("eod.users", None),  # filled by tasks.alerts
]


async def run_eod(triggered_by: str = "scheduler", skip_ingest: bool = False, only: list[str] | None = None) -> list:
    from app.tasks.alerts import step_users

    results = []
    for name, fn in EOD_STEPS:
        if only and name not in only:
            continue
        if skip_ingest and name in ("eod.universe", "eod.prices", "eod.extras"):
            continue
        if fn is None:
            fn = step_users
        job = await run_job(name, fn, triggered_by)
        results.append(job)
        if job.status == "FAILED" and name in ("eod.prices", "eod.indicators"):
            log.error("EOD aborted at %s", name)
            break
    return results

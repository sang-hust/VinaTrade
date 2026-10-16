"""Sync of the free sources added 16/10/2026: corporate events + market alerts (VNDirect), foreign & proprietary flows
(VNDirect), broker recommendations (VNDirect), insider deals (Vietcap), news RSS (CafeF, Vietstock, VnExpress, VnEconomy).
See docs/NGUON-DU-LIEU.md."""

import asyncio
import json
import logging
import re
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vntime import is_trading_day, last_closed_trading_day, today_vn
from app.ingestion.adapters.rss import FEEDS, RSSAdapter
from app.ingestion.adapters.vci import VCIAdapter
from app.ingestion.adapters.vndirect import VNDirectAdapter
from app.ingestion.universe import mark_source
from app.models import BrokerRecommendation, CorporateAction, InsiderTransaction, InvestorFlow, NewsArticle, NewsStockLink, Stock

log = logging.getLogger(__name__)


def _date(v):
    if v is None or isinstance(v, date):
        return v
    try:
        return datetime.fromisoformat(str(v)[:10]).date()
    except ValueError:
        return None


# ------------------------------------------------------------------ events
async def sync_events(db: AsyncSession, since: date | None = None, field: str = "disclosureDate") -> dict:
    since = since or today_vn() - timedelta(days=10)
    v = VNDirectAdapter(timeout=40)
    try:
        rows = await v.events(since, field=field)
        await mark_source(db, "VND", True)
    except Exception as e:  # noqa: BLE001
        await mark_source(db, "VND", False, str(e))
        raise
    finally:
        await v.close()
    active = {s for (s,) in (await db.execute(select(Stock.symbol))).all()}
    rows = [r for r in rows if r["symbol"] in active]
    cols = [c for c in rows[0] if c != "external_id"] if rows else []
    for i in range(0, len(rows), 300):
        chunk = rows[i : i + 300]
        stmt = insert(CorporateAction).values(chunk)
        await db.execute(stmt.on_conflict_do_update(index_elements=["external_id"], set_={c: getattr(stmt.excluded, c) for c in cols}))
    await db.flush()
    kinds: dict[str, int] = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    return {"events": len(rows), "kinds": kinds}


# ------------------------------------------------------------------ flows
async def sync_flows(db: AsyncSession, days: list[date] | None = None) -> dict:
    days = days or [last_closed_trading_day()]
    v = VNDirectAdapter(timeout=40)
    n = 0
    try:
        for d in days:
            merged: dict[str, dict] = {}
            for r in await v.foreign_flows(d):
                merged.setdefault(r["symbol"], {"symbol": r["symbol"], "trade_date": d}).update(r)
            try:
                for r in await v.proprietary_flows(d):
                    merged.setdefault(r["symbol"], {"symbol": r["symbol"], "trade_date": d}).update(r)
            except Exception as e:  # noqa: BLE001
                log.warning("proprietary %s failed: %s", d, e)
            if not merged:
                continue
            allcols = ["foreign_buy_val", "foreign_sell_val", "foreign_net_val", "foreign_buy_vol", "foreign_sell_vol", "foreign_net_vol", "foreign_room",
                       "prop_buy_val", "prop_sell_val", "prop_net_val"]
            rows = [{"symbol": r["symbol"], "trade_date": d, **{c: r.get(c) for c in allcols}} for r in merged.values()]
            for i in range(0, len(rows), 1000):
                chunk = rows[i : i + 1000]
                stmt = insert(InvestorFlow).values(chunk)
                await db.execute(stmt.on_conflict_do_update(index_elements=["symbol", "trade_date"],
                                                            set_={c: func.coalesce(getattr(stmt.excluded, c), getattr(InvestorFlow, c)) for c in allcols}))
            n += len(rows)
            await db.flush()
        await mark_source(db, "VND", True)
    finally:
        await v.close()
    return {"days": len(days), "rows": n}


def trading_days_back(n: int, end: date | None = None) -> list[date]:
    d = end or last_closed_trading_day()
    out = []
    while len(out) < n:
        if is_trading_day(d):
            out.append(d)
        d -= timedelta(days=1)
    return out


# ------------------------------------------------------------------ recommendations
async def sync_recommendations(db: AsyncSession, since: date | None = None) -> dict:
    since = since or today_vn() - timedelta(days=21)
    v = VNDirectAdapter(timeout=40)
    try:
        rows = await v.recommendations(since)
    finally:
        await v.close()
    seen, uniq = set(), []
    for r in rows:
        k = (r["symbol"], r["firm"], r["report_date"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    for i in range(0, len(uniq), 500):
        chunk = uniq[i : i + 500]
        stmt = insert(BrokerRecommendation).values(chunk)
        await db.execute(stmt.on_conflict_do_update(constraint="uq_broker_rec", set_={c: getattr(stmt.excluded, c) for c in ("rec_type", "report_price", "target_price", "analyst", "source")}))
    await db.flush()
    return {"recommendations": len(uniq)}


# ------------------------------------------------------------------ insiders
async def sync_insiders(db: AsyncSession, symbols: list[str] | None = None, pages: int = 1, concurrency: int = 8, min_value_ma20: float = 1e9) -> dict:
    if symbols is None:
        symbols = [s for (s,) in (await db.execute(text(
            "SELECT symbol FROM stock_snapshots WHERE value_ma20 >= :v UNION SELECT symbol FROM watchlist_items UNION SELECT symbol FROM positions WHERE quantity > 0"), {"v": min_value_ma20})).all()]
    vci = VCIAdapter(timeout=40)
    sem = asyncio.Semaphore(concurrency)
    stats = {"symbols": len(symbols), "rows": 0, "failed": 0}

    async def one(sym):
        async with sem:
            try:
                return await vci.insiders(sym, size=50, pages=pages)
            except Exception as e:  # noqa: BLE001
                log.warning("insiders %s failed: %s", sym, e)
                stats["failed"] += 1
                return []

    try:
        for i in range(0, len(symbols), 40):
            results = await asyncio.gather(*(one(s) for s in symbols[i : i + 40]))
            rows = [r for res in results for r in res]
            for r in rows:
                for k in ("start_date", "end_date", "announce_date"):
                    r[k] = _date(r[k])
            dedup = {r["external_id"]: r for r in rows}
            rows = list(dedup.values())
            if rows:
                cols = [c for c in rows[0] if c != "external_id"]
                for j in range(0, len(rows), 500):
                    chunk = rows[j : j + 500]
                    stmt = insert(InsiderTransaction).values(chunk)
                    await db.execute(stmt.on_conflict_do_update(index_elements=["external_id"], set_={c: getattr(stmt.excluded, c) for c in cols}))
                stats["rows"] += len(rows)
            await db.flush()
        await mark_source(db, "VCI", stats["failed"] < len(symbols) / 2)
    finally:
        await vci.close()
    return stats


# ------------------------------------------------------------------ news
STOP_TICKERS = {"VND", "USD", "CEO", "CFO", "COO", "CTO", "GDP", "ETF", "IPO", "FDI", "CPI", "PMI", "HCM", "EUR", "JPY", "CNY", "ESG", "EPS", "ROE", "ROA",
                "OTC", "VAT", "BOT", "BOO", "KCN", "WTO", "FED", "IMF", "USA", "TPP", "CEO", "AGM", "CTCK", "BCTC", "TTCK", "HNX", "HSX", "TOP", "NEW",
                "THE", "AND", "FOR", "GDP", "API", "APP", "VIP", "SME", "MOU", "EVN", "BHX", "SBV", "NHNN", "VAS", "IFRS", "ODA", "PPP"}
TICKER_RE = re.compile(r"(?<![A-Za-z0-9À-ỹ])([A-Z][A-Z0-9]{2})(?![A-Za-z0-9À-ỹ])")


def tag_symbols(textv: str, universe: set[str]) -> list[str]:
    found = []
    for m in TICKER_RE.finditer(textv or ""):
        t = m.group(1)
        if t in universe and t not in STOP_TICKERS and t not in found:
            found.append(t)
    return found[:8]


async def sync_news(db: AsyncSession, analyze: bool = True, max_analyze: int = 80) -> dict:
    universe = {s for (s,) in (await db.execute(select(Stock.symbol).where(Stock.is_active))).all()}
    r = RSSAdapter(timeout=30)
    items, failed = [], 0
    try:
        for source, url, is_market in FEEDS:
            try:
                for it in await r.fetch(source, url):
                    it["is_market"] = is_market
                    items.append(it)
            except Exception as e:  # noqa: BLE001
                failed += 1
                log.warning("rss %s failed: %s", url, e)
    finally:
        await r.close()
    await mark_source(db, "RSS", failed < len(FEEDS))
    existing = {u for (u,) in (await db.execute(select(NewsArticle.url).where(NewsArticle.url.in_([i["url"] for i in items])))).all()} if items else set()
    new = 0
    seen_urls = set()
    for it in items:
        if it["url"] in existing or it["url"] in seen_urls:
            continue
        seen_urls.add(it["url"])
        syms = tag_symbols(f"{it['title']} {it.get('summary') or ''}", universe)
        a = NewsArticle(url=it["url"], source=it["source"], title=it["title"], summary=it.get("summary"), image_url=it.get("image_url"),
                        published_at=it["published_at"], symbols=syms, is_market=bool(it["is_market"] or not syms))
        db.add(a)
        await db.flush()
        for s in syms:
            db.add(NewsStockLink(article_id=a.id, symbol=s))
        new += 1
    await db.flush()
    analyzed = await analyze_news(db, max_analyze) if analyze else 0
    # retention: keep 120 days
    await db.execute(text("DELETE FROM news_articles WHERE published_at < now() - interval '120 days'"))
    return {"fetched": len(items), "new": new, "analyzed": analyzed, "feeds_failed": failed}


async def analyze_news(db: AsyncSession, limit: int = 80) -> int:
    """Claude: sentiment −1..1, 1-sentence summary, and which candidate tickers the article is really about."""
    from app.services import ai

    if not ai.available():
        return 0
    rows = (await db.execute(select(NewsArticle).where(NewsArticle.analyzed_at.is_(None)).order_by(NewsArticle.published_at.desc()).limit(limit))).scalars().all()
    if not rows:
        return 0
    client = ai._client()
    n = 0
    for i in range(0, len(rows), 20):
        chunk = rows[i : i + 20]
        payload = [{"id": a.id, "title": a.title, "summary": (a.summary or "")[:400], "candidate_symbols": a.symbols or []} for a in chunk]
        prompt = ("Với mỗi bản tin chứng khoán Việt Nam dưới đây, trả về JSON mảng các object {id, sentiment, symbols, summary}:\n"
                  "- sentiment: số từ -1 (rất tiêu cực cho cổ phiếu/thị trường) đến 1 (rất tích cực), 0 nếu trung tính.\n"
                  "- symbols: chỉ giữ các mã trong candidate_symbols mà bản tin thực sự nói về doanh nghiệp đó (mã viết hoa trùng từ thường thì bỏ).\n"
                  "- summary: một câu tiếng Việt ≤ 30 từ, chỉ dựa vào tiêu đề và tóm tắt, không thêm số liệu.\n"
                  "Chỉ trả về JSON.\n\n" + json.dumps(payload, ensure_ascii=False))
        try:
            resp = await client.messages.create(model=ai.settings.ai_model, max_tokens=3000, output_config={"effort": "low"},
                                                system="Bạn là biên tập viên tin tài chính, phân loại tin khách quan, không bịa thông tin.",
                                                messages=[{"role": "user", "content": prompt}])
            txt = "".join(b.text for b in resp.content if b.type == "text")
            m = re.search(r"\[.*\]", txt, re.S)
            res = {int(x["id"]): x for x in json.loads(m.group(0))} if m else {}
        except Exception as e:  # noqa: BLE001
            log.warning("analyze_news failed: %s", e)
            res = {}
        for a in chunk:
            x = res.get(a.id)
            a.analyzed_at = datetime.now(UTC)
            if not x:
                continue
            try:
                s = max(-1.0, min(1.0, float(x.get("sentiment") or 0)))
            except (TypeError, ValueError):
                s = 0.0
            a.sentiment = round(s, 2)
            a.sentiment_label = "POSITIVE" if s >= 0.25 else "NEGATIVE" if s <= -0.25 else "NEUTRAL"
            a.ai_summary = (x.get("summary") or "")[:400] or None
            keep = [t for t in (x.get("symbols") or []) if t in (a.symbols or [])]
            if keep != (a.symbols or []):
                await db.execute(text("DELETE FROM news_stock_links WHERE article_id = :i"), {"i": a.id})
                for t in keep:
                    db.add(NewsStockLink(article_id=a.id, symbol=t))
                a.symbols = keep
                a.is_market = a.is_market or not keep
            n += 1
        await db.flush()
    return n


# ------------------------------------------------------------------ snapshot enrichment
ENRICH_SQL = [
    # foreign / proprietary net over the last 1, 5, 20 trading days of data
    """WITH d AS (SELECT DISTINCT trade_date FROM investor_flows ORDER BY trade_date DESC LIMIT 20),
            r AS (SELECT trade_date, row_number() OVER (ORDER BY trade_date DESC) rn FROM d),
            f AS (SELECT i.symbol, sum(i.foreign_net_val) FILTER (WHERE r.rn <= 1) t1, sum(i.foreign_net_val) FILTER (WHERE r.rn <= 5) t5,
                         sum(i.foreign_net_val) t20, sum(i.prop_net_val) FILTER (WHERE r.rn <= 5) p5
                  FROM investor_flows i JOIN r ON r.trade_date = i.trade_date GROUP BY i.symbol)
       UPDATE stock_snapshots s SET foreign_net_today = f.t1, foreign_net_5d = f.t5, foreign_net_20d = f.t20, prop_net_5d = f.p5 FROM f WHERE f.symbol = s.symbol""",
    """UPDATE stock_snapshots s SET foreign_room_pct = x.room / st.listed_shares * 100
       FROM (SELECT DISTINCT ON (symbol) symbol, foreign_room room FROM investor_flows WHERE foreign_room IS NOT NULL ORDER BY symbol, trade_date DESC) x
       JOIN stocks st ON st.symbol = x.symbol WHERE s.symbol = x.symbol AND st.listed_shares > 0""",
    # insiders: net value of completed deals in 90 days (negative = selling), pending registered sells
    """UPDATE stock_snapshots s SET insider_net_90d = x.net, insider_pending_sell = x.pending FROM (
         SELECT i.symbol,
                sum(CASE WHEN i.status = 'DONE' AND coalesce(i.end_date, i.announce_date) >= current_date - 90
                         THEN (CASE WHEN i.side = 'BUY' THEN 1 ELSE -1 END) * coalesce(i.quantity_done, 0) ELSE 0 END) * max(sn.price) net,
                sum(CASE WHEN i.status = 'REGISTERED' AND i.side = 'SELL' AND coalesce(i.end_date, current_date) >= current_date THEN coalesce(i.quantity, 0) ELSE 0 END) pending
         FROM insider_transactions i JOIN stock_snapshots sn ON sn.symbol = i.symbol
         WHERE coalesce(i.end_date, i.announce_date) >= current_date - 180 GROUP BY i.symbol) x WHERE s.symbol = x.symbol""",
    # consensus: latest report per firm within 180 days
    """UPDATE stock_snapshots s SET consensus_target = x.t, consensus_count = x.n, consensus_upside_pct = (x.t / s.price - 1) * 100 FROM (
         SELECT symbol, avg(target_price) t, count(*) n FROM (
           SELECT DISTINCT ON (symbol, firm) symbol, firm, target_price FROM broker_recommendations
           WHERE report_date >= current_date - 180 AND target_price > 0 ORDER BY symbol, firm, report_date DESC) z GROUP BY symbol) x
       WHERE s.symbol = x.symbol AND s.price > 0""",
    # news sentiment 7 days
    """UPDATE stock_snapshots s SET news_sentiment_7d = x.avg_s, news_count_7d = x.n FROM (
         SELECT l.symbol, avg(a.sentiment) avg_s, count(*) n FROM news_stock_links l JOIN news_articles a ON a.id = l.article_id
         WHERE a.published_at >= now() - interval '7 days' GROUP BY l.symbol) x WHERE s.symbol = x.symbol""",
    # trailing cash dividend yield from ex-dates in the last 365 days
    """UPDATE stock_snapshots s SET dividend_yield = x.cash / s.price * 100 FROM (
         SELECT symbol, sum(cash_per_share) cash FROM corporate_actions WHERE kind = 'CASH_DIVIDEND' AND ex_date BETWEEN current_date - 365 AND current_date
         GROUP BY symbol) x WHERE s.symbol = x.symbol AND s.price > 0""",
    # next event (ex-date of a right, or AGM date) + calendar days until it (pre-trade "event within 5 sessions")
    """UPDATE stock_snapshots s SET next_event = NULL, earnings_in_days = NULL""",
    """UPDATE stock_snapshots s SET next_event = json_build_object('kind', x.kind, 'title', x.title, 'date', x.d, 'note', left(x.note, 200)),
              earnings_in_days = x.d - current_date FROM (
         SELECT DISTINCT ON (symbol) symbol, kind, title, note, coalesce(ex_date, event_date) d FROM corporate_actions
         WHERE kind IN ('CASH_DIVIDEND','STOCK_DIVIDEND','BONUS','ISSUE','AGM','AGM_RECORD') AND coalesce(ex_date, event_date) >= current_date
         ORDER BY symbol, coalesce(ex_date, event_date)) x WHERE s.symbol = x.symbol""",
]


async def enrich_snapshots(db: AsyncSession) -> dict:
    for sql in ENRICH_SQL:
        await db.execute(text(sql))
    await db.flush()
    n = (await db.execute(text("SELECT count(*) FILTER (WHERE foreign_net_5d IS NOT NULL), count(*) FILTER (WHERE insider_net_90d IS NOT NULL), count(*) FILTER (WHERE consensus_target IS NOT NULL), count(*) FILTER (WHERE next_event IS NOT NULL) FROM stock_snapshots"))).one()
    return {"with_flows": n[0], "with_insiders": n[1], "with_consensus": n[2], "with_next_event": n[3]}


async def risk_inputs(db: AsyncSession) -> dict[str, dict]:
    """Per symbol: insider net sell (VND, 90d), dilution % (ISSUE in 365d), late filing / audit flags from exchange alerts."""
    out: dict[str, dict] = {}
    rows = (await db.execute(text("""
        SELECT i.symbol, sum(CASE WHEN i.side = 'SELL' THEN 1 ELSE -1 END * coalesce(i.quantity_done, 0)) * max(p.close) v
        FROM insider_transactions i JOIN (SELECT DISTINCT ON (symbol) symbol, close FROM price_daily WHERE trade_date >= current_date - 15 ORDER BY symbol, trade_date DESC) p ON p.symbol = i.symbol
        WHERE i.status = 'DONE' AND coalesce(i.end_date, i.announce_date) >= current_date - 90 GROUP BY i.symbol"""))).all()
    for sym, v in rows:
        out.setdefault(sym, {})["insider_net_sell_vnd"] = max(0.0, float(v or 0))
    for sym, ratio in (await db.execute(text("""SELECT symbol, sum(ratio) FROM corporate_actions WHERE kind = 'ISSUE' AND coalesce(ex_date, disclosure_date) >= current_date - 365
                                               GROUP BY symbol"""))).all():
        out.setdefault(sym, {})["dilution_pct"] = float(ratio or 0)
    for sym, note in (await db.execute(text("""SELECT symbol, note FROM corporate_actions WHERE kind LIKE 'ALERT_%' AND disclosure_date >= current_date - 365"""))).all():
        n = (note or "").lower()
        d = out.setdefault(sym, {})
        if "chậm" in n and ("báo cáo tài chính" in n or "bctc" in n):
            d["late_filing"] = True
        if "kiểm toán" in n and ("ngoại trừ" in n or "từ chối" in n or "không đưa ra ý kiến" in n):
            d["audit_qualified"] = True
    return out


async def backfill_extras(db: AsyncSession, flow_days: int = 60) -> dict:
    """One-off history load: events since 2025, upcoming events, 60 sessions of flows, 1 year of recommendations, insiders (2 pages), news."""
    out = {}
    out["events_disclosed"] = await sync_events(db, date(2025, 1, 1))
    out["events_upcoming"] = await sync_events(db, today_vn() - timedelta(days=30), field="effectiveDate")
    await db.commit()
    out["flows"] = await sync_flows(db, trading_days_back(flow_days))
    await db.commit()
    out["recommendations"] = await sync_recommendations(db, today_vn() - timedelta(days=400))
    await db.commit()
    out["insiders"] = await sync_insiders(db, pages=2)
    await db.commit()
    out["news"] = await sync_news(db, analyze=True, max_analyze=120)
    await db.commit()
    return out


if __name__ == "__main__":
    import sys

    from app.core.db import session_scope

    async def _main():
        logging.basicConfig(level=logging.WARNING)
        async with session_scope() as db:
            r = await backfill_extras(db, flow_days=int(sys.argv[1]) if len(sys.argv) > 1 else 60)
            print(json.dumps(r, ensure_ascii=False, default=str))

    asyncio.run(_main())

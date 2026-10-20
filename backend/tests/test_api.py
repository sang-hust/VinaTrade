"""API smoke tests against the local database (needs `alembic upgrade head` + seed + at least one EOD run).
Skipped automatically when the database is unreachable."""

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def client():
    os.environ.setdefault("SCHEDULER_ENABLED", "false")
    settings.scheduler_enabled = False
    from app.main import app

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/health")
            if r.status_code != 200:
                pytest.skip("database not available")
            yield c
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"database not available: {e}")


@pytest.fixture
async def token(client):
    r = await client.post("/api/v1/auth/login", json={"email": settings.admin_email, "password": settings.admin_password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _h(token):
    return {"Authorization": f"Bearer {token}"}


async def test_me_and_overview(client, token):
    r = await client.get("/api/v1/me", headers=_h(token))
    assert r.status_code == 200 and r.json()["user"]["role"] == "ADMIN"
    r = await client.get("/api/v1/market/overview", headers=_h(token))
    assert r.status_code == 200
    d = r.json()
    assert "headline" in d and "indexes" in d and "signals" in d


async def test_unauthenticated():
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/market/overview")
        assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_stock_analysis_and_screener(client, token):
    r = await client.get("/api/v1/stocks/FPT/analysis", headers=_h(token))
    if r.status_code == 404:
        pytest.skip("no EOD data yet")
    d = r.json()
    assert d["symbol"] == "FPT" and d["plan"]["stop_loss"] < d["price"] and d["rating_vi"]
    r = await client.get("/api/v1/screeners/presets", headers=_h(token))
    assert r.status_code == 200 and len(r.json()) == 11
    r = await client.post("/api/v1/screener/run", headers=_h(token), json={"preset_code": "GRAHAM", "limit": 5})
    assert r.status_code == 200 and "items" in r.json()
    r = await client.post("/api/v1/screener/run", headers=_h(token), json={"conditions": {"field": "bogus", "op": ">", "value": 1}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "DSL_INVALID"


async def test_register_pending_and_activate(client, token):
    email = f"test-{uuid.uuid4().hex[:8]}@example.com"
    r = await client.post("/api/v1/auth/register", json={"email": email, "password": "matkhau123", "full_name": "Người thử"})
    assert r.status_code == 200
    t2 = r.json()["access_token"]
    uid = r.json()["user"]["id"]
    r = await client.get("/api/v1/market/overview", headers=_h(t2))
    assert r.status_code == 403 and r.json()["error"]["code"] == "ACCOUNT_PENDING"
    r = await client.post(f"/api/v1/admin/users/{uid}/activate", headers=_h(token), json={"valid_months": 3})
    assert r.status_code == 200 and r.json()["status"] == "ACTIVE"
    r = await client.get("/api/v1/me", headers=_h(t2))
    assert r.status_code == 200 and r.json()["needs_onboarding"] is True
    r = await client.put("/api/v1/me/onboarding", headers=_h(t2), json={"experience": "NEW", "holding": "WEEKS", "max_loss": "P5", "symbols": ["FPT", "HPG"], "capital_band": "200M_1B"})
    assert r.status_code == 200 and r.json()["settings"]["ui_detail"] == "SIMPLE" and r.json()["risk_limits"]["stop_loss_pct"] == 5
    r = await client.get("/api/v1/watchlists", headers=_h(t2))
    assert r.status_code == 200 and r.json()[0]["count"] == 2
    await client.delete(f"/api/v1/admin/users/{uid}", headers=_h(token))


async def test_portfolio_pretrade_flow(client, token):
    r = await client.post("/api/v1/portfolios", headers=_h(token), json={"name": "Test", "initial_capital": 500_000_000})
    assert r.status_code == 200
    pid = r.json()["id"]
    try:
        r = await client.post(f"/api/v1/portfolios/{pid}/transactions", headers=_h(token), json={"side": "BUY", "symbol": "FPT", "quantity": 100, "price": 50000})
        assert r.status_code == 400 and r.json()["error"]["code"] == "PRETRADE_REQUIRED"
        r = await client.post("/api/v1/pretrade-check", headers=_h(token), json={"symbol": "FPT", "portfolio_id": pid, "quantity": 100, "price": 50000, "stop_loss": 46000, "take_profit": 60000})
        if r.status_code == 404:
            pytest.skip("no snapshot data")
        d = r.json()
        assert d["result"] in ("GREEN", "YELLOW", "RED") and len(d["items"]) >= 8
        if d["result"] != "RED":
            r = await client.post(f"/api/v1/portfolios/{pid}/transactions", headers=_h(token), json={"side": "BUY", "symbol": "FPT", "quantity": 100, "price": 50000, "stop_loss": 46000, "pretrade_check_id": d["check_id"]})
            assert r.status_code == 200
            r = await client.get(f"/api/v1/portfolios/{pid}", headers=_h(token))
            assert r.status_code == 200 and r.json()["positions"][0]["symbol"] == "FPT"
    finally:
        await client.delete(f"/api/v1/portfolios/{pid}", headers=_h(token))


# ---------------------------------------------------------------- admin console (UI part IV)
async def test_admin_frame_and_overview(client, token):
    r = await client.get("/api/v1/admin/status", headers=_h(token))
    assert r.status_code == 200
    d = r.json()
    assert d["health"] in ("GREEN", "YELLOW", "RED") and d["session"]["state"] in ("OPEN", "CLOSED", "HOLIDAY") and "todo" in d
    r = await client.get("/api/v1/admin/overview", headers=_h(token))
    assert r.status_code == 200
    o = r.json()
    assert o["eod_total"] == 19 and all("label" in s and "at" in s for s in o["eod_chain"]) and "users_total" in o["kpis"]
    r = await client.get("/api/v1/admin/overview/report", headers=_h(token))
    assert r.status_code == 200 and "BÁO CÁO VẬN HÀNH" in r.text
    r = await client.get(f"/api/v1/admin/search?q={settings.admin_email.split('@')[0][:4]}", headers=_h(token))
    assert r.status_code == 200 and any(x["type"] == "user" for x in r.json())
    r = await client.get("/api/v1/admin/search?q=sao lưu", headers=_h(token))
    assert any(x["type"] == "job" for x in r.json())


async def test_admin_session_unlock_and_idle(client, token):
    r = await client.post("/api/v1/admin/session/unlock", headers=_h(token), json={"password": "sai-mat-khau"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "BAD_CREDENTIALS"
    r = await client.post("/api/v1/admin/session/unlock", headers=_h(token), json={"password": settings.admin_password})
    assert r.status_code == 200
    # simulate 31 idle minutes on this device → console locked, unlock reopens it
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from app.core.db import session_scope
    from app.models import UserDevice

    async with session_scope() as db:
        await db.execute(update(UserDevice).values(admin_seen_at=datetime.now(UTC) - timedelta(minutes=settings.admin_idle_minutes + 1)))
    r = await client.get("/api/v1/admin/status", headers=_h(token))
    assert r.status_code == 403 and r.json()["error"]["code"] == "ADMIN_SESSION_EXPIRED"
    r = await client.post("/api/v1/admin/session/unlock", headers=_h(token), json={"password": settings.admin_password})
    assert r.status_code == 200
    r = await client.get("/api/v1/admin/status", headers=_h(token))
    assert r.status_code == 200


async def test_admin_config_form_and_history(client, token):
    r = await client.get("/api/v1/admin/config", headers=_h(token))
    assert r.status_code == 200
    rows = {c["key"]: c for c in r.json()}
    assert rows["risk.defaults"]["kind"] == "form" and rows["risk.defaults"]["fields"][0]["unit"] and rows["scoring.weights"]["kind"] == "weights"
    r = await client.put("/api/v1/admin/config/scoring.thresholds", headers=_h(token), json={"value": {"STRONG_BUY": 60, "BUY": 70, "HOLD": 50, "REDUCE": 35}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "THRESHOLDS_ORDER"
    r = await client.put("/api/v1/admin/config/alerts.limits", headers=_h(token), json={"value": {"max_rules_per_user": 150, "max_per_day": 40, "cooldown_minutes": 1440}})
    assert r.status_code == 200
    r = await client.get("/api/v1/admin/config/alerts.limits/history", headers=_h(token))
    assert r.status_code == 200 and r.json()[0]["after"]["value"]["max_rules_per_user"] == 150
    r = await client.post("/api/v1/admin/config/alerts.limits/reset", headers=_h(token))
    assert r.status_code == 200 and r.json()["value"]["max_rules_per_user"] == 200
    r = await client.post("/api/v1/admin/config/scoring.weights/preview", headers=_h(token), json={"value": {"SHORT": {"tech": 70, "fund": 10, "sector": 10, "pattern": 10}, "MID": {"tech": 25, "fund": 25, "sector": 25, "pattern": 25}, "LONG": {"tech": 10, "fund": 70, "sector": 10, "pattern": 10}}})
    assert r.status_code == 200 and "changed" in r.json() and "by_horizon" in r.json()
    r = await client.post("/api/v1/admin/config/scoring.weights/preview", headers=_h(token), json={"value": {"SHORT": {"tech": 70, "fund": 10, "sector": 10, "pattern": 20}}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "WEIGHTS_SUM"


async def test_admin_strategies_draft_and_performance(client, token):
    r = await client.get("/api/v1/admin/strategies", headers=_h(token))
    assert r.status_code == 200
    items = {s["code"]: s for s in r.json()["items"]}
    assert "fields" in items["MA50_PULLBACK"] and items["MA50_PULLBACK"]["params"]["pullback_rsi_max"] is not None
    r = await client.put("/api/v1/admin/strategies/GOLDEN_CROSS/draft", headers=_h(token), json={"params": {"bogus": 1}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "NO_PARAMS"
    r = await client.put("/api/v1/admin/strategies/MA50_PULLBACK/draft", headers=_h(token), json={"params": {"pullback_rsi_max": 50}})
    assert r.status_code == 200 and r.json()["draft_params"] == {"pullback_rsi_max": 50}
    r = await client.delete("/api/v1/admin/strategies/MA50_PULLBACK/draft", headers=_h(token))
    assert r.status_code == 200
    r = await client.get("/api/v1/admin/strategies/performance?months=12&days=20", headers=_h(token))
    assert r.status_code == 200
    p = r.json()
    assert p["regimes"] == ["UP", "PRESSURE", "DOWN"] and "excess_vs_index" in p["kpis"] and all("suggestion" in x and "name" in x for x in p["by_strategy_regime"])


async def test_admin_jobs_table_quality_latency(client, token):
    r = await client.get("/api/v1/admin/jobs?limit=20", headers=_h(token))
    assert r.status_code == 200
    d = r.json()
    assert {"queue_pending", "failed_24h", "db_size_mb", "last_backup_at"} <= set(d["kpis"])
    names = {j["name"] for j in d["jobs"]}
    assert {"eod", "intraday", "backup", "news_sync"} <= names and all("schedule" in j and "status" in j for j in d["jobs"])
    assert isinstance(d["latency"], list) and len(d["quality"]) >= 5
    r = await client.post("/api/v1/admin/jobs/backup/stop", headers=_h(token))
    assert r.status_code == 400 and r.json()["error"]["code"] == "NOT_RUNNING"
    if d["runs"]:
        r = await client.get(f"/api/v1/admin/jobs/runs/{d['runs'][0]['id']}", headers=_h(token))
        assert r.status_code == 200 and "error" in r.json()


async def test_admin_users_create_bulk_and_margin_import(client, token):
    email = f"tao-{uuid.uuid4().hex[:8]}@example.com"
    r = await client.post("/api/v1/admin/users", headers=_h(token), json={"email": email, "full_name": "Người được tạo", "valid_months": 6})
    assert r.status_code == 200 and r.json()["status"] == "ACTIVE" and r.json()["temp_password"]
    uid = r.json()["id"]
    r = await client.get(f"/api/v1/admin/users/{uid}", headers=_h(token))
    assert r.status_code == 200 and r.json()["max_devices"] == 3 and "registered_device" in r.json()
    r = await client.post("/api/v1/admin/users/bulk-activate", headers=_h(token), json={"ids": [uid], "valid_months": 3})
    assert r.status_code == 200 and "0 tài khoản" in r.json()["message"]  # already active → skipped
    await client.delete(f"/api/v1/admin/users/{uid}", headers=_h(token))
    csv = "CTCK,Mã\nVCBS,FPT\nVCBS,HPG\nPinetree,fpt\n".encode()
    r = await client.post("/api/v1/admin/margin-lists/import?replace=true", headers=_h(token), files={"file": ("kyquy.csv", csv, "text/csv")})
    assert r.status_code == 200 and r.json()["lists"]["VCBS"] == ["FPT", "HPG"] and r.json()["lists"]["Pinetree"] == ["FPT"]
    r = await client.get("/api/v1/admin/ai-usage?days=7", headers=_h(token))
    assert r.status_code == 200 and "by_task" in r.json()
    r = await client.get("/api/v1/admin/audit-logs?action=MARGIN_LISTS", headers=_h(token))
    assert r.status_code == 200 and r.json()["total"] >= 1


async def test_total_risk_in_analysis_and_ranking(client, token):
    r = await client.get("/api/v1/stocks/FPT/analysis", headers=_h(token))
    if r.status_code == 404:
        pytest.skip("no EOD data yet")
    d = r.json()
    if d.get("risk") is None:
        pytest.skip("eod.risk_total has not run on this database")
    risk = d["risk"]
    assert risk["level"] in ("LOW", "MEDIUM", "HIGH") and [c["key"] for c in risk["components"]] == ["volatility", "liquidity", "company", "manipulation", "event", "correlation"]
    assert all("note" in c and "weight" in c for c in risk["components"]) and "score_adj" in risk and risk["text"]
    r = await client.get("/api/v1/opportunities?horizon=MID&limit=30", headers=_h(token))
    assert r.status_code == 200
    items = r.json()["items"]
    adj = [i["score_adj"] for i in items if i.get("score_adj") is not None]
    assert adj == sorted(adj, reverse=True) and all("risk_total_level" in i for i in items)
    r = await client.get("/api/v1/opportunities?horizon=MID&limit=30&sort=score", headers=_h(token))
    sc = [i["score"] for i in r.json()["items"] if i.get("score") is not None]
    assert sc == sorted(sc, reverse=True)
    r = await client.get("/api/v1/market/overview", headers=_h(token))
    buys = r.json()["signals"].get("buys") or []
    assert all("risk_total_vi" in b for b in buys)
    r = await client.get("/api/v1/admin/config", headers=_h(token))
    keys = {c["key"] for c in r.json()}
    assert {"risk.score_weights", "risk.score_params"} <= keys
    r = await client.put("/api/v1/admin/config/risk.score_weights", headers=_h(token), json={"value": {"volatility": 50, "liquidity": 20, "company": 20, "manipulation": 15, "event": 10, "correlation": 10}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "WEIGHTS_SUM"


async def test_risk_numbers_and_options(client, token):
    r = await client.get("/api/v1/market/overview?horizon=MID", headers=_h(token))
    assert r.status_code == 200
    for b in (r.json()["signals"].get("buys") or []):
        assert "risk_numbers" in b
        if b["risk_numbers"]:
            assert "text" in b["risk_numbers"] and "max_loss" in b["risk_numbers"]
    r = await client.post("/api/v1/pretrade-check", headers=_h(token), json={"symbol": "FPT", "quantity": 300, "price": 50000, "stop_loss": 46000, "take_profit": 60000, "save": False})
    if r.status_code == 404:
        pytest.skip("no snapshot data")
    d = r.json()
    assert [o["key"] for o in d["options"]] == ["none", "third", "full"] and d["options"][2]["quantity"] == 300 and d["options"][1]["quantity"] == 100
    assert d["options"][2]["max_loss"] >= 300 * 4000 and "risk_numbers" in d


async def test_transaction_typo_and_cash_guards(client, token):
    r = await client.post("/api/v1/portfolios", headers=_h(token), json={"name": "Guard test", "initial_capital": 10_000_000, "uses_margin": False})
    assert r.status_code == 200
    pid = r.json()["id"]
    try:
        r = await client.get("/api/v1/stocks/VNM/analysis", headers=_h(token))
        if r.status_code == 404:
            pytest.skip("no snapshot data")
        px = r.json()["price"]
        chk = await client.post("/api/v1/pretrade-check", headers=_h(token), json={"symbol": "VNM", "portfolio_id": pid, "quantity": 100, "price": px // 10, "stop_loss": px // 11, "take_profit": px // 8})
        assert chk.status_code == 200 and chk.json()["result"] == "RED" and any(i["code"] == "PRICE" and i["level"] == "RED" for i in chk.json()["items"])
        r = await client.post(f"/api/v1/portfolios/{pid}/transactions", headers=_h(token), json={"side": "BUY", "symbol": "VNM", "quantity": 100, "price": px // 10, "pretrade_check_id": chk.json()["check_id"]})
        assert r.status_code == 400 and r.json()["error"]["code"] == "PRICE_SUSPECT" and r.json()["error"]["details"]["suggested_price"] == float(px)
        r = await client.post(f"/api/v1/portfolios/{pid}/transactions", headers=_h(token), json={"side": "BUY", "symbol": "VNM", "quantity": 100_000, "price": px, "pretrade_check_id": chk.json()["check_id"]})
        assert r.status_code == 400 and r.json()["error"]["code"] == "CASH_INSUFFICIENT"
        r = await client.post(f"/api/v1/portfolios/{pid}/transactions", headers=_h(token), json={"side": "SELL", "symbol": "VNM", "quantity": 100, "price": px // 10, "confirm_price": True})
        assert r.status_code != 400 or r.json()["error"]["code"] != "PRICE_SUSPECT"  # confirmed price passes the typo guard
    finally:
        await client.delete(f"/api/v1/portfolios/{pid}", headers=_h(token))


async def test_heat_limit_and_guard_fields(client, token):
    r = await client.get("/api/v1/me/risk-limits", headers=_h(token))
    assert r.status_code == 200 and "max_open_risk_pct" in r.json()
    r = await client.put("/api/v1/me/risk-limits", headers=_h(token), json={"max_open_risk_pct": 5})
    assert r.status_code == 200 and r.json()["max_open_risk_pct"] == 5
    await client.put("/api/v1/me/risk-limits", headers=_h(token), json={"max_open_risk_pct": 6})
    r = await client.get("/api/v1/me/risk-guard", headers=_h(token))
    assert r.status_code == 200 and "equity_cap_pct" in r.json() and "drawdown_pct" in r.json()
    r = await client.post("/api/v1/pretrade-check", headers=_h(token), json={"symbol": "FPT", "quantity": 100, "save": False})
    if r.status_code == 404:
        pytest.skip("no snapshot data")
    codes = [i["code"] for i in r.json()["items"]]
    assert "HEAT" in codes and "LIQUIDITY" in codes


async def test_breadth_fields_and_manipulation_check(client, token):
    r = await client.get("/api/v1/market/overview", headers=_h(token))
    assert r.status_code == 200
    br = r.json().get("breadth")
    if br:
        assert {"new_highs", "new_lows", "foreign_net_5d", "foreign_sell_streak", "pressure_reasons"} <= set(br)
    r = await client.post("/api/v1/pretrade-check", headers=_h(token), json={"symbol": "FPT", "quantity": 100, "save": False})
    if r.status_code == 404:
        pytest.skip("no snapshot data")
    assert "MANIPULATION" in [i["code"] for i in r.json()["items"]]
    r = await client.get("/api/v1/admin/config", headers=_h(token))
    assert {"regime.breadth", "risk.manipulation"} <= {c["key"] for c in r.json()}
    r = await client.post("/api/v1/screener/run", headers=_h(token), json={"preset_code": "HIGH_RISK", "limit": 5})
    assert r.status_code == 200 and all((i.get("risk_total") or 0) >= 50 or (i.get("risk_score") or 0) >= 60 for i in r.json()["items"])


async def test_risk_avoided_endpoints(client, token):
    r = await client.get("/api/v1/admin/risk-avoided?days=180", headers=_h(token))
    assert r.status_code == 200
    d = r.json()
    assert {"red_blocked", "red_overridden", "guard", "stop_sold", "stop_held", "drawdown", "headline"} <= set(d) and "avoided_vnd" in d["red_blocked"]
    r = await client.get("/api/v1/me/risk-avoided?days=90", headers=_h(token))
    assert r.status_code == 200 and "headline" in r.json() and "drawdown" in r.json()


async def test_strategy_regime_gates(client, token):
    r = await client.get("/api/v1/admin/strategies", headers=_h(token))
    assert r.status_code == 200 and "gate" in r.json() and all("gated_regimes" in s for s in r.json()["items"])
    r = await client.get("/api/v1/admin/strategies/performance?months=60", headers=_h(token))
    assert r.status_code == 200
    r = await client.get("/api/v1/admin/config", headers=_h(token))
    assert "strategy.regime_gate" in {c["key"] for c in r.json()}

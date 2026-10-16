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

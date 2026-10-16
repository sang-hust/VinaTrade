import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select

from app.api.deps import DB, CurrentUser
from app.api.presenters import clean, row
from app.core.errors import bad_request, forbidden, not_found
from app.models import Alert, AlertRule, StockSnapshot
from app.schemas.common import Ok
from app.screener.dsl import describe, ensure_valid, to_sql
from app.services.sysconfig import get_config

router = APIRouter(tags=["alerts"])

TEMPLATES = {
    "ENTRY_ZONE": {"name": "Giá vào vùng mua", "build": lambda p: {"all": [{"field": "price", "op": ">=", "value": {"field": "entry_low"}}, {"field": "price", "op": "<=", "value": {"field": "entry_high"}}]}},
    "RATING_CHANGE": {"name": "Đổi khuyến nghị", "build": lambda p: {"field": "rating_changed", "op": "==", "value": True}},
    "STOP_OR_TP": {"name": "Chạm cắt lỗ hoặc mục tiêu", "build": lambda p: {"any": [{"field": "price", "op": "<=", "value": {"field": "stop_loss"}}, {"field": "price", "op": ">=", "value": {"field": "take_profit_1"}}]}},
    "BREAKOUT": {"name": "Phá nền", "build": lambda p: {"field": "signal", "op": "has_signal", "value": "BREAKOUT_BASE", "lookback": 1}},
    "RSI": {"name": "RSI", "build": lambda p: {"field": "rsi14", "op": p.get("op", "<"), "value": float(p.get("value", 30))}},
    "PRICE": {"name": "Chạm giá", "build": lambda p: {"field": "price", "op": p.get("op", "<="), "value": float(p.get("value", 0))}},
    "PCT_CHANGE": {"name": "% thay đổi trong phiên", "build": lambda p: {"field": "change_pct", "op": p.get("op", ">="), "value": float(p.get("value", 5))}},
    "MA50_CROSS": {"name": "Giá cắt MA50", "build": lambda p: {"field": "price", "op": "cross_above" if p.get("direction", "up") == "up" else "cross_below", "value": {"field": "ma50"}, "lookback": 1}},
    "VOLUME_SPIKE": {"name": "Khối lượng đột biến", "build": lambda p: {"field": "vol_ratio", "op": ">=", "value": float(p.get("value", 2))}},
}
# rating_changed / entry_low are snapshot columns usable in memory & SQL
from app.screener.dsl import FIELDS as _F  # noqa: E402

for extra in ("rating_changed", "entry_low", "entry_high", "stop_loss", "take_profit_1", "change_pct"):
    _F.setdefault(extra, {"type": "num", "vi": extra, "group": "score"})
_F["rating_changed"] = {"type": "bool", "vi": "Đổi khuyến nghị hôm nay", "group": "score"}
_F["entry_low"]["vi"], _F["entry_high"]["vi"], _F["stop_loss"]["vi"], _F["take_profit_1"]["vi"] = "Vùng mua (dưới)", "Vùng mua (trên)", "Cắt lỗ hệ thống", "Chốt lời 1 hệ thống"


class RuleIn(BaseModel):
    name: str | None = None
    scope_type: str = "SYMBOL"  # SYMBOL | WATCHLIST | PORTFOLIO | SCREENER | MARKET
    scope_id: str | None = None
    template: str | None = None
    params: dict | None = None
    conditions: dict | None = None
    timing: str = "BOTH"
    priority: str = "HIGH"
    channels: list[str] = ["push", "telegram"]
    cooldown_minutes: int = 1440
    enabled: bool = True


def _rule_out(r: AlertRule) -> dict:
    return {**row(r, ["id", "name", "scope_type", "scope_id", "conditions", "template", "timing", "priority", "channels", "cooldown_minutes", "enabled", "last_fired_at", "created_at"]),
            "id": str(r.id), "chips": describe(r.conditions) if r.conditions else [], "template_vi": TEMPLATES.get(r.template or "", {}).get("name")}


def _build(body: RuleIn) -> tuple[dict, str]:
    if body.template:
        t = TEMPLATES.get(body.template)
        if not t:
            raise bad_request("TEMPLATE", "Mẫu cảnh báo không tồn tại")
        cond = t["build"](body.params or {})
        name = body.name or (f"{body.scope_id}: {t['name']}" if body.scope_type == "SYMBOL" and body.scope_id else t["name"])
        return cond, name
    if not body.conditions:
        raise bad_request("NO_CONDITIONS", "Cần điều kiện cảnh báo")
    ensure_valid(body.conditions)
    return body.conditions, body.name or " ".join(describe(body.conditions))[:160]


@router.get("/alert-rules/templates")
async def templates(user: CurrentUser):
    return [{"code": k, "name": v["name"]} for k, v in TEMPLATES.items()]


@router.get("/alert-rules")
async def list_rules(user: CurrentUser, db: DB):
    rows = (await db.execute(select(AlertRule).where(AlertRule.user_id == user.id).order_by(desc(AlertRule.created_at)))).scalars().all()
    return [_rule_out(r) for r in rows]


@router.post("/alert-rules")
async def create_rule(body: RuleIn, user: CurrentUser, db: DB):
    limits = await get_config(db, "alerts.limits")
    n = await db.scalar(select(func.count(AlertRule.id)).where(AlertRule.user_id == user.id))
    if n >= int(limits.get("max_rules_per_user", 200)):
        raise bad_request("RULE_LIMIT", f"Tối đa {limits.get('max_rules_per_user', 200)} quy tắc. Hãy gộp hoặc xóa bớt.")
    cond, name = _build(body)
    if body.scope_type not in ("SYMBOL", "WATCHLIST", "PORTFOLIO", "SCREENER", "MARKET"):
        raise bad_request("SCOPE", "Phạm vi không hợp lệ")
    r = AlertRule(user_id=user.id, name=name[:160], scope_type=body.scope_type, scope_id=(body.scope_id.upper() if body.scope_type == "SYMBOL" and body.scope_id else body.scope_id),
                  conditions=cond, template=body.template, timing=body.timing.upper(), priority=body.priority.upper(), channels=body.channels, cooldown_minutes=body.cooldown_minutes, enabled=body.enabled)
    db.add(r)
    await db.commit()
    return _rule_out(r)


@router.put("/alert-rules/{rule_id}")
async def update_rule(rule_id: uuid.UUID, body: RuleIn, user: CurrentUser, db: DB):
    r = await db.get(AlertRule, rule_id)
    if not r or r.user_id != user.id:
        raise forbidden()
    cond, name = _build(body)
    r.name, r.scope_type, r.scope_id, r.conditions, r.template = name[:160], body.scope_type, (body.scope_id.upper() if body.scope_type == "SYMBOL" and body.scope_id else body.scope_id), cond, body.template
    r.timing, r.priority, r.channels, r.cooldown_minutes, r.enabled = body.timing.upper(), body.priority.upper(), body.channels, body.cooldown_minutes, body.enabled
    await db.commit()
    return _rule_out(r)


@router.patch("/alert-rules/{rule_id}/toggle")
async def toggle_rule(rule_id: uuid.UUID, user: CurrentUser, db: DB, enabled: bool = True):
    r = await db.get(AlertRule, rule_id)
    if not r or r.user_id != user.id:
        raise forbidden()
    r.enabled = enabled
    await db.commit()
    return _rule_out(r)


@router.delete("/alert-rules/{rule_id}", response_model=Ok)
async def delete_rule(rule_id: uuid.UUID, user: CurrentUser, db: DB):
    r = await db.get(AlertRule, rule_id)
    if not r or r.user_id != user.id:
        raise forbidden()
    await db.delete(r)
    await db.commit()
    return Ok(message="Đã xóa quy tắc")


@router.post("/alert-rules/{rule_id}/test")
async def test_rule(rule_id: uuid.UUID, user: CurrentUser, db: DB):
    r = await db.get(AlertRule, rule_id)
    if not r or r.user_id != user.id:
        raise forbidden()
    from app.tasks.alerts import _rule_hits

    snaps = {s.symbol: {c.name: getattr(s, c.name) for c in StockSnapshot.__table__.columns} for s in (await db.execute(select(StockSnapshot))).scalars()}
    hits = await _rule_hits(db, user, r, snaps)
    return {"count": len(hits), "symbols": hits[:50]}


@router.post("/alert-rules/preview")
async def preview_rule(body: RuleIn, user: CurrentUser, db: DB):
    cond, _ = _build(body)
    try:
        syms = [s for (s,) in (await db.execute(select(StockSnapshot.symbol).where(to_sql(cond)).limit(50))).all()]
    except Exception:  # noqa: BLE001
        syms = []
    return {"count": len(syms), "symbols": syms, "chips": describe(cond)}


@router.get("/alerts")
async def list_alerts(user: CurrentUser, db: DB, unread: bool | None = None, filter: str | None = Query(None, alias="f"), page: int = 1, size: int = Query(50, le=200)):
    stmt = select(Alert).where(Alert.user_id == user.id)
    if unread:
        stmt = stmt.where(Alert.read_at.is_(None))
    f = (filter or "all").lower()
    if f == "unread":
        stmt = stmt.where(Alert.read_at.is_(None))
    elif f == "urgent":
        stmt = stmt.where(Alert.priority == "URGENT")
    elif f == "rating":
        stmt = stmt.where(Alert.kind == "RATING_CHANGE")
    elif f == "price":
        stmt = stmt.where(Alert.kind.in_(["PRICE", "SIGNAL"]))
    elif f == "portfolio":
        stmt = stmt.where(Alert.kind.in_(["PORTFOLIO", "GUARD", "PLAN"]))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (await db.execute(stmt.order_by(desc(Alert.created_at)).offset((page - 1) * size).limit(size))).scalars().all()
    counts = {}
    base = select(Alert.kind, Alert.priority, Alert.read_at).where(Alert.user_id == user.id)
    for kind, prio, read_at in (await db.execute(base)).all():
        counts["all"] = counts.get("all", 0) + 1
        if read_at is None:
            counts["unread"] = counts.get("unread", 0) + 1
        if prio == "URGENT":
            counts["urgent"] = counts.get("urgent", 0) + 1
        if kind == "RATING_CHANGE":
            counts["rating"] = counts.get("rating", 0) + 1
        if kind in ("PRICE", "SIGNAL"):
            counts["price"] = counts.get("price", 0) + 1
        if kind in ("PORTFOLIO", "GUARD", "PLAN"):
            counts["portfolio"] = counts.get("portfolio", 0) + 1
    return {"items": [{**row(a, ["id", "symbol", "kind", "priority", "title", "body", "deeplink", "data", "read_at", "created_at"]), "signal_id": a.signal_id, "rule_id": str(a.rule_id) if a.rule_id else None} for a in rows],
            "total": total, "page": page, "size": size, "counts": counts}


class ReadIn(BaseModel):
    ids: list[int] | None = None
    all: bool = False


@router.post("/alerts/read", response_model=Ok)
async def mark_read(body: ReadIn, user: CurrentUser, db: DB):
    stmt = Alert.__table__.update().where(Alert.user_id == user.id, Alert.read_at.is_(None)).values(read_at=datetime.now(UTC))
    if not body.all:
        if not body.ids:
            raise bad_request("IDS", "Cần danh sách id")
        stmt = stmt.where(Alert.id.in_(body.ids))
    await db.execute(stmt)
    await db.commit()
    return Ok()


@router.get("/alerts/{alert_id}")
async def alert_detail(alert_id: int, user: CurrentUser, db: DB):
    a = await db.get(Alert, alert_id)
    if not a or a.user_id != user.id:
        raise not_found()
    if a.read_at is None:
        a.read_at = datetime.now(UTC)
        await db.commit()
    return {**row(a, ["id", "symbol", "kind", "priority", "title", "body", "deeplink", "data", "read_at", "created_at"]), "signal_id": a.signal_id}


_ = clean

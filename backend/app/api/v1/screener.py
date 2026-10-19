import uuid

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, or_, select

from app.api.deps import DB, CurrentUser
from app.api.presenters import snapshot_item
from app.core.errors import bad_request, forbidden, not_found
from app.models import Screener, Stock, StockSnapshot
from app.schemas.common import Ok
from app.screener.dsl import FIELDS, OPS, describe, ensure_valid, to_sql
from app.screener.presets import DEFAULT_FORM, FORM_FIELDS, build_dsl

router = APIRouter(tags=["screener"])


class RunIn(BaseModel):
    conditions: dict | None = None
    preset_code: str | None = None
    form: dict | None = None
    horizon: str = "MID"
    limit: int = 50
    page: int = 1
    sort: str | None = None


class ScreenerIn(BaseModel):
    name: str
    description: str | None = None
    conditions: dict | None = None
    form: dict | None = None
    preset_code: str | None = None
    horizon: str = "MID"
    notify_new: bool = False


def _col(hz: str):
    """Default ordering: risk-adjusted score (opportunity × (1 − risk/200)) — the least-risky pick first."""
    return {"SHORT": StockSnapshot.score_adj_short, "LONG": StockSnapshot.score_adj_long}.get(hz, StockSnapshot.score_adj_mid)


async def _resolve(db, body: RunIn | ScreenerIn) -> tuple[dict, dict | None]:
    hz = body.horizon.upper() if body.horizon.upper() in ("SHORT", "MID", "LONG") else "MID"
    if body.preset_code:
        p = (await db.execute(select(Screener).where(Screener.code == body.preset_code, Screener.is_preset))).scalar_one_or_none()
        if not p:
            raise not_found("Bộ lọc mẫu không tồn tại")
        form = body.form if body.form is not None else p.form_state
        return build_dsl(p.conditions.get("all", []), form, hz), form
    if body.form is not None and body.conditions is None:
        return build_dsl([], body.form, hz), body.form
    if body.conditions is None:
        raise bad_request("NO_CONDITIONS", "Cần điều kiện lọc")
    return body.conditions, None


@router.get("/screener/fields")
async def fields(user: CurrentUser):
    return {"fields": [{"key": k, **v} for k, v in FIELDS.items() if not v.get("memory_only")], "ops": OPS, "form": FORM_FIELDS, "form_default": DEFAULT_FORM}


@router.get("/screeners/presets")
async def presets(user: CurrentUser, db: DB):
    rows = (await db.execute(select(Screener).where(Screener.is_preset).order_by(Screener.position))).scalars().all()
    groups = {"TECH": "Kỹ thuật", "FUND": "Cơ bản", "AVOID": "Nên tránh"}
    return [{"id": str(r.id), "code": r.code, "name": r.name, "description": r.description, "group": r.group, "group_vi": groups.get(r.group), "horizon": r.horizon,
             "count": (r.last_result or {}).get("count", 0), "date": (r.last_result or {}).get("date"), "form_state": r.form_state, "core": r.conditions.get("all", [])} for r in rows]


@router.post("/screener/run")
async def run(body: RunIn, user: CurrentUser, db: DB):
    dsl, form = await _resolve(db, body)
    ensure_valid(dsl)
    hz = body.horizon.upper() if body.horizon.upper() in ("SHORT", "MID", "LONG") else "MID"
    try:
        clause = to_sql(dsl)
    except Exception as e:
        raise bad_request("DSL_INVALID", str(e)) from e
    stmt = select(Stock, StockSnapshot).join(StockSnapshot, StockSnapshot.symbol == Stock.symbol).where(Stock.is_active, clause)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    order = desc(_col(hz)).nulls_last()
    if body.sort:
        key, _, direction = body.sort.partition(":")
        if key in FIELDS and not FIELDS[key].get("memory_only"):
            colx = getattr(StockSnapshot, key)
            order = (colx.asc() if direction == "asc" else desc(colx)).nulls_last()
    limit = min(max(body.limit, 1), 200)
    rows = (await db.execute(stmt.order_by(order).offset((body.page - 1) * limit).limit(limit))).all()
    # relax suggestion when empty
    suggestion = None
    if total == 0 and isinstance(dsl, dict) and dsl.get("all") and len(dsl["all"]) > 1:
        best = None
        for i, rule in enumerate(dsl["all"]):
            rest = {"all": [r for j, r in enumerate(dsl["all"]) if j != i]}
            try:
                n = await db.scalar(select(func.count()).select_from(select(StockSnapshot.symbol).where(to_sql(rest)).subquery()))
            except Exception:  # noqa: BLE001
                continue
            if n and (best is None or n > best[0]):
                best = (n, rule)
        if best:
            suggestion = f"Không có mã nào thỏa {len(dsl['all'])} điều kiện. Thử bỏ “{' '.join(describe(best[1]))}”: còn {best[0]} mã."
    return {"items": [snapshot_item(sn, st, hz) for st, sn in rows], "total": total, "page": body.page, "size": limit, "horizon": hz,
            "chips": describe(dsl), "dsl": dsl, "form": form, "suggestion": suggestion}


@router.get("/screeners")
async def list_screeners(user: CurrentUser, db: DB):
    rows = (await db.execute(select(Screener).where(or_(Screener.user_id == user.id, Screener.is_preset)).order_by(Screener.is_preset.desc(), Screener.position, Screener.created_at))).scalars().all()
    return [_out(r) for r in rows]


def _out(r: Screener) -> dict:
    return {"id": str(r.id), "code": r.code, "name": r.name, "description": r.description, "group": r.group, "horizon": r.horizon, "conditions": r.conditions, "form_state": r.form_state,
            "is_preset": r.is_preset, "notify_new": r.notify_new, "count": (r.last_result or {}).get("count"), "date": (r.last_result or {}).get("date"), "chips": describe(r.conditions) if r.conditions else [],
            "created_at": r.created_at.isoformat() if r.created_at else None}


@router.post("/screeners")
async def create_screener(body: ScreenerIn, user: CurrentUser, db: DB):
    dsl, form = await _resolve(db, body)
    ensure_valid(dsl)
    n = await db.scalar(select(func.count(Screener.id)).where(Screener.user_id == user.id))
    if n >= 50:
        raise bad_request("SCREENER_LIMIT", "Tối đa 50 bộ lọc")
    r = Screener(user_id=user.id, name=body.name.strip()[:120], description=body.description, horizon=body.horizon.upper(), conditions=dsl, form_state=form, notify_new=body.notify_new)
    syms = [s for (s,) in (await db.execute(select(StockSnapshot.symbol).where(to_sql(dsl)).limit(200))).all()]
    r.last_result = {"count": len(syms), "symbols": syms}
    db.add(r)
    await db.commit()
    return _out(r)


@router.get("/screeners/{screener_id}")
async def get_screener(screener_id: uuid.UUID, user: CurrentUser, db: DB):
    r = await db.get(Screener, screener_id)
    if not r or (r.user_id != user.id and not r.is_preset):
        raise not_found()
    return _out(r)


@router.put("/screeners/{screener_id}")
async def update_screener(screener_id: uuid.UUID, body: ScreenerIn, user: CurrentUser, db: DB):
    r = await db.get(Screener, screener_id)
    if not r or r.user_id != user.id:
        raise forbidden()
    dsl, form = await _resolve(db, body)
    ensure_valid(dsl)
    r.name, r.description, r.horizon, r.conditions, r.form_state, r.notify_new = body.name.strip()[:120], body.description, body.horizon.upper(), dsl, form, body.notify_new
    await db.commit()
    return _out(r)


@router.delete("/screeners/{screener_id}", response_model=Ok)
async def delete_screener(screener_id: uuid.UUID, user: CurrentUser, db: DB):
    r = await db.get(Screener, screener_id)
    if not r or r.user_id != user.id:
        raise forbidden()
    await db.delete(r)
    await db.commit()
    return Ok(message="Đã xóa bộ lọc")


@router.get("/screeners/presets/{code}/results")
async def preset_results(code: str, user: CurrentUser, db: DB, limit: int = Query(50, le=200)):
    body = RunIn(preset_code=code, limit=limit)
    p = (await db.execute(select(Screener).where(Screener.code == code))).scalar_one_or_none()
    if p:
        body.horizon = p.horizon
    return await run(body, user, db)

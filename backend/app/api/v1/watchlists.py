import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.api.presenters import snapshot_item
from app.core.errors import bad_request, forbidden, not_found
from app.models import Stock, StockSnapshot, Watchlist, WatchlistItem
from app.schemas.common import Ok

router = APIRouter(prefix="/watchlists", tags=["watchlists"])


class WatchlistIn(BaseModel):
    name: str


class ItemIn(BaseModel):
    symbol: str
    note: str | None = None


async def _get(db, user, wid: uuid.UUID) -> Watchlist:
    wl = await db.get(Watchlist, wid)
    if not wl or wl.user_id != user.id:
        raise not_found("Danh sách không tồn tại")
    return wl


@router.get("")
async def list_watchlists(user: CurrentUser, db: DB, horizon: str = "MID"):
    wls = (await db.execute(select(Watchlist).where(Watchlist.user_id == user.id).order_by(Watchlist.position, Watchlist.created_at))).scalars().all()
    if not wls:
        wl = Watchlist(user_id=user.id, name="Theo dõi")
        db.add(wl)
        await db.commit()
        wls = [wl]
    out = []
    for wl in wls:
        items = (await db.execute(select(WatchlistItem, Stock, StockSnapshot).join(Stock, Stock.symbol == WatchlistItem.symbol)
                                  .join(StockSnapshot, StockSnapshot.symbol == WatchlistItem.symbol, isouter=True).where(WatchlistItem.watchlist_id == wl.id).order_by(WatchlistItem.added_at))).all()
        rows = []
        for it, st, sn in items:
            d = snapshot_item(sn, st, horizon.upper()) if sn else {"symbol": st.symbol, "name": st.short_name or st.name_vi}
            d["note"], d["added_at"] = it.note, it.added_at.isoformat() if it.added_at else None
            rows.append(d)
        out.append({"id": str(wl.id), "name": wl.name, "count": len(rows), "items": rows, "changed_today": sum(1 for r in rows if r.get("rating_changed"))})
    return out


@router.post("")
async def create_watchlist(body: WatchlistIn, user: CurrentUser, db: DB):
    n = await db.scalar(select(func.count(Watchlist.id)).where(Watchlist.user_id == user.id))
    if n >= 20:
        raise bad_request("WL_LIMIT", "Tối đa 20 danh sách")
    wl = Watchlist(user_id=user.id, name=body.name.strip()[:80], position=n)
    db.add(wl)
    await db.commit()
    return {"id": str(wl.id), "name": wl.name, "count": 0, "items": []}


@router.put("/{wid}")
async def rename(wid: uuid.UUID, body: WatchlistIn, user: CurrentUser, db: DB):
    wl = await _get(db, user, wid)
    wl.name = body.name.strip()[:80]
    await db.commit()
    return {"id": str(wl.id), "name": wl.name}


@router.delete("/{wid}", response_model=Ok)
async def delete_watchlist(wid: uuid.UUID, user: CurrentUser, db: DB):
    wl = await _get(db, user, wid)
    await db.delete(wl)
    await db.commit()
    return Ok(message="Đã xóa danh sách")


@router.post("/{wid}/items")
async def add_item(wid: uuid.UUID, body: ItemIn, user: CurrentUser, db: DB):
    wl = await _get(db, user, wid)
    sym = body.symbol.upper().strip()
    st = await db.get(Stock, sym)
    if not st or not st.is_active:
        raise not_found("Không có mã này")
    if await db.get(WatchlistItem, (wl.id, sym)) is None:
        n = await db.scalar(select(func.count()).select_from(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id))
        if n >= 200:
            raise bad_request("WL_ITEMS", "Tối đa 200 mã mỗi danh sách")
        db.add(WatchlistItem(watchlist_id=wl.id, symbol=sym, note=body.note))
    await db.commit()
    sn = await db.get(StockSnapshot, sym)
    return snapshot_item(sn, st) if sn else {"symbol": sym, "name": st.name_vi}


@router.delete("/{wid}/items/{symbol}", response_model=Ok)
async def remove_item(wid: uuid.UUID, symbol: str, user: CurrentUser, db: DB):
    wl = await _get(db, user, wid)
    it = await db.get(WatchlistItem, (wl.id, symbol.upper()))
    if it:
        await db.delete(it)
        await db.commit()
    return Ok()


@router.post("/quick-add")
async def quick_add(body: ItemIn, user: CurrentUser, db: DB):
    """One-tap add to the first watchlist (FR-59)."""
    wl = (await db.execute(select(Watchlist).where(Watchlist.user_id == user.id).order_by(Watchlist.position, Watchlist.created_at))).scalars().first()
    if wl is None:
        wl = Watchlist(user_id=user.id, name="Theo dõi")
        db.add(wl)
        await db.flush()
    return await add_item(wl.id, body, user, db)


_ = forbidden

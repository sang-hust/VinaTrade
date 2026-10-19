import csv
import io
import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, File, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import desc, func, select

from app.api.deps import DB, CurrentUser, audit
from app.api.presenters import clean, price_int, row
from app.core.errors import bad_request, not_found
from app.core.vntime import today_vn
from app.engines.risk import correlated_groups, margin_metrics
from app.engines.scoring import RATING_VI
from app.ingestion.icb import ICB_LV2
from app.models import (
    ActionItem,
    IndexDaily,
    Portfolio,
    PortfolioMargin,
    Position,
    RiskGuardEvent,
    StockSnapshot,
    TradeJournal,
    TradePlan,
    TradePlanStep,
    Transaction,
)
from app.schemas.common import Ok
from app.services.portfolio import nav_history, period_pnl, portfolio_view, recompute_positions
from app.services.riskguard import (
    _returns_frame,
    ensure_user_defaults,
    refresh_action_items,
    resolve_action,
)
from app.services.trades import (
    PLAN_TEMPLATES,
    complete_step,
    create_plan,
    record_transaction,
    set_stop_loss,
)

router = APIRouter(tags=["portfolio"])


class PortfolioIn(BaseModel):
    name: str
    broker: str | None = None
    is_paper: bool = False
    uses_margin: bool = False
    initial_capital: float = 0
    fee_pct: float = 0.15
    tax_pct: float = 0.1


class TxIn(BaseModel):
    side: str
    symbol: str | None = None
    quantity: int = 0
    price: float = 0
    trade_date: date | None = None
    fee: float | None = None
    tax: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    amount: float | None = None
    note: str | None = None
    reason: str | None = None
    emotion: str | None = None
    pretrade_check_id: uuid.UUID | None = None
    plan_id: uuid.UUID | None = None
    plan_seq: int | None = None
    confirm_price: bool = False  # the user confirmed a price far from the market (not a typo)


class StopIn(BaseModel):
    stop_loss: float
    take_profit_1: float | None = None
    take_profit_2: float | None = None
    reason: str | None = None


class MarginIn(BaseModel):
    loan: float = 0
    call_ratio: float = 0.35
    force_sell_ratio: float = 0.30
    interest_pct: float | None = None


class ResolveIn(BaseModel):
    action: str
    params: dict | None = None


class PlanIn(BaseModel):
    symbol: str
    template: str | None = None
    params: dict = {}
    name: str | None = None
    steps: list[dict] | None = None


class JournalIn(BaseModel):
    symbol: str | None = None
    transaction_id: uuid.UUID | None = None
    entry_reason: str | None = None
    emotion: str | None = None
    lesson: str | None = None
    tags: list[str] | None = None


async def _pf(db, user, pid: uuid.UUID) -> Portfolio:
    pf = await db.get(Portfolio, pid)
    if not pf or pf.user_id != user.id:
        raise not_found("Danh mục không tồn tại")
    return pf


def _pf_out(pf: Portfolio, view: dict | None = None) -> dict:
    d = {"id": str(pf.id), "name": pf.name, "broker": pf.broker, "is_paper": pf.is_paper, "uses_margin": pf.uses_margin, "cash": clean(pf.cash), "initial_capital": clean(pf.initial_capital),
         "fee_pct": clean(pf.fee_pct), "tax_pct": clean(pf.tax_pct), "label": "Tiền ảo" if pf.is_paper else ("ký quỹ" if pf.uses_margin else "thật")}
    if view:
        d.update({"nav": round(view["nav"]), "market_value": round(view["market_value"]), "unrealized_pnl": round(view["unrealized_pnl"]),
                  "unrealized_pnl_pct": round(view["unrealized_pnl"] / view["cost_basis"] * 100, 2) if view.get("cost_basis") else 0.0,
                  "positions_count": len(view["positions"]), "open_risk": round(view["open_risk"]), "open_risk_pct": round(view["open_risk_pct"], 2)})
    return d


def _pos_out(v) -> dict:
    return {"symbol": v.symbol, "name": v.name, "quantity": v.quantity, "available_qty": v.available_qty, "avg_cost": price_int(v.avg_cost), "price": price_int(v.price), "value": round(v.value),
            "pnl": round(v.pnl), "pnl_pct": round(v.pnl_pct, 2), "weight_pct": round(v.weight_pct, 2), "stop_loss": price_int(v.stop_loss), "initial_stop_loss": price_int(v.initial_stop_loss),
            "take_profit_1": price_int(v.take_profit_1), "take_profit_2": price_int(v.take_profit_2), "industry_code": v.industry_code,
            "industry": ICB_LV2.get(v.industry_code, ("",))[0] if v.industry_code else None, "rating": v.rating, "rating_vi": RATING_VI.get(v.rating), "score": clean(v.score),
            "change_pct": clean(v.change_pct), "beta": clean(v.beta), "sys_stop": price_int(v.extra.get("sys_stop")), "sys_tp1": price_int(v.extra.get("sys_tp1")),
            "entry_low": price_int(v.extra.get("entry_low")), "entry_high": price_int(v.extra.get("entry_high")), "is_chase": bool((v.extra.get("gain_from_base_pct") or 0) > 20 or (v.extra.get("ceiling_streak") or 0) >= 2),
            "risk_score": clean(v.extra.get("risk_score"))}


@router.get("/portfolios")
async def list_portfolios(user: CurrentUser, db: DB):
    pfs = (await db.execute(select(Portfolio).where(Portfolio.user_id == user.id).order_by(Portfolio.is_paper, Portfolio.created_at))).scalars().all()
    out = []
    for pf in pfs:
        out.append(_pf_out(pf, await portfolio_view(db, pf)))
    return out


@router.post("/portfolios")
async def create_portfolio(body: PortfolioIn, user: CurrentUser, db: DB, paper: bool = False):
    n = await db.scalar(select(func.count(Portfolio.id)).where(Portfolio.user_id == user.id))
    if n >= 10:
        raise bad_request("PF_LIMIT", "Tối đa 10 danh mục")
    pf = Portfolio(user_id=user.id, name=body.name.strip()[:80], broker=body.broker, is_paper=body.is_paper or paper, uses_margin=body.uses_margin,
                   initial_capital=body.initial_capital, cash=body.initial_capital, fee_pct=body.fee_pct, tax_pct=body.tax_pct)
    db.add(pf)
    await db.flush()
    if pf.uses_margin:
        db.add(PortfolioMargin(portfolio_id=pf.id))
    await db.commit()
    return _pf_out(pf, await portfolio_view(db, pf))


@router.put("/portfolios/{pid}")
async def update_portfolio(pid: uuid.UUID, body: PortfolioIn, user: CurrentUser, db: DB):
    pf = await _pf(db, user, pid)
    pf.name, pf.broker, pf.uses_margin, pf.fee_pct, pf.tax_pct = body.name.strip()[:80], body.broker, body.uses_margin, body.fee_pct, body.tax_pct
    if body.initial_capital != float(pf.initial_capital or 0):
        pf.initial_capital = body.initial_capital
        await recompute_positions(db, pf.id)
    if pf.uses_margin and await db.get(PortfolioMargin, pf.id) is None:
        db.add(PortfolioMargin(portfolio_id=pf.id))
    await db.commit()
    return _pf_out(pf, await portfolio_view(db, pf))


@router.delete("/portfolios/{pid}", response_model=Ok)
async def delete_portfolio(pid: uuid.UUID, user: CurrentUser, db: DB):
    pf = await _pf(db, user, pid)
    await db.delete(pf)
    await audit(db, user, "PORTFOLIO_DELETE", "portfolio", str(pid))
    await db.commit()
    return Ok(message="Đã xóa danh mục")


@router.get("/portfolios/{pid}")
async def get_portfolio(pid: uuid.UUID, user: CurrentUser, db: DB):
    pf = await _pf(db, user, pid)
    view = await portfolio_view(db, pf)
    lim, g = await ensure_user_defaults(db, user)
    items = (await db.execute(select(ActionItem).where(ActionItem.portfolio_id == pf.id, ActionItem.status == "OPEN").order_by(ActionItem.created_at))).scalars().all()
    order = {"URGENT": 0, "RISK": 1, "SUGGEST": 2}
    items = sorted(items, key=lambda a: (order.get(a.priority, 9), -a.rank_score))
    pnl = await period_pnl(db, pf) if not pf.is_paper else {"week_pnl_pct": 0, "month_pnl_pct": 0, "week_pnl_vnd": 0, "month_pnl_vnd": 0}
    # VN-Index today
    idx = (await db.execute(select(IndexDaily).where(IndexDaily.index_code == "VNINDEX").order_by(desc(IndexDaily.trade_date)).limit(2))).scalars().all()
    idx_chg = (idx[0].close / idx[1].close - 1) * 100 if len(idx) == 2 and idx[1].close else 0.0
    today_pnl = sum((v.change_pct or 0) / 100 * v.value / (1 + (v.change_pct or 0) / 100) for v in view["positions"])
    stress = []
    for shock in (-10, -20, -30):
        loss = sum(v.value * (v.beta or 1.0) * shock / 100 for v in view["positions"])
        stress.append({"shock_pct": shock, "loss": round(loss), "nav_after": round(view["nav"] + loss)})
    await db.commit()
    return {
        "portfolio": _pf_out(pf, view),
        "kpis": {"nav": round(view["nav"]), "cash": round(view["cash"]), "market_value": round(view["market_value"]), "unrealized_pnl": round(view["unrealized_pnl"]),
                 "unrealized_pnl_pct": round(view["unrealized_pnl"] / view["cost_basis"] * 100, 2) if view.get("cost_basis") else 0.0,
                 "today_pnl": round(today_pnl), "today_pnl_pct": round(today_pnl / view["nav"] * 100, 2) if view["nav"] else 0.0, "vnindex_change_pct": round(idx_chg, 2),
                 "open_risk": round(view["open_risk"]), "open_risk_pct": round(view["open_risk_pct"], 2), "stress": stress,
                 "week_pnl_pct": round(pnl["week_pnl_pct"], 2), "month_pnl_pct": round(pnl["month_pnl_pct"], 2)},
        "action_items": [_item_out(a) for a in items],
        "positions": [_pos_out(v) for v in view["positions"]],
        "sector_weights": [{"code": k, "name": ICB_LV2.get(k, ("Khác",))[0], "weight_pct": round(w, 2), "over_limit": w > float(lim.max_sector_pct)} for k, w in sorted(view["sector_weights"].items(), key=lambda kv: -kv[1])],
        "cash_weight_pct": round(view["cash"] / view["nav"] * 100, 2) if view["nav"] else 100.0,
        "guard": {"mode": g.mode, "release_at": clean(g.release_at), "reason": g.reason, "week_pnl_pct": clean(g.week_pnl_pct), "month_pnl_pct": clean(g.month_pnl_pct)},
        "limits": row(lim, ["max_risk_per_trade_pct", "max_position_pct", "max_sector_pct", "max_correlated_group_pct", "weekly_loss_limit_pct", "monthly_loss_limit_pct"]),
        "plans": [{"symbol": p.symbol, "id": str(p.id), "name": p.name, "status": p.status} for p in (await db.execute(select(TradePlan).where(TradePlan.portfolio_id == pf.id, TradePlan.status == "ACTIVE"))).scalars()],
    }


def _item_out(a: ActionItem) -> dict:
    return {"id": str(a.id), "priority": a.priority, "priority_vi": {"URGENT": "KHẨN", "RISK": "RỦI RO", "SUGGEST": "GỢI Ý"}.get(a.priority), "kind": a.kind, "symbol": a.symbol, "title": a.title,
            "detail": a.detail, "actions": a.actions, "status": a.status, "result_text": a.result_text, "created_at": clean(a.created_at), "resolved_at": clean(a.resolved_at)}


@router.get("/portfolios/{pid}/positions")
async def positions(pid: uuid.UUID, user: CurrentUser, db: DB):
    pf = await _pf(db, user, pid)
    view = await portfolio_view(db, pf)
    return [_pos_out(v) for v in view["positions"]]


@router.put("/portfolios/{pid}/positions/{symbol}/stop")
async def update_stop(pid: uuid.UUID, symbol: str, body: StopIn, user: CurrentUser, db: DB):
    pf = await _pf(db, user, pid)
    pos = await set_stop_loss(db, user, pf, symbol, body.stop_loss, body.reason)
    if body.take_profit_1 is not None:
        pos.take_profit_1 = body.take_profit_1
    if body.take_profit_2 is not None:
        pos.take_profit_2 = body.take_profit_2
    await db.commit()
    await refresh_action_items(db, user, pf, notify_urgent=False)
    await db.commit()
    return Ok(message=f"Đã cập nhật cắt lỗ {symbol.upper()}")


@router.get("/portfolios/{pid}/transactions")
async def transactions(pid: uuid.UUID, user: CurrentUser, db: DB, symbol: str | None = None, page: int = 1, size: int = Query(50, le=200)):
    pf = await _pf(db, user, pid)
    stmt = select(Transaction).where(Transaction.portfolio_id == pf.id)
    if symbol:
        stmt = stmt.where(Transaction.symbol == symbol.upper())
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (await db.execute(stmt.order_by(desc(Transaction.trade_date), desc(Transaction.created_at)).offset((page - 1) * size).limit(size))).scalars().all()
    return {"items": [{**row(t, ["symbol", "side", "quantity", "price", "fee", "tax", "amount", "trade_date", "stop_loss", "take_profit", "note", "reason", "emotion", "created_at"]), "id": str(t.id), "pretrade_check_id": str(t.pretrade_check_id) if t.pretrade_check_id else None} for t in rows],
            "total": total, "page": page, "size": size}


@router.post("/portfolios/{pid}/transactions")
async def add_transaction(pid: uuid.UUID, body: TxIn, user: CurrentUser, db: DB):
    pf = await _pf(db, user, pid)
    side = body.side.upper()
    if side == "BUY" and not body.pretrade_check_id:
        from app.models import PretradeCheck
        # BR: every buy goes through pretrade; accept a recent check for the same symbol as proof
        recent = (await db.execute(select(PretradeCheck).where(PretradeCheck.user_id == user.id, PretradeCheck.symbol == (body.symbol or "").upper(),
                                                                PretradeCheck.created_at >= datetime.now().astimezone() - timedelta(hours=12)).order_by(desc(PretradeCheck.created_at)).limit(1))).scalar_one_or_none()
        if recent is None:
            raise bad_request("PRETRADE_REQUIRED", "Mọi lệnh mua đều phải qua Kiểm tra trước khi mua", {"pretrade_required": True})
        body.pretrade_check_id = recent.id
    # Typo guard: a fill price more than ±30% from the latest close is almost always a missing digit (5.600 vs 56.000)
    if side in ("BUY", "SELL") and body.symbol and body.price and not body.confirm_price:
        sn = await db.get(StockSnapshot, body.symbol.upper())
        if sn and sn.price:
            dev = (float(body.price) / float(sn.price) - 1) * 100
            if abs(dev) > 30:
                guess = float(sn.price)
                raise bad_request("PRICE_SUSPECT", f"Giá {float(body.price):,.0f} đ lệch {dev:+.0f}% so với giá thị trường {float(sn.price):,.0f} đ của {body.symbol.upper()}. Có phải bạn muốn nhập {guess:,.0f} đ? Nếu đúng là giá đã khớp, xác nhận để ghi.".replace(",", "."),
                                  {"market_price": float(sn.price), "suggested_price": guess})
    # Cash guard: a real portfolio without margin cannot go negative
    if side == "BUY" and not pf.is_paper and not pf.uses_margin:
        need = float(body.price or 0) * int(body.quantity or 0) + float(body.fee or 0)
        cash = float(pf.cash or 0)
        if need > cash + 1:
            raise bad_request("CASH_INSUFFICIENT", f"Tiền mặt {cash:,.0f} đ không đủ cho lệnh {need:,.0f} đ. Ghi 'Nộp tiền' vào danh mục (hoặc sửa vốn ban đầu), hoặc bật ký quỹ nếu bạn đang vay.".replace(",", "."),
                              {"cash": cash, "need": need})
    # BR-16 / M12: averaging down on a losing position needs a reason
    if side == "BUY" and body.symbol:
        pos = await db.get(Position, (pf.id, body.symbol.upper()))
        if pos and pos.quantity > 0 and pos.avg_cost and body.price < pos.avg_cost * 0.98:
            if not (body.reason and len(body.reason.strip()) >= 10):
                pnl = (body.price / pos.avg_cost - 1) * 100
                raise bad_request("AVERAGE_DOWN_REASON", f"{body.symbol.upper()} đang lỗ {abs(pnl):.1f}%. Mua thêm lúc này là bình quân giá xuống, trái với giới hạn của bạn. Ghi lý do để tiếp tục.")
            db.add(RiskGuardEvent(user_id=user.id, kind="AVERAGE_DOWN", symbol=body.symbol.upper(), detail={"price": body.price, "avg_cost": pos.avg_cost}, note=body.reason))
    tx = await record_transaction(db, pf, side=side, symbol=body.symbol, quantity=body.quantity, price=body.price, trade_date=body.trade_date or today_vn(), fee=body.fee, tax=body.tax,
                                  stop_loss=body.stop_loss, take_profit=body.take_profit, note=body.note, reason=body.reason, emotion=body.emotion, pretrade_check_id=body.pretrade_check_id, amount=body.amount)
    if body.plan_id and body.plan_seq:
        plan = await db.get(TradePlan, body.plan_id)
        if plan and plan.user_id == user.id:
            await complete_step(db, plan, body.plan_seq, tx.id)
    if body.reason or body.emotion:
        db.add(TradeJournal(user_id=user.id, transaction_id=tx.id, symbol=tx.symbol, entry_reason=body.reason, emotion=body.emotion))
    await db.commit()
    await refresh_action_items(db, user, pf, notify_urgent=False)
    await db.commit()
    return {"id": str(tx.id), "message": f"Đã ghi {('mua' if side == 'BUY' else 'bán') if side in ('BUY', 'SELL') else side.lower()} {tx.quantity:,} {tx.symbol or ''}".replace(",", "."),
            "reminder": "Nhớ đặt lệnh dừng lỗ tại công ty chứng khoán." if side == "BUY" else None}


@router.delete("/portfolios/{pid}/transactions/{tid}", response_model=Ok)
async def delete_transaction(pid: uuid.UUID, tid: uuid.UUID, user: CurrentUser, db: DB):
    pf = await _pf(db, user, pid)
    tx = await db.get(Transaction, tid)
    if not tx or tx.portfolio_id != pf.id:
        raise not_found()
    await db.delete(tx)
    await db.flush()
    await recompute_positions(db, pf.id)
    await db.commit()
    return Ok(message="Đã xóa giao dịch")


@router.post("/portfolios/{pid}/import")
async def import_transactions(pid: uuid.UUID, user: CurrentUser, db: DB, file: UploadFile = File(...)):  # noqa: B008
    """CSV/XLSX broker statement: columns (vi/en aliases) ngày, mã, mua/bán, khối lượng, giá, phí, thuế."""
    pf = await _pf(db, user, pid)
    raw = await file.read()
    rows: list[dict] = []
    name = (file.filename or "").lower()
    if name.endswith(".xlsx"):
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        header = [str(h or "").strip().lower() for h in next(it)]
        for r in it:
            rows.append(dict(zip(header, r, strict=False)))
    else:
        text = raw.decode("utf-8-sig", errors="ignore")
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t") if text else csv.excel
        for r in csv.DictReader(io.StringIO(text), dialect=dialect):
            rows.append({(k or "").strip().lower(): v for k, v in r.items()})
    alias = {"date": ["ngày", "ngay", "date", "trade_date", "ngày gd"], "symbol": ["mã", "ma", "symbol", "mã ck", "ticker"], "side": ["mua/bán", "loại", "side", "lệnh", "loai"],
             "qty": ["khối lượng", "kl", "quantity", "qty", "so luong", "số lượng"], "price": ["giá", "gia", "price", "giá khớp"], "fee": ["phí", "phi", "fee"], "tax": ["thuế", "thue", "tax"]}

    def pick(r, key):
        for a in alias[key]:
            if a in r and r[a] not in (None, ""):
                return r[a]
        return None

    n, errors = 0, []
    for i, r in enumerate(rows, start=2):
        try:
            d = pick(r, "date")
            dt = d if isinstance(d, date) else datetime.strptime(str(d).strip()[:10].replace("-", "/"), "%d/%m/%Y").date() if "/" in str(d) or "-" in str(d) else None
            if dt is None:
                dt = datetime.fromisoformat(str(d)[:10]).date()
            side_raw = str(pick(r, "side") or "").strip().lower()
            side = "BUY" if side_raw in ("mua", "buy", "b", "m") else "SELL" if side_raw in ("bán", "ban", "sell", "s", "b án") else None
            if not side:
                raise ValueError("loại lệnh")
            qty = int(float(str(pick(r, "qty")).replace(".", "").replace(",", "")))
            px = float(str(pick(r, "price")).replace(".", "").replace(",", "."))
            if px < 1000:
                px *= 1000
            fee = float(str(pick(r, "fee") or 0).replace(".", "").replace(",", ".") or 0) or None
            tax = float(str(pick(r, "tax") or 0).replace(".", "").replace(",", ".") or 0) or None
            await record_transaction(db, pf, side=side, symbol=str(pick(r, "symbol")).upper(), quantity=qty, price=px, trade_date=dt, fee=fee, tax=tax, note="Nhập file")
            n += 1
        except Exception as e:  # noqa: BLE001
            errors.append({"row": i, "error": str(e)[:120]})
    await db.commit()
    return {"imported": n, "errors": errors[:50]}


@router.get("/portfolios/{pid}/performance")
async def performance(pid: uuid.UUID, user: CurrentUser, db: DB, days: int = 180):
    pf = await _pf(db, user, pid)
    start = today_vn() - timedelta(days=days)
    series = await nav_history(db, pf, start)
    return {"series": [{"date": d.isoformat(), "nav": round(v)} for d, v in series]}


@router.get("/portfolios/{pid}/benchmark")
async def benchmark(pid: uuid.UUID, user: CurrentUser, db: DB, days: int = 180):
    pf = await _pf(db, user, pid)
    start = today_vn() - timedelta(days=days)
    series = await nav_history(db, pf, start)
    if len(series) < 2:
        return {"portfolio_pct": 0.0, "vnindex_pct": 0.0, "vn30_pct": 0.0, "savings_pct": round(6.0 * days / 365, 2), "sharpe": None, "max_drawdown_pct": 0.0, "series": []}
    import numpy as np

    navs = np.array([v for _, v in series])
    rets = np.diff(navs) / navs[:-1]
    pf_pct = (navs[-1] / navs[0] - 1) * 100 if navs[0] else 0.0
    dd = float(((navs / np.maximum.accumulate(navs)) - 1).min() * 100)
    sharpe = float(rets.mean() / rets.std() * np.sqrt(250)) if rets.std() else None

    async def idx_pct(code):
        rows = (await db.execute(select(IndexDaily.trade_date, IndexDaily.close).where(IndexDaily.index_code == code, IndexDaily.trade_date >= series[0][0]).order_by(IndexDaily.trade_date))).all()
        return (rows[-1][1] / rows[0][1] - 1) * 100 if len(rows) > 1 else 0.0, rows

    vn_pct, vn_rows = await idx_pct("VNINDEX")
    vn30_pct, _ = await idx_pct("VN30")
    base_idx = vn_rows[0][1] if vn_rows else None
    idx_map = {d: c for d, c in vn_rows}
    return {"portfolio_pct": round(pf_pct, 2), "vnindex_pct": round(vn_pct, 2), "vn30_pct": round(vn30_pct, 2), "savings_pct": round(6.0 * days / 365, 2), "sharpe": round(sharpe, 2) if sharpe else None,
            "max_drawdown_pct": round(dd, 2), "series": [{"date": d.isoformat(), "portfolio": round((v / navs[0] - 1) * 100, 2), "vnindex": round((idx_map[d] / base_idx - 1) * 100, 2) if d in idx_map and base_idx else None} for d, v in series]}


@router.get("/portfolios/{pid}/action-items")
async def action_items(pid: uuid.UUID, user: CurrentUser, db: DB, status: str = "OPEN", refresh: bool = False):
    pf = await _pf(db, user, pid)
    if refresh:
        items = await refresh_action_items(db, user, pf, notify_urgent=False)
        await db.commit()
    else:
        order = {"URGENT": 0, "RISK": 1, "SUGGEST": 2}
        items = sorted((await db.execute(select(ActionItem).where(ActionItem.portfolio_id == pf.id, ActionItem.status == status.upper()))).scalars().all(), key=lambda a: (order.get(a.priority, 9), -a.rank_score))
    return [_item_out(a) for a in items]


@router.post("/action-items/{item_id}/resolve")
async def resolve(item_id: uuid.UUID, body: ResolveIn, user: CurrentUser, db: DB):
    item = await db.get(ActionItem, item_id)
    if not item or item.user_id != user.id:
        raise not_found()
    if item.status != "OPEN":
        raise bad_request("ITEM_CLOSED", "Việc này đã được xử lý")
    result = await resolve_action(db, user, item, body.action.upper(), body.params or {})
    await db.commit()
    if result != "open":
        pf = await db.get(Portfolio, item.portfolio_id)
        await refresh_action_items(db, user, pf, notify_urgent=False)
        await db.commit()
    open_count = await db.scalar(select(func.count(ActionItem.id)).where(ActionItem.portfolio_id == item.portfolio_id, ActionItem.status == "OPEN"))
    return {"result": result, "item": _item_out(item), "open_count": open_count}


# ---------------------------------------------------------------- margin / stress / correlation
@router.get("/portfolios/{pid}/margin")
async def get_margin(pid: uuid.UUID, user: CurrentUser, db: DB):
    pf = await _pf(db, user, pid)
    m = await db.get(PortfolioMargin, pf.id)
    view = await portfolio_view(db, pf)
    positions = [{"symbol": v.symbol, "quantity": v.quantity, "price": v.price, "beta": v.beta or 1.0} for v in view["positions"]]
    metrics = margin_metrics(positions, view["cash"], float(m.loan) if m else 0.0, m.call_ratio if m else 0.35, m.force_sell_ratio if m else 0.30)
    return {"settings": row(m, ["loan", "call_ratio", "force_sell_ratio", "interest_pct"]) if m else None, "metrics": metrics}


@router.put("/portfolios/{pid}/margin")
async def set_margin(pid: uuid.UUID, body: MarginIn, user: CurrentUser, db: DB):
    pf = await _pf(db, user, pid)
    m = await db.get(PortfolioMargin, pf.id)
    if m is None:
        m = PortfolioMargin(portfolio_id=pf.id)
        db.add(m)
    m.loan, m.call_ratio, m.force_sell_ratio, m.interest_pct = body.loan, body.call_ratio, body.force_sell_ratio, body.interest_pct
    pf.uses_margin = body.loan > 0
    await db.commit()
    return await get_margin(pid, user, db)


@router.post("/portfolios/{pid}/stress-test")
async def stress_test(pid: uuid.UUID, user: CurrentUser, db: DB, shocks: str = "-10,-20,-30"):
    pf = await _pf(db, user, pid)
    m = await db.get(PortfolioMargin, pf.id)
    view = await portfolio_view(db, pf)
    positions = [{"symbol": v.symbol, "quantity": v.quantity, "price": v.price, "beta": v.beta or 1.0} for v in view["positions"]]
    sh = tuple(int(x) for x in shocks.split(",") if x.strip())
    return margin_metrics(positions, view["cash"], float(m.loan) if m else 0.0, m.call_ratio if m else 0.35, m.force_sell_ratio if m else 0.30, shocks=sh)["scenarios"]


@router.get("/portfolios/{pid}/correlation")
async def correlation(pid: uuid.UUID, user: CurrentUser, db: DB):
    pf = await _pf(db, user, pid)
    view = await portfolio_view(db, pf)
    lim, _ = await ensure_user_defaults(db, user)
    syms = [v.symbol for v in view["positions"]]
    rets = await _returns_frame(db, syms)
    groups, R = correlated_groups(rets, {v.symbol: v.weight_pct for v in view["positions"]}) if not rets.empty else ([], None)
    matrix = {a: {b: clean(R.loc[a, b]) for b in R.columns} for a in R.index} if R is not None else {}
    return {"groups": [{**g, "over_limit": g["weight_pct"] > float(lim.max_correlated_group_pct)} for g in groups], "matrix": matrix, "limit_pct": clean(lim.max_correlated_group_pct)}


# ---------------------------------------------------------------- trade plans
def _plan_out(p: TradePlan, steps: list[TradePlanStep]) -> dict:
    return {"id": str(p.id), "symbol": p.symbol, "name": p.name, "template": p.template, "status": p.status, "portfolio_id": str(p.portfolio_id) if p.portfolio_id else None, "created_at": clean(p.created_at),
            "steps": [{**row(s, ["seq", "title", "condition", "action", "fraction", "price", "new_stop", "status", "triggered_at", "done_at"]), "transaction_id": str(s.transaction_id) if s.transaction_id else None} for s in steps]}


@router.get("/trade-plans")
async def list_plans(user: CurrentUser, db: DB, symbol: str | None = None, portfolio_id: uuid.UUID | None = None, status: str | None = "ACTIVE"):
    stmt = select(TradePlan).where(TradePlan.user_id == user.id)
    if symbol:
        stmt = stmt.where(TradePlan.symbol == symbol.upper())
    if portfolio_id:
        stmt = stmt.where(TradePlan.portfolio_id == portfolio_id)
    if status:
        stmt = stmt.where(TradePlan.status == status.upper())
    plans = (await db.execute(stmt.order_by(desc(TradePlan.created_at)))).scalars().all()
    out = []
    for p in plans:
        steps = (await db.execute(select(TradePlanStep).where(TradePlanStep.plan_id == p.id).order_by(TradePlanStep.seq))).scalars().all()
        out.append(_plan_out(p, steps))
    return out


@router.get("/trade-plans/templates")
async def plan_templates(user: CurrentUser):
    return [{"code": k, "name": v["name"], "params": {"BREAKOUT_3": ["breakout", "pullback", "entry", "stop"], "BUY_SUPPORT": ["support", "stop"], "SCALE_OUT": ["tp1", "tp2", "entry"]}[k]} for k, v in PLAN_TEMPLATES.items()]


@router.post("/trade-plans")
async def create_trade_plan(body: PlanIn, user: CurrentUser, db: DB, portfolio_id: uuid.UUID | None = None):
    pf = await _pf(db, user, portfolio_id) if portfolio_id else None
    n = await db.scalar(select(func.count(TradePlan.id)).where(TradePlan.user_id == user.id, TradePlan.status == "ACTIVE"))
    if n >= 50:
        raise bad_request("PLAN_LIMIT", "Tối đa 50 kế hoạch đang hoạt động")
    plan = await create_plan(db, user, pf, body.symbol, body.template, body.params, body.name, body.steps)
    await db.commit()
    steps = (await db.execute(select(TradePlanStep).where(TradePlanStep.plan_id == plan.id).order_by(TradePlanStep.seq))).scalars().all()
    return _plan_out(plan, steps)


@router.put("/trade-plans/{plan_id}")
async def update_plan(plan_id: uuid.UUID, user: CurrentUser, db: DB, status: str | None = None, name: str | None = None):
    p = await db.get(TradePlan, plan_id)
    if not p or p.user_id != user.id:
        raise not_found()
    if status in ("ACTIVE", "PAUSED", "CANCELLED"):
        p.status = status
    if name:
        p.name = name[:120]
    await db.commit()
    steps = (await db.execute(select(TradePlanStep).where(TradePlanStep.plan_id == p.id).order_by(TradePlanStep.seq))).scalars().all()
    return _plan_out(p, steps)


@router.post("/trade-plans/{plan_id}/steps")
async def add_step(plan_id: uuid.UUID, body: dict, user: CurrentUser, db: DB):
    p = await db.get(TradePlan, plan_id)
    if not p or p.user_id != user.id:
        raise not_found()
    from app.screener.dsl import ensure_valid
    cond = body.get("condition")
    if not cond or not body.get("title") or body.get("action") not in ("BUY", "SELL", "TAKE_PROFIT", "MOVE_STOP", "STOP_LOSS"):
        raise bad_request("STEP_INVALID", "Bước cần tiêu đề, điều kiện và hành động hợp lệ")
    ensure_valid(cond)
    seq = (await db.scalar(select(func.max(TradePlanStep.seq)).where(TradePlanStep.plan_id == p.id)) or 0) + 1
    db.add(TradePlanStep(plan_id=p.id, seq=seq, title=body["title"][:200], condition=cond, action=body["action"], fraction=body.get("fraction"), price=body.get("price"), new_stop=body.get("new_stop")))
    if p.status == "DONE":
        p.status = "ACTIVE"
    await db.commit()
    steps = (await db.execute(select(TradePlanStep).where(TradePlanStep.plan_id == p.id).order_by(TradePlanStep.seq))).scalars().all()
    return _plan_out(p, steps)


@router.put("/trade-plans/{plan_id}/steps/{seq}")
async def update_step(plan_id: uuid.UUID, seq: int, body: dict, user: CurrentUser, db: DB):
    p = await db.get(TradePlan, plan_id)
    if not p or p.user_id != user.id:
        raise not_found()
    if body.get("status") in ("DONE", "SKIPPED"):
        await complete_step(db, p, seq, skip=body["status"] == "SKIPPED")
    else:
        s = await db.get(TradePlanStep, (p.id, seq))
        if not s:
            raise not_found()
        for k in ("title", "condition", "action", "fraction", "price", "new_stop"):
            if k in body:
                setattr(s, k, body[k])
        if "condition" in body:
            from app.screener.dsl import ensure_valid
            ensure_valid(body["condition"])
    await db.commit()
    steps = (await db.execute(select(TradePlanStep).where(TradePlanStep.plan_id == p.id).order_by(TradePlanStep.seq))).scalars().all()
    return _plan_out(p, steps)


@router.delete("/trade-plans/{plan_id}", response_model=Ok)
async def delete_plan(plan_id: uuid.UUID, user: CurrentUser, db: DB):
    p = await db.get(TradePlan, plan_id)
    if not p or p.user_id != user.id:
        raise not_found()
    await db.delete(p)
    await db.commit()
    return Ok(message="Đã xóa kế hoạch")


# ---------------------------------------------------------------- journal
@router.get("/journal")
async def journal(user: CurrentUser, db: DB, limit: int = 100):
    rows = (await db.execute(select(TradeJournal).where(TradeJournal.user_id == user.id).order_by(desc(TradeJournal.created_at)).limit(limit))).scalars().all()
    return [{**row(j, ["symbol", "entry_reason", "emotion", "lesson", "tags", "created_at"]), "id": str(j.id), "transaction_id": str(j.transaction_id) if j.transaction_id else None} for j in rows]


@router.post("/journal")
async def add_journal(body: JournalIn, user: CurrentUser, db: DB):
    j = TradeJournal(user_id=user.id, **body.model_dump())
    db.add(j)
    await db.commit()
    return {"id": str(j.id)}


@router.put("/journal/{jid}")
async def update_journal(jid: uuid.UUID, body: JournalIn, user: CurrentUser, db: DB):
    j = await db.get(TradeJournal, jid)
    if not j or j.user_id != user.id:
        raise not_found()
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(j, k, v)
    await db.commit()
    return {"id": str(j.id)}


@router.get("/journal/stats")
async def journal_stats(user: CurrentUser, db: DB):
    """Win rate, avg hold, common mistakes from realized trades (FR-30)."""
    from app.services.coach import trade_metrics

    return await trade_metrics(db, user, weeks=52)

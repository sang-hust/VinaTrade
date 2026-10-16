"""Health, Telegram webhook, realtime websocket (alerts / market heartbeat)."""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import desc, func, select, text

from app.api.deps import DB
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import decode_access_token
from app.core.vntime import is_market_open, now_vn, session_state
from app.models import ActionItem, Alert, MarketRegime, RiskGuardStatus, StockSnapshot, User
from app.services.notify import send_telegram

router = APIRouter(tags=["system"])
log = logging.getLogger(__name__)


@router.get("/health")
async def health(db: DB):
    await db.execute(text("SELECT 1"))
    last = (await db.execute(select(func.max(StockSnapshot.trade_date)))).scalar()
    return {"status": "ok", "app": settings.app_name, "time": now_vn().isoformat(), "session": session_state(), "last_snapshot": last.isoformat() if last else None,
            "ai": bool(settings.anthropic_api_key), "telegram": bool(settings.telegram_bot_token)}


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request, db: DB):
    if settings.telegram_webhook_secret and request.headers.get("x-telegram-bot-api-secret-token") != settings.telegram_webhook_secret:
        return {"ok": False}
    upd = await request.json()
    msg = upd.get("message") or upd.get("edited_message") or {}
    chat_id = str((msg.get("chat") or {}).get("id") or "")
    text_ = (msg.get("text") or "").strip()
    if not chat_id or not text_:
        return {"ok": True}
    parts = text_.split()
    cmd = parts[0].lower().split("@")[0]
    reply = None
    user = (await db.execute(select(User).where(User.telegram_chat_id == chat_id))).scalar_one_or_none()
    if cmd == "/start":
        code = parts[1].strip().upper() if len(parts) > 1 else None
        if code:
            u = (await db.execute(select(User).where(User.telegram_link_code == code))).scalar_one_or_none()
            if u:
                u.telegram_chat_id, u.telegram_link_code = chat_id, None
                await db.commit()
                reply = f"✅ Đã liên kết Telegram với tài khoản {u.email}. Bạn sẽ nhận cảnh báo tại đây."
            else:
                reply = "Mã liên kết không hợp lệ. Lấy mã mới trong ứng dụng: Tài khoản → Nhận cảnh báo → Telegram."
        else:
            reply = "Xin chào! Mở ứng dụng Vinatrade → Tài khoản → Telegram để lấy mã, rồi gửi: /start MÃ"
    elif not user:
        reply = "Tài khoản chưa liên kết. Gửi /start MÃ với mã lấy trong ứng dụng."
    elif cmd in ("/gia", "/price"):
        sym = parts[1].upper() if len(parts) > 1 else None
        sn = await db.get(StockSnapshot, sym) if sym else None
        if sn:
            from app.engines.scoring import RATING_VI
            reply = (f"<b>{sym}</b> {sn.price:,.0f} đ ({sn.change_pct:+.2f}%)\nKhuyến nghị: {RATING_VI.get(sn.rating, '—')} · {sn.score_mid:.0f}/100\n"
                     f"Vùng mua {sn.entry_low:,.0f}–{sn.entry_high:,.0f}, cắt lỗ {sn.stop_loss:,.0f}, chốt lời {sn.take_profit_1:,.0f}").replace(",", ".")
        else:
            reply = "Dùng: /gia FPT"
    elif cmd in ("/canhbao", "/alerts"):
        rows = (await db.execute(select(Alert).where(Alert.user_id == user.id).order_by(desc(Alert.created_at)).limit(5))).scalars().all()
        reply = "\n".join(f"• {a.title}" for a in rows) or "Chưa có cảnh báo."
    elif cmd in ("/thitruong", "/market"):
        reg = (await db.execute(select(MarketRegime).order_by(desc(MarketRegime.trade_date)).limit(1))).scalar_one_or_none()
        reply = reg.headline if reg else "Chưa có dữ liệu."
    elif cmd == "/stop":
        user.telegram_chat_id = None
        await db.commit()
        reply = "Đã hủy liên kết. Bạn sẽ không nhận cảnh báo qua Telegram nữa."
    else:
        reply = "Lệnh: /gia MÃ · /canhbao · /thitruong · /stop"
    if reply:
        await send_telegram(chat_id, reply)
    return {"ok": True}


# ---------------------------------------------------------------- websocket
class Hub:
    def __init__(self):
        self.clients: dict[WebSocket, set[str]] = {}
        self.users: dict[WebSocket, uuid.UUID] = {}

    async def broadcast(self, channel: str, data: dict, user_id: uuid.UUID | None = None):
        dead = []
        for ws, chans in list(self.clients.items()):
            if channel in chans or channel.split(":")[0] in chans:
                if user_id and self.users.get(ws) != user_id:
                    continue
                try:
                    await ws.send_text(json.dumps({"ch": channel, "ts": datetime.now(UTC).isoformat(), "data": data}, ensure_ascii=False, default=str))
                except Exception:  # noqa: BLE001
                    dead.append(ws)
        for ws in dead:
            self.clients.pop(ws, None)
            self.users.pop(ws, None)


hub = Hub()


@router.websocket("/ws")
async def websocket(ws: WebSocket):
    token = ws.query_params.get("token")
    try:
        payload = decode_access_token(token or "")
        uid = uuid.UUID(payload["sub"])
    except Exception:  # noqa: BLE001
        await ws.close(code=4401)
        return
    await ws.accept()
    hub.clients[ws] = {"system"}
    hub.users[ws] = uid
    try:
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=25)
            except TimeoutError:
                # heartbeat with unread count + guard state + market state
                async with SessionLocal() as db:
                    unread = await db.scalar(select(func.count(Alert.id)).where(Alert.user_id == uid, Alert.read_at.is_(None)))
                    g = await db.get(RiskGuardStatus, uid)
                    open_items = await db.scalar(select(func.count(ActionItem.id)).where(ActionItem.user_id == uid, ActionItem.status == "OPEN"))
                await ws.send_text(json.dumps({"ch": "system", "data": {"ping": True, "unread": unread, "guard_mode": g.mode if g else "NORMAL", "open_items": open_items, "market_open": is_market_open(), "session": session_state()}}))
                continue
            try:
                m = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if m.get("action") == "subscribe":
                hub.clients[ws] |= set(m.get("channels") or [])
            elif m.get("action") == "unsubscribe":
                hub.clients[ws] -= set(m.get("channels") or [])
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.pop(ws, None)
        hub.users.pop(ws, None)

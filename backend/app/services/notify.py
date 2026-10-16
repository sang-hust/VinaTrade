"""Alert creation + delivery: in-app always; Telegram / email / push when configured and enabled by the user.
Handles quiet hours, per-day cap and dedupe (FR-26)."""

import asyncio
import logging
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.vntime import now_vn
from app.models import Alert, NotificationDelivery, User, UserDevice, UserSettings

log = logging.getLogger(__name__)


def _in_quiet_hours(s: UserSettings | None) -> bool:
    if not s or not s.quiet_start or not s.quiet_end:
        return False
    t = now_vn().strftime("%H:%M")
    a, b = s.quiet_start, s.quiet_end
    return (a <= t < b) if a <= b else (t >= a or t < b)


async def create_alert(db: AsyncSession, user: User, *, kind: str, title: str, body: str | None = None, priority: str = "HIGH",
                       symbol: str | None = None, deeplink: str | None = None, data: dict | None = None, dedupe_key: str | None = None,
                       rule_id=None, signal_id: int | None = None, channels: list[str] | None = None, dedupe_hours: int = 24) -> Alert | None:
    """Creates the alert row (+ deliveries). Returns None when deduped or over the daily cap."""
    if dedupe_key:
        since = datetime.now(UTC) - timedelta(hours=dedupe_hours)
        dup = await db.scalar(select(Alert.id).where(Alert.user_id == user.id, Alert.dedupe_key == dedupe_key, Alert.created_at >= since))
        if dup:
            return None
    s = await db.get(UserSettings, user.id)
    if priority != "URGENT":
        day_start = now_vn().replace(hour=0, minute=0, second=0, microsecond=0)
        n_today = await db.scalar(select(func.count(Alert.id)).where(Alert.user_id == user.id, Alert.created_at >= day_start))
        if s and n_today >= (s.max_alerts_per_day or 40):
            return None
    alert = Alert(user_id=user.id, rule_id=rule_id, signal_id=signal_id, symbol=symbol, kind=kind, priority=priority, title=title,
                  body=body, deeplink=deeplink, data=data, dedupe_key=dedupe_key)
    db.add(alert)
    await db.flush()
    quiet = _in_quiet_hours(s) and priority != "URGENT"
    wanted = set(channels or [])
    if s:
        if s.notify_telegram:
            wanted.add("telegram")
        if s.notify_push:
            wanted.add("push")
        if s.notify_email and kind in ("REPORT", "SYSTEM"):
            wanted.add("email")
    if not channels:
        pass
    db.add(NotificationDelivery(alert_id=alert.id, channel="inapp", status="SENT", sent_at=datetime.now(UTC)))
    for ch in ("telegram", "push", "email"):
        if ch not in wanted:
            continue
        if quiet:
            db.add(NotificationDelivery(alert_id=alert.id, channel=ch, status="SKIPPED", error="quiet hours"))
            continue
        db.add(NotificationDelivery(alert_id=alert.id, channel=ch, status="PENDING"))
    await db.flush()
    return alert


async def dispatch_pending(db: AsyncSession, limit: int = 200) -> dict:
    """Send PENDING deliveries. Called right after alert creation in jobs and by the scheduler every minute."""
    rows = (await db.execute(
        select(NotificationDelivery, Alert, User)
        .join(Alert, Alert.id == NotificationDelivery.alert_id)
        .join(User, User.id == Alert.user_id)
        .where(NotificationDelivery.status == "PENDING", NotificationDelivery.attempts < 3)
        .order_by(NotificationDelivery.id)
        .limit(limit)
    )).all()
    stats = {"sent": 0, "failed": 0}
    for d, a, u in rows:
        t0 = datetime.now(UTC)
        d.attempts += 1
        try:
            if d.channel == "telegram":
                ok = await send_telegram(u.telegram_chat_id, _telegram_text(a))
            elif d.channel == "email":
                ok = await asyncio.to_thread(send_email, u.email, a.title, (a.body or a.title) + ("\n\n" + settings.public_web_url + (a.deeplink or "") if a.deeplink else ""))
            elif d.channel == "push":
                tokens = [t for (t,) in (await db.execute(select(UserDevice.push_token).where(UserDevice.user_id == u.id, UserDevice.push_token.isnot(None)))).all()]
                ok = await send_push(tokens, a.title, a.body or "", a.deeplink)
            else:
                ok = True
            d.status = "SENT" if ok else ("SKIPPED" if ok is None else "FAILED")
            d.error = None if ok else (d.error or "not configured")
            if ok:
                stats["sent"] += 1
            elif ok is False:
                stats["failed"] += 1
        except Exception as e:  # noqa: BLE001
            d.status = "FAILED" if d.attempts >= 3 else "PENDING"
            d.error = str(e)[:255]
            stats["failed"] += 1
        d.latency_ms = int((datetime.now(UTC) - a.created_at.replace(tzinfo=UTC) if a.created_at.tzinfo is None else datetime.now(UTC) - a.created_at).total_seconds() * 1000)
        d.sent_at = datetime.now(UTC)
        _ = t0
    await db.flush()
    return stats


def _telegram_text(a: Alert) -> str:
    icon = {"URGENT": "🚨", "HIGH": "📈", "INFO": "ℹ️"}.get(a.priority, "")
    text = f"{icon} <b>{_esc(a.title)}</b>"
    if a.body:
        text += "\n" + _esc(a.body)
    if a.deeplink:
        text += f"\n<a href=\"{settings.public_web_url}{a.deeplink}\">Mở trong Vinatrade</a>"
    return text


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def send_telegram(chat_id: str | None, html: str) -> bool | None:
    if not settings.telegram_bot_token:
        return None
    if not chat_id:
        return None
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                         json={"chat_id": chat_id, "text": html, "parse_mode": "HTML", "disable_web_page_preview": True})
        if r.status_code != 200:
            log.warning("telegram send failed: %s", r.text[:200])
            return False
    return True


def send_email(to: str, subject: str, body: str) -> bool | None:
    if not settings.smtp_host:
        log.info("[email not configured] to=%s subject=%s", to, subject)
        return None
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, to, subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as s:
        s.starttls()
        if settings.smtp_user:
            s.login(settings.smtp_user, settings.smtp_password)
        s.send_message(msg)
    return True


async def send_push(tokens: list[str], title: str, body: str, deeplink: str | None) -> bool | None:
    if not tokens:
        return None
    try:
        from app.services.push import send_fcm  # lazy: firebase-admin optional
    except Exception:  # noqa: BLE001
        return None
    return await asyncio.to_thread(send_fcm, tokens, title, body, deeplink)

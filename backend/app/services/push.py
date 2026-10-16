"""Firebase Cloud Messaging (optional). Needs FIREBASE_CREDENTIALS (path) or GCP_CREDENTIALS_JSON (inline)."""

import json
import logging
import os

from app.core.config import settings

log = logging.getLogger(__name__)
_app = None


def _init():
    global _app
    if _app is not None:
        return _app
    import firebase_admin
    from firebase_admin import credentials

    if settings.gcp_credentials_json:
        cred = credentials.Certificate(json.loads(settings.gcp_credentials_json))
    elif settings.firebase_credentials and os.path.exists(settings.firebase_credentials):
        cred = credentials.Certificate(settings.firebase_credentials)
    else:
        raise RuntimeError("firebase not configured")
    _app = firebase_admin.initialize_app(cred)
    return _app


def send_fcm(tokens: list[str], title: str, body: str, deeplink: str | None) -> bool | None:
    try:
        _init()
    except Exception as e:  # noqa: BLE001
        log.info("push disabled: %s", e)
        return None
    from firebase_admin import messaging

    msg = messaging.MulticastMessage(
        tokens=tokens[:500],
        notification=messaging.Notification(title=title, body=body),
        data={"deeplink": deeplink or ""},
        android=messaging.AndroidConfig(priority="high"),
        apns=messaging.APNSConfig(payload=messaging.APNSPayload(aps=messaging.Aps(sound="default"))),
    )
    resp = messaging.send_each_for_multicast(msg)
    return resp.success_count > 0

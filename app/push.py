"""Web push via pywebpush + VAPID keys, mirroring src/lib/push.ts."""
from __future__ import annotations

import json
import os
from typing import Optional

from .db import all_rows, run

_configured = False


def push_ready() -> bool:
    global _configured
    if _configured:
        return True
    pub = os.environ.get("VAPID_PUBLIC_KEY")
    priv = os.environ.get("VAPID_PRIVATE_KEY")
    if not pub or not priv:
        return False
    _configured = True
    return True


async def send_push(user_id: str, title: str, body: str, url: Optional[str] = None) -> int:
    if not push_ready():
        return 0
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        return 0

    subs = await all_rows("SELECT endpoint, json FROM push_subs WHERE user_id = ?", [user_id])
    sent = 0
    payload = json.dumps({"title": title, "body": body, "url": url})
    vapid_claims = {"sub": os.environ.get("VAPID_SUBJECT", "mailto:planner@example.com")}
    for s in subs:
        try:
            webpush(
                subscription_info=json.loads(s["json"]),
                data=payload,
                vapid_private_key=os.environ["VAPID_PRIVATE_KEY"],
                vapid_claims=dict(vapid_claims),
                ttl=3600,
            )
            sent += 1
        except WebPushException as e:  # noqa: PERF203
            code = getattr(e.response, "status_code", None)
            if code in (404, 410):
                await run("DELETE FROM push_subs WHERE endpoint = ?", [s["endpoint"]])
        except Exception:  # noqa: BLE001
            pass
    return sent

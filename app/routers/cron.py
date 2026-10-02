"""Vercel cron target, mirroring src/app/api/cron/daily/route.ts: refreshes
each user's sync + plan + push notification once a day."""
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from ..db import all_rows
from ..plan_service import build_plan, ensure_fresh_sync
from ..push import send_push
from ..repo import settings_of

router = APIRouter()


@router.get("/api/cron/daily")
async def cron_daily(authorization: str = Header(default="")):
    secret = os.environ.get("CRON_SECRET")
    if secret and authorization != f"Bearer {secret}":
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

    users = await all_rows("SELECT * FROM users")
    results = []
    for user in users:
        try:
            tz = settings_of(user).timezone
            today = datetime.now(ZoneInfo(tz)).date().isoformat()
            await ensure_fresh_sync(user, force=True)
            payload = await build_plan(user["id"], today, force=True)
            await send_push(user["id"], "Today's plan is ready", "Open Day Planner to see today's schedule.")
            results.append({"id": user["id"], "ok": True, "warnings": len(payload["plan"]["warnings"])})
        except Exception as e:  # noqa: BLE001
            results.append({"id": user["id"], "ok": False, "error": str(e)})
    return JSONResponse({"ok": True, "results": results})

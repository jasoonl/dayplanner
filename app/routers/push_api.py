from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..db import run
from ..push import push_ready, send_push
from ..session import current_user_id

router = APIRouter()


@router.get("/push/vapid-public-key")
async def vapid_public_key():
    import os
    return JSONResponse({"key": os.environ.get("VAPID_PUBLIC_KEY"), "ready": push_ready()})


@router.post("/push/subscribe")
async def push_subscribe(request: Request):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    sub = await request.json()
    endpoint = sub.get("endpoint")
    if not endpoint:
        return JSONResponse({"ok": False, "error": "missing endpoint"}, status_code=400)
    await run("INSERT OR REPLACE INTO push_subs (endpoint, user_id, json) VALUES (?, ?, ?)", [endpoint, uid, json.dumps(sub)])
    return JSONResponse({"ok": True})


@router.post("/push/test")
async def push_test(request: Request):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    count = await send_push(uid, "Day Planner", "This is a test notification.")
    return JSONResponse({"ok": True, "sent": count})

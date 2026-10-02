from __future__ import annotations

import secrets

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from ..db import run
from ..integrations.google import auth_url, exchange_code, google_configured, user_info
from ..repo import create_user, get_user
from ..session import clear_session, current_user_id, set_session

router = APIRouter()

_states: set[str] = set()


@router.get("/auth/google")
async def google_login():
    if not google_configured():
        return RedirectResponse("/login?error=not_configured")
    state = secrets.token_urlsafe(16)
    _states.add(state)
    return RedirectResponse(auth_url(state))


@router.get("/auth/google/callback")
async def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error or not code:
        return RedirectResponse("/login?error=denied")
    tokens = await exchange_code(code)
    info = await user_info(tokens["access_token"])
    email = info.get("email")
    from ..db import one_row
    existing = await one_row("SELECT id FROM users WHERE email = ?", [email]) if email else None
    uid = existing["id"] if existing else await create_user(email, info.get("name"))
    import json
    await run("UPDATE users SET google_json = ? WHERE id = ?", [json.dumps(tokens), uid])
    resp = RedirectResponse("/")
    set_session(resp, uid)
    return resp


@router.post("/auth/logout")
@router.get("/auth/logout")
async def logout():
    resp = RedirectResponse("/login")
    clear_session(resp)
    return resp


@router.get("/auth/demo")
async def demo_login():
    """Explicit entry point into the demo user, for the login page's 'Try the demo' link."""
    from ..seed import ensure_demo_user
    uid = await ensure_demo_user()
    resp = RedirectResponse("/")
    set_session(resp, uid)
    return resp

"""JWT session cookie, mirroring src/lib/session.ts."""
from __future__ import annotations

import os
import time
from typing import Optional

import jwt
from fastapi import Request, Response

from .integrations.google import google_configured
from .repo import get_user
from .seed import ensure_demo_user

COOKIE = "dp_session"
_DEV_SECRET = "dev-only-insecure-secret-change-me-0123456789"


def _secret() -> str:
    s = os.environ.get("SESSION_SECRET")
    if not s or len(s) < 32:
        return _DEV_SECRET
    return s


def demo_mode() -> bool:
    return os.environ.get("DEMO_MODE") == "1" or not google_configured()


def set_session(response: Response, user_id: str) -> None:
    now = int(time.time())
    token = jwt.encode({"uid": user_id, "iat": now, "exp": now + 180 * 86400}, _secret(), algorithm="HS256")
    response.set_cookie(
        COOKIE, token, httponly=True, samesite="lax",
        secure=os.environ.get("VERCEL_ENV") == "production", path="/", max_age=180 * 86400,
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


class Unauthorized(Exception):
    pass


async def current_user_id(request: Request) -> Optional[str]:
    token = request.cookies.get(COOKIE)
    if token:
        try:
            payload = jwt.decode(token, _secret(), algorithms=["HS256"])
            uid = payload.get("uid")
            if uid and await get_user(uid):
                return uid
        except Exception:  # noqa: BLE001
            pass
    if demo_mode():
        return await ensure_demo_user()
    return None


async def require_user_id(request: Request) -> str:
    uid = await current_user_id(request)
    if not uid:
        raise Unauthorized("Sign in required")
    return uid

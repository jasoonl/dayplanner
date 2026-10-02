"""Google OAuth + Calendar REST integration via plain httpx (no heavy SDK, to
stay within Vercel's Python function size limits). Mirrors
src/lib/integrations/google.ts: reads/writes a dedicated secondary
"Day Planner" calendar via the calendar.app.created scope."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx

from ..db import run

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CAL = "https://www.googleapis.com/calendar/v3"

GOOGLE_SCOPES = [
    "openid", "email", "profile",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.app.created",
]


class GoogleAuthError(Exception):
    pass


def google_configured() -> bool:
    return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))


def redirect_uri() -> str:
    base = os.environ.get("APP_URL", "http://localhost:8000").rstrip("/")
    return f"{base}/api/auth/google/callback"


def auth_url(state: str) -> str:
    p = {
        "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(p)}"


async def exchange_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(TOKEN_URL, data={
            "code": code,
            "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
            "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
        })
    if resp.status_code >= 400:
        raise RuntimeError(f"Google token exchange failed: {resp.status_code} {resp.text}")
    j = resp.json()
    return {
        "access_token": j["access_token"],
        "refresh_token": j.get("refresh_token"),
        "expires_at": int(time.time() * 1000) + (j["expires_in"] - 60) * 1000,
        "scope": j.get("scope"),
        "id_token": j.get("id_token"),
    }


async def access_token(user: dict) -> str:
    if not user.get("google_json"):
        raise GoogleAuthError("Google not connected")
    t = json.loads(user["google_json"])
    now = int(time.time() * 1000)
    if t["expires_at"] > now + 30_000:
        return t["access_token"]
    if not t.get("refresh_token"):
        raise GoogleAuthError("Google session expired — reconnect")
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(TOKEN_URL, data={
            "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
            "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            "refresh_token": t["refresh_token"],
            "grant_type": "refresh_token",
        })
    if resp.status_code >= 400:
        raise GoogleAuthError(f"Google refresh failed ({resp.status_code}) — reconnect Google in Settings")
    j = resp.json()
    nxt = {**t, "access_token": j["access_token"], "expires_at": now + (j["expires_in"] - 60) * 1000}
    await run("UPDATE users SET google_json = ? WHERE id = ?", [json.dumps(nxt), user["id"]])
    user["google_json"] = json.dumps(nxt)
    return nxt["access_token"]


async def _gfetch(user: dict, path: str, method: str = "GET", body: Optional[dict] = None) -> Optional[dict]:
    token = await access_token(user)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.request(method, f"{CAL}{path}", headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        }, json=body)
    if resp.status_code == 401:
        raise GoogleAuthError("Google rejected the token — reconnect")
    if resp.status_code not in (200, 201, 204, 410) and resp.status_code >= 400:
        raise RuntimeError(f"Google Calendar {resp.status_code}: {resp.text[:300]}")
    if resp.status_code in (204, 410):
        return None
    return resp.json()


async def list_calendars(user: dict) -> list[dict]:
    r = await _gfetch(user, "/users/me/calendarList?minAccessRole=reader&maxResults=100")
    return (r or {}).get("items", [])


async def list_events(user: dict, calendar_id: str, from_ms: int, to_ms: int) -> list[dict]:
    from urllib.parse import quote
    out: list[dict] = []
    page_token = ""
    for _ in range(10):
        p = {
            "timeMin": datetime.fromtimestamp(from_ms / 1000, tz=timezone.utc).isoformat(),
            "timeMax": datetime.fromtimestamp(to_ms / 1000, tz=timezone.utc).isoformat(),
            "singleEvents": "true", "orderBy": "startTime", "maxResults": "250",
        }
        if page_token:
            p["pageToken"] = page_token
        r = await _gfetch(user, f"/calendars/{quote(calendar_id, safe='')}/events?{urlencode(p)}")
        items = (r or {}).get("items", [])
        out.extend(items)
        page_token = (r or {}).get("nextPageToken")
        if not page_token:
            break
    return [
        e for e in out
        if e.get("status") != "cancelled" and e.get("transparency") != "transparent"
        and not any(a.get("self") and a.get("responseStatus") == "declined" for a in e.get("attendees", []))
    ]


async def ensure_planner_calendar(user: dict, tz: str) -> str:
    if user.get("planner_calendar_id"):
        return user["planner_calendar_id"]
    cal = await _gfetch(user, "/calendars", method="POST", body={
        "summary": "Day Planner", "description": "Study blocks, travel and routines planned by Day Planner.", "timeZone": tz,
    })
    cal_id = cal["id"]
    await run("UPDATE users SET planner_calendar_id = ? WHERE id = ?", [cal_id, user["id"]])
    user["planner_calendar_id"] = cal_id
    return cal_id


async def insert_event(user: dict, calendar_id: str, summary: str, start: int, end: int, tz: str,
                        description: Optional[str] = None, color_id: Optional[str] = None) -> str:
    from urllib.parse import quote
    r = await _gfetch(user, f"/calendars/{quote(calendar_id, safe='')}/events", method="POST", body={
        "summary": summary, "description": description, "colorId": color_id,
        "start": {"dateTime": datetime.fromtimestamp(start / 1000, tz=timezone.utc).isoformat(), "timeZone": tz},
        "end": {"dateTime": datetime.fromtimestamp(end / 1000, tz=timezone.utc).isoformat(), "timeZone": tz},
        "reminders": {"useDefault": False, "overrides": []}, "transparency": "opaque",
    })
    return r["id"]


async def delete_event(user: dict, calendar_id: str, event_id: str) -> None:
    from urllib.parse import quote
    try:
        await _gfetch(user, f"/calendars/{quote(calendar_id, safe='')}/events/{quote(event_id, safe='')}", method="DELETE")
    except Exception:  # noqa: BLE001
        pass


async def user_info(access_token_str: str) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get("https://openidconnect.googleapis.com/v1/userinfo",
                                 headers={"Authorization": f"Bearer {access_token_str}"})
    if resp.status_code >= 400:
        raise RuntimeError("Could not read Google profile")
    return resp.json()

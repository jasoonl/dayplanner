from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..integrations.google import google_configured
from ..main import render, templates
from ..plan_service import build_plan, make_briefing
from ..repo import get_user, list_places, list_routines, list_sources, list_tasks_full, settings_of
from ..session import current_user_id, demo_mode
from ..view_helpers import annotate_blocks

router = APIRouter()


async def _today_context(request: Request, user_id: str, date: Optional[str] = None) -> dict:
    user = await get_user(user_id)
    s = settings_of(user)
    tz = s.timezone
    today = datetime.now(ZoneInfo(tz)).date().isoformat()
    date = date or today
    payload = await build_plan(user_id, date)
    plan = payload["plan"]
    import time as _time
    now = int(_time.time() * 1000) if date == today else None
    blocks = annotate_blocks(plan["blocks"], tz, now, payload["doneBlocks"])
    warnings = plan["warnings"][:3]
    more_warnings = max(0, len(plan["warnings"]) - 3)
    briefing = payload["briefing"]
    if not briefing and payload["checkinDone"]:
        briefing = await make_briefing(user_id, date, plan)
    return {
        "request": request, "date": date, "today": today, "is_today": date == today, "tz": tz,
        "plan": plan, "blocks": blocks, "warnings": warnings, "more_warnings": more_warnings,
        "briefing": briefing, "checkin_done": payload["checkinDone"], "energy": payload["energy"],
        "stats": plan["stats"], "all_day": payload["allDay"], "demo": demo_mode(),
        "google_connected": bool(user.get("google_json")), "google_auth_error": payload.get("googleAuthError"),
    }


async def render_today(request: Request, user_id: str, date: Optional[str] = None) -> HTMLResponse:
    ctx = await _today_context(request, user_id, date)
    return render("partials/today_body.html", ctx)


@router.get("/", response_class=HTMLResponse)
async def today_page(request: Request):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    ctx = await _today_context(request, uid)
    ctx["active_nav"] = "today"
    return render("today.html", ctx)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    uid = await current_user_id(request)
    if uid and not demo_mode():
        return RedirectResponse("/")
    return render("login.html", {"request": request, "google_configured": google_configured(), "demo": demo_mode()})


@router.get("/tasks", response_class=HTMLResponse)
async def tasks_page(request: Request):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    user = await get_user(uid)
    tz = settings_of(user).timezone
    tasks = await list_tasks_full(uid)
    from ..view_helpers import fmt_hhmm_ampm
    for t in tasks:
        t["dueFmt"] = None
        if t["due_at"]:
            dt = datetime.fromtimestamp(t["due_at"] / 1000, tz=ZoneInfo(tz))
            t["dueFmt"] = dt.strftime("%a") + ("" if t["due_all_day"] else f" {fmt_hhmm_ampm(t['due_at'], tz)}")
    return render("tasks.html", {"request": request, "tasks": tasks, "active_nav": "tasks"})


@router.get("/week", response_class=HTMLResponse)
async def week_page(request: Request):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    user = await get_user(uid)
    tz = settings_of(user).timezone
    today = datetime.now(ZoneInfo(tz)).date().isoformat()
    payload = await build_plan(uid, today)
    plan = payload["plan"]
    week = []
    for d in plan["week"]:
        dt = datetime.fromisoformat(d["date"]).replace(tzinfo=ZoneInfo(tz))
        cap = max(1, d["capacityMin"])
        pct = min(100, round(100 * d["allocatedMin"] / cap))
        overload = d["allocatedMin"] > d["capacityMin"]
        week.append({**d, "weekday": dt.strftime("%a"), "monthDay": dt.strftime("%-d"), "pct": pct, "overload": overload})
    due_soon_ids = set(plan.get("dueSoon") or [])
    at_risk = plan.get("atRisk") or []
    return render("week.html", {
        "request": request, "week": week, "at_risk": at_risk, "due_soon_count": len(due_soon_ids), "active_nav": "week",
    })


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    user = await get_user(uid)
    s = settings_of(user)
    places = await list_places(uid)
    sources = await list_sources(uid)
    routines = await list_routines(uid)
    from ..ai.gemini import gemini_configured
    from ..push import push_ready
    return render("settings.html", {
        "request": request, "settings": s, "places": places, "sources": sources, "routines": routines,
        "active_nav": "settings", "google_connected": bool(user.get("google_json")),
        "google_configured": google_configured(), "gemini_configured": gemini_configured(),
        "push_ready": push_ready(), "demo": demo_mode(),
    })

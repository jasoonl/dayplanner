from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..ai.gemini import parse_checkin
from ..ai.rules import parse_free_text
from ..db import bump_version
from ..main import render, templates
from ..plan_service import build_plan, make_briefing, publish_plan
from ..repo import get_day_state, get_user, list_events, list_routines, list_tasks, patch_day_state, settings_of
from ..session import current_user_id
from ..tasks_service import create_task
from .pages import render_today

router = APIRouter()


@router.get("/checkin", response_class=HTMLResponse)
async def checkin_sheet(request: Request):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    user = await get_user(uid)
    s = settings_of(user)
    tz = s.timezone
    today = datetime.now(ZoneInfo(tz)).date().isoformat()
    day = datetime.now(ZoneInfo(tz))
    horizon = int((day + timedelta(days=3)).replace(hour=23, minute=59, second=59).timestamp() * 1000)
    tasks = [t for t in await list_tasks(uid) if t.dueAt and t.dueAt <= horizon]
    state = await get_day_state(uid, today)
    return render("checkin.html", {
        "request": request, "date": today, "tasks": tasks, "state": state, "active_nav": "today",
    })


@router.post("/checkin/parse", response_class=HTMLResponse)
async def checkin_parse(request: Request, text: str = Form("")):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    user = await get_user(uid)
    tz = settings_of(user).timezone
    today = datetime.now(ZoneInfo(tz)).date().isoformat()
    if not text.strip():
        return render("partials/checkin_drafts.html", {"request": request, "drafts": []})
    ai_result = await parse_checkin(text, today, tz)
    if ai_result is not None:
        drafts = ai_result
    else:
        drafts = [d.__dict__ for d in parse_free_text(text, today, tz)]
    return render("partials/checkin_drafts.html", {"request": request, "drafts": drafts})


@router.post("/checkin", response_class=HTMLResponse)
async def checkin_submit(
    request: Request,
    date: str = Form(...),
    energy: str = Form("ok"),
    skipped: list[str] = Form(default=[]),
    draft_title: list[str] = Form(default=[]),
    draft_minutes: list[int] = Form(default=[]),
    draft_priority: list[int] = Form(default=[]),
    draft_where: list[str] = Form(default=[]),
    draft_category: list[str] = Form(default=[]),
    draft_due: list[str] = Form(default=[]),
):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    user = await get_user(uid)
    s = settings_of(user)

    for i, title in enumerate(draft_title):
        if not title.strip():
            continue
        await create_task(uid, {
            "title": title, "minutes": draft_minutes[i] if i < len(draft_minutes) else 30,
            "priority": draft_priority[i] if i < len(draft_priority) else 2,
            "where": draft_where[i] if i < len(draft_where) else "anywhere",
            "category": draft_category[i] if i < len(draft_category) else "personal",
            "due": (draft_due[i] or None) if i < len(draft_due) else None,
            "splittable": True,
        }, s.timezone)

    await patch_day_state(uid, date, {"checkin_done": 1, "energy": energy, "skipped_json": __import__("json").dumps(skipped)})
    await bump_version(uid)
    payload = await build_plan(uid, date, force=True)
    await make_briefing(uid, date, payload["plan"])
    if s.autoPublish and user.get("google_json"):
        await publish_plan(uid, date, payload["plan"])
    return await render_today(request, uid, date)


@router.post("/plan/build", response_class=HTMLResponse)
async def plan_build(request: Request, date: str = Form(None)):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    user = await get_user(uid)
    tz = settings_of(user).timezone
    date = date or datetime.now(ZoneInfo(tz)).date().isoformat()
    payload = await build_plan(uid, date, force=True)
    if settings_of(user).autoPublish and user.get("google_json"):
        await publish_plan(uid, date, payload["plan"])
    return await render_today(request, uid, date)

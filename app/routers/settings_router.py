from __future__ import annotations

import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..db import bump_version, new_id, run
from ..main import render, templates
from ..repo import AppSettings, get_user, list_places, save_settings, settings_of
from ..session import current_user_id
from ..sync import rematch_places

router = APIRouter()


@router.post("/settings", response_class=HTMLResponse)
async def settings_save(
    request: Request, timezone: str = Form(...), checkinTime: str = Form("07:00"),
    focusMin: int = Form(50), breakMin: int = Form(10), morningRoutineMin: int = Form(40),
    windDownMin: int = Form(30), maxWorkMinPerDay: int = Form(300), lookaheadDays: int = Form(7),
    travelMode: str = Form("TRANSIT"), defaultTravelMin: int = Form(30), autoPublish: bool = Form(False),
):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    user = await get_user(uid)
    s = settings_of(user)
    s.timezone = timezone
    s.checkinTime = checkinTime
    s.focusMin = focusMin
    s.breakMin = breakMin
    s.morningRoutineMin = morningRoutineMin
    s.windDownMin = windDownMin
    s.maxWorkMinPerDay = maxWorkMinPerDay
    s.lookaheadDays = lookaheadDays
    s.travelMode = travelMode
    s.defaultTravelMin = defaultTravelMin
    s.autoPublish = autoPublish
    s.onboarded = True
    await save_settings(uid, s)
    return render("partials/toast.html", {"request": request, "message": "Settings saved."})


@router.post("/places", response_class=HTMLResponse)
async def places_create(request: Request, name: str = Form(...), address: str = Form(...), isHome: bool = Form(False), aliases: str = Form("")):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    alias_list = [a.strip() for a in aliases.split(",") if a.strip()]
    if isHome:
        await run("UPDATE places SET is_home = 0 WHERE user_id = ?", [uid])
    await run(
        "INSERT INTO places (id, user_id, name, address, aliases_json, is_home) VALUES (?,?,?,?,?,?)",
        [new_id("p_"), uid, name, address, json.dumps(alias_list), 1 if isHome else 0],
    )
    await rematch_places(uid)
    places = await list_places(uid)
    return render("partials/places_list.html", {"request": request, "places": places})


@router.post("/places/{place_id}/delete", response_class=HTMLResponse)
async def places_delete(request: Request, place_id: str):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    await run("DELETE FROM places WHERE id = ? AND user_id = ?", [place_id, uid])
    await bump_version(uid)
    places = await list_places(uid)
    return render("partials/places_list.html", {"request": request, "places": places})


@router.post("/routines", response_class=HTMLResponse)
async def routines_create(
    request: Request, title: str = Form(...), minutes: int = Form(30), days: list[int] = Form(...),
    where: str = Form("home"), category: str = Form("routine"), priority: int = Form(3),
    windowStart: str = Form(None), windowEnd: str = Form(None),
):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    await run(
        "INSERT INTO routines (id, user_id, title, minutes, days_json, where_, category, priority, window_start, window_end, active) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,1)",
        [new_id("r_"), uid, title, minutes, json.dumps(days), where, category, priority, windowStart or None, windowEnd or None],
    )
    await bump_version(uid)
    from ..repo import list_routines
    routines = await list_routines(uid)
    return render("partials/routines_list.html", {"request": request, "routines": routines})


@router.post("/routines/{routine_id}/delete", response_class=HTMLResponse)
async def routines_delete(request: Request, routine_id: str):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    await run("DELETE FROM routines WHERE id = ? AND user_id = ?", [routine_id, uid])
    await bump_version(uid)
    from ..repo import list_routines
    routines = await list_routines(uid)
    return render("partials/routines_list.html", {"request": request, "routines": routines})

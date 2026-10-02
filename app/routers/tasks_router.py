from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..db import run
from ..main import render, templates
from ..repo import get_user, list_tasks_full, settings_of
from ..session import current_user_id
from ..tasks_service import create_task, patch_task
from ..view_helpers import fmt_hhmm_ampm

router = APIRouter()


async def _render_task_list(request: Request, uid: str) -> HTMLResponse:
    user = await get_user(uid)
    tz = settings_of(user).timezone
    tasks = await list_tasks_full(uid)
    for t in tasks:
        t["dueFmt"] = None
        if t["due_at"]:
            dt = datetime.fromtimestamp(t["due_at"] / 1000, tz=ZoneInfo(tz))
            t["dueFmt"] = dt.strftime("%a") + ("" if t["due_all_day"] else f" {fmt_hhmm_ampm(t['due_at'], tz)}")
    return render("partials/task_list.html", {"request": request, "tasks": tasks})


@router.post("/tasks", response_class=HTMLResponse)
async def tasks_create(
    request: Request, title: str = Form(...), minutes: int = Form(30), priority: int = Form(2),
    where: str = Form("anywhere"), category: str = Form("personal"), due: str = Form(None),
    dueTime: str = Form(None), splittable: bool = Form(True),
):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    user = await get_user(uid)
    tz = settings_of(user).timezone
    await create_task(uid, {
        "title": title, "minutes": minutes, "priority": priority, "where": where, "category": category,
        "due": due or None, "dueTime": dueTime or None, "splittable": splittable,
    }, tz)
    return await _render_task_list(request, uid)


@router.post("/tasks/{task_id}", response_class=HTMLResponse)
async def tasks_patch(
    request: Request, task_id: str, title: str = Form(None), estimateMin: int = Form(None),
    spentMin: int = Form(None), priority: int = Form(None), where: str = Form(None),
    category: str = Form(None), splittable: bool = Form(None), done: bool = Form(None),
    due: str = Form(None), notes: str = Form(None),
):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    user = await get_user(uid)
    tz = settings_of(user).timezone
    patch = {}
    for k, v in {
        "title": title, "estimateMin": estimateMin, "spentMin": spentMin, "priority": priority,
        "where": where, "category": category, "splittable": splittable, "done": done, "due": due, "notes": notes,
    }.items():
        if v is not None:
            patch[k] = v
    await patch_task(uid, task_id, patch, tz)
    return await _render_task_list(request, uid)


@router.post("/tasks/{task_id}/delete", response_class=HTMLResponse)
async def tasks_delete(request: Request, task_id: str):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    await run("DELETE FROM tasks WHERE id = ? AND user_id = ?", [task_id, uid])
    return await _render_task_list(request, uid)

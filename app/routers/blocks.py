from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..db import bump_version, new_id, now_ms, one_row, run
from ..repo import get_day_state, get_user, patch_day_state, settings_of
from ..session import current_user_id
from ..tasks_service import patch_task
from .pages import render_today

router = APIRouter()


@router.post("/blocks/complete", response_class=HTMLResponse)
async def block_complete(
    request: Request, date: str = Form(...), blockId: str = Form(...),
    taskId: str = Form(None), routineId: str = Form(None), minutes: int = Form(0),
    start: int = Form(...), finished: bool = Form(False),
):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    category = None
    if taskId:
        t = await one_row("SELECT category FROM tasks WHERE id = ? AND user_id = ?", [taskId, uid])
        if t:
            category = t["category"]
            now = now_ms()
            await run(
                "UPDATE tasks SET spent_min = spent_min + ?, done = CASE WHEN ? THEN 1 ELSE done END, "
                "done_at = CASE WHEN ? THEN ? ELSE done_at END, updated_at = ? WHERE id = ? AND user_id = ?",
                [minutes, 1 if finished else 0, 1 if finished else 0, now, now, taskId, uid],
            )
    if minutes > 0:
        await run(
            "INSERT INTO work_log (id, user_id, task_id, routine_id, category, start, minutes) VALUES (?,?,?,?,?,?,?)",
            [new_id("w_"), uid, taskId, routineId, category or "routine", start, minutes],
        )
    st = await get_day_state(uid, date)
    done = list(dict.fromkeys([*st.doneBlocks, blockId, *([f"routine:{routineId}"] if routineId else [])]))
    skipped = list(dict.fromkeys([*st.skipped, routineId])) if routineId else st.skipped
    await patch_day_state(uid, date, {"done_blocks_json": json.dumps(done), "skipped_json": json.dumps(skipped)})
    await bump_version(uid)
    return await render_today(request, uid, date)


@router.post("/blocks/skip", response_class=HTMLResponse)
async def block_skip(
    request: Request, date: str = Form(...), taskId: str = Form(None),
    routineId: str = Form(None), eventId: str = Form(None),
):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    user = await get_user(uid)
    tz = settings_of(user).timezone
    if taskId:
        y, m, d = (int(x) for x in date.split("-"))
        nxt = (datetime(y, m, d) + timedelta(days=1)).date().isoformat()
        await patch_task(uid, taskId, {"notBefore": nxt}, tz)
    id_ = routineId or eventId
    if id_:
        st = await get_day_state(uid, date)
        skipped = list(dict.fromkeys([*st.skipped, id_]))
        await patch_day_state(uid, date, {"skipped_json": json.dumps(skipped)})
        await bump_version(uid)
    return await render_today(request, uid, date)

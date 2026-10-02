"""Task create/patch logic, mirroring src/lib/tasks.ts."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from .db import bump_version, new_id, now_ms, one_row, run


def due_from(due: Optional[str], due_time: Optional[str], category: str, tz: str) -> tuple[Optional[int], int]:
    if not due:
        return None, 0
    if due_time:
        y, m, d = (int(x) for x in due.split("-"))
        h, mi = (int(x) for x in due_time.split(":"))
        dt = datetime(y, m, d, h, mi, tzinfo=ZoneInfo(tz))
        return int(dt.timestamp() * 1000), 0
    if category == "school":
        y, m, d = (int(x) for x in due.split("-"))
        dt = datetime(y, m, d, tzinfo=ZoneInfo(tz))
        return int(dt.timestamp() * 1000), 1
    y, m, d = (int(x) for x in due.split("-"))
    dt = datetime(y, m, d, 23, 0, tzinfo=ZoneInfo(tz))
    return int(dt.timestamp() * 1000), 0


async def create_task(user_id: str, t: dict, tz: str) -> str:
    today = datetime.now(ZoneInfo(tz)).date().isoformat()
    due = today if (t.get("priority") == 4 and not t.get("due")) else t.get("due")
    due_time = "23:00" if (t.get("priority") == 4 and not t.get("due")) else t.get("dueTime")
    due_at, all_day = due_from(due, due_time, t["category"], tz)
    id_ = new_id("t_")
    now = now_ms()
    await run(
        "INSERT INTO tasks (id, user_id, title, category, due_at, due_all_day, estimate_min, estimate_source, "
        "priority, where_, splittable, notes, created_at, updated_at) VALUES (?,?,?,?,?,?,?,'user',?,?,?,?,?,?)",
        [id_, user_id, t["title"], t["category"], due_at, all_day, t["minutes"], t["priority"], t["where"],
         1 if t.get("splittable", True) else 0, t.get("notes"), now, now],
    )
    await bump_version(user_id)
    return id_


async def patch_task(user_id: str, id_: str, p: dict, tz: str) -> None:
    cur = await one_row("SELECT category, due_at, done FROM tasks WHERE id = ? AND user_id = ?", [id_, user_id])
    if not cur:
        raise ValueError("Task not found")
    sets: list[str] = []
    args: list = []

    def set_(col: str, v) -> None:
        sets.append(f"{col} = ?")
        args.append(v)

    if "title" in p:
        set_("title", p["title"])
    if "estimateMin" in p:
        set_("estimate_min", p["estimateMin"])
        set_("estimate_source", "user")
    if "spentMin" in p:
        set_("spent_min", p["spentMin"])
    if "priority" in p:
        set_("priority", p["priority"])
    if "where" in p:
        set_("where_", p["where"])
    if "category" in p:
        set_("category", p["category"])
    if "splittable" in p:
        set_("splittable", 1 if p["splittable"] else 0)
    if "notes" in p:
        set_("notes", p["notes"])
    if "done" in p:
        set_("done", 1 if p["done"] else 0)
        set_("done_at", now_ms() if p["done"] else None)
    if "due" in p:
        due_at, all_day = due_from(p["due"], p.get("dueTime"), p.get("category", cur["category"]), tz)
        set_("due_at", due_at)
        set_("due_all_day", all_day)
    if "notBefore" in p:
        nb = p["notBefore"]
        if nb:
            y, m, d = (int(x) for x in nb.split("-"))
            dt = datetime(y, m, d, tzinfo=ZoneInfo(tz))
            set_("not_before", int(dt.timestamp() * 1000))
        else:
            set_("not_before", None)
    if not sets:
        return
    set_("updated_at", now_ms())
    await run(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ? AND user_id = ?", args + [id_, user_id])
    await bump_version(user_id)

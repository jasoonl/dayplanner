"""Pull events/assignments from ICS feeds, Google Calendar and Canvas into the
local DB. Faithful port of src/lib/sync.ts (place-matching regex logic
included verbatim)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from .ai.rules import rule_estimate
from .db import all_rows, batch, bump_version, new_id, now_ms, run
from .integrations import ics as ics_mod
from .integrations.canvas import fetch_canvas_planner
from .integrations.google import GoogleAuthError, list_events as g_list_events
from .planner.types import Place
from .repo import list_places, list_sources, settings_of

_ONLINE_LOC_RE = re.compile(r"zoom\.us|meet\.google|teams\.microsoft|^https?://|\b(zoom|online|virtual|remote|facetime)\b", re.I)
_ONLINE_TITLE_RE = re.compile(r"\b(zoom|online|virtual|facetime|call)\b", re.I)
_ADDR_RE = re.compile(r"\d+\s+\w+")


def match_place(title: str, location: Optional[str], places: list[Place], fallback: Optional[str]) -> Optional[str]:
    loc = (location or "").lower()
    t = title.lower()

    def keys(p: Place) -> list[str]:
        return [a.lower().strip() for a in [p.name, *p.aliases] if len(a.strip()) >= 3]

    if loc:
        if _ONLINE_LOC_RE.search(loc):
            return None
        for p in places:
            if any(k in loc for k in keys(p)) or (p.address and p.address.lower() in loc):
                return p.id
    if _ONLINE_TITLE_RE.search(t):
        return None
    for p in places:
        if p.isHome:
            continue
        for k in keys(p):
            if re.search(rf"\b{re.escape(k)}\b", t):
                return p.id
    if location and _ADDR_RE.search(location) and len(location) > 6:
        return f"addr:{location.strip()}"
    return fallback


async def estimate_ratios(user_id: str) -> dict[str, dict]:
    rows = await all_rows(
        "SELECT category, SUM(estimate_min) est, SUM(spent_min) spent, COUNT(*) n FROM ("
        " SELECT category, estimate_min, spent_min FROM tasks"
        " WHERE user_id = ? AND done = 1 AND spent_min > 0 AND estimate_source != 'user'"
        " ORDER BY done_at DESC LIMIT 200) GROUP BY category",
        [user_id],
    )
    out: dict[str, dict] = {}
    for r in rows:
        if r["n"] >= 3 and r["est"] > 0:
            out[r["category"]] = {"ratio": min(1.8, max(0.6, r["spent"] / r["est"])), "n": r["n"]}
    return out


@dataclass
class _NewTask:
    source: dict
    uid: str
    title: str
    course: Optional[str]
    dueAt: Optional[int]
    dueAllDay: bool
    url: Optional[str]
    done: bool


async def _upsert_assignments(user: dict, items: list[_NewTask], seen_by_source: dict[str, set[str]], window_from: int) -> int:
    tz = settings_of(user).timezone
    start_today = int(datetime.now(ZoneInfo(tz)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    existing = await all_rows(
        "SELECT id, source_id, external_uid, done, spent_min, due_at, estimate_source FROM tasks "
        "WHERE user_id = ? AND source_id IS NOT NULL", [user["id"]],
    )
    by_key = {f"{e['source_id']}|{e['external_uid']}": e for e in existing}
    fresh = [i for i in items if f"{i.source.get('id')}|{i.uid}" not in by_key]
    ratios = await estimate_ratios(user["id"])
    now = now_ms()
    stmts: list[tuple[str, list]] = []

    for f in fresh:
        g = rule_estimate(f.title, f.source["category"])
        r = ratios.get(f.source["category"], {}).get("ratio", 1)
        est = max(10, round((g.minutes * r) / 5) * 5)
        past_due = f.dueAt is not None and f.dueAt < start_today
        stmts.append((
            "INSERT INTO tasks (id, user_id, source_id, external_uid, title, course, category, source_label, due_at, due_all_day, "
            "estimate_min, estimate_source, priority, where_, splittable, done, done_at, url, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [new_id("t_"), user["id"], f.source["id"], f.uid, f.title, f.course, f.source["category"], f.source["label"],
             f.dueAt, 1 if f.dueAllDay else 0, est, "rule", g.priority, g.where, 1 if g.splittable else 0,
             1 if (f.done or past_due) else 0, now if (f.done or past_due) else None, f.url, now, now],
        ))

    for f in items:
        e = by_key.get(f"{f.source.get('id')}|{f.uid}")
        if not e:
            continue
        stmts.append((
            "UPDATE tasks SET title = ?, course = ?, due_at = ?, due_all_day = ?, url = COALESCE(?, url), updated_at = ? WHERE id = ?",
            [f.title, f.course, f.dueAt, 1 if f.dueAllDay else 0, f.url, now, e["id"]],
        ))
        if f.done and not e["done"]:
            stmts.append(("UPDATE tasks SET done = 1, done_at = ? WHERE id = ?", [now, e["id"]]))

    for e in existing:
        seen = seen_by_source.get(e["source_id"])
        if seen is None or e["external_uid"] in seen:
            continue
        if not e["done"] and e["spent_min"] == 0 and (e["due_at"] or 0) >= window_from:
            stmts.append(("DELETE FROM tasks WHERE id = ?", [e["id"]]))

    await batch(stmts)
    return len(fresh)


async def sync_user(user: dict) -> dict:
    settings = settings_of(user)
    tz = settings.timezone
    start_today = datetime.now(ZoneInfo(tz)).replace(hour=0, minute=0, second=0, microsecond=0)
    day_ms = 86_400_000
    ev_from = int(start_today.timestamp() * 1000) - day_ms
    ev_to = int(start_today.timestamp() * 1000) + 15 * day_ms
    task_from = int(start_today.timestamp() * 1000) - 14 * day_ms
    task_to = int(start_today.timestamp() * 1000) + 120 * day_ms

    places = await list_places(user["id"])
    sources = [s for s in await list_sources(user["id"]) if s["enabled"]]
    report: dict = {"ok": True, "sources": [], "newTasks": 0}
    assignments: list[_NewTask] = []
    seen_by_source: dict[str, set[str]] = {}

    for src in sources:
        if src["kind"] not in ("ics", "google", "canvas_api"):
            continue
        if src["kind"] == "google" and not user.get("google_json"):
            continue
        events: list[dict] = []
        try:
            if src["kind"] == "ics" and src["url"]:
                text = ics_mod.fetch_ics_sync(src["url"])
                items = ics_mod.parse_ics(text, from_ms=task_from, to_ms=task_to, tz=tz, role=src["role"])
                seen: set[str] = set()
                for it in items:
                    if it.kind == "assignment":
                        split = ics_mod.split_course(it.title)
                        seen.add(it.uid)
                        assignments.append(_NewTask(source=src, uid=it.uid, title=split["title"], course=split.get("course"),
                                                     dueAt=it.start, dueAllDay=it.allDay, url=it.url, done=False))
                    elif it.end > ev_from and it.start < ev_to:
                        events.append({"uid": it.uid, "title": it.title, "start": it.start, "end": it.end,
                                       "allDay": it.allDay or it.kind == "info", "location": it.location})
                seen_by_source[src["id"]] = seen
            elif src["kind"] == "google":
                meta = json.loads(src.get("meta_json") or "{}")
                cal_ids = [c for c in (meta.get("calendarIds") or ["primary"]) if c != user.get("planner_calendar_id")]
                for cal_id in cal_ids:
                    for e in await g_list_events(user, cal_id, ev_from, ev_to):
                        all_day = bool(e["start"].get("date"))
                        if all_day:
                            y, m, d = (int(x) for x in e["start"]["date"].split("-"))
                            start = int(datetime(y, m, d, tzinfo=ZoneInfo(tz)).timestamp() * 1000)
                            y2, m2, d2 = (int(x) for x in e["end"]["date"].split("-"))
                            end = int(datetime(y2, m2, d2, tzinfo=ZoneInfo(tz)).timestamp() * 1000)
                        else:
                            start = int(datetime.fromisoformat(e["start"]["dateTime"].replace("Z", "+00:00")).timestamp() * 1000)
                            end = int(datetime.fromisoformat(e["end"]["dateTime"].replace("Z", "+00:00")).timestamp() * 1000)
                        events.append({"uid": f"{cal_id}:{e['id']}", "title": e.get("summary", "(busy)"), "start": start,
                                       "end": end, "allDay": all_day, "location": e.get("location")})
            elif src["kind"] == "canvas_api" and src["url"] and src["token"]:
                items = await fetch_canvas_planner(src["url"], src["token"], task_from, task_to)
                seen = set()
                for it in items:
                    seen.add(it.uid)
                    assignments.append(_NewTask(source=src, uid=it.uid, title=it.title, course=it.course,
                                                 dueAt=it.dueAt, dueAllDay=False, url=it.url, done=it.submitted))
                seen_by_source[src["id"]] = seen

            stmts: list[tuple[str, list]] = [("DELETE FROM events WHERE user_id = ? AND source_id = ?", [user["id"], src["id"]])]
            for e in events:
                place_id = None if e["allDay"] else match_place(e["title"], e.get("location"), places, src["default_place_id"])
                stmts.append((
                    "INSERT OR REPLACE INTO events (id, user_id, source_id, title, start, end, all_day, location, place_id) VALUES (?,?,?,?,?,?,?,?,?)",
                    [f"{src['id']}:{e['uid']}:{e['start']}", user["id"], src["id"], e["title"], e["start"], e["end"],
                     1 if e["allDay"] else 0, e.get("location"), place_id],
                ))
            if src["kind"] != "canvas_api":
                await batch(stmts)
            count = len(events) + len(seen_by_source.get(src["id"], set()))
            await run("UPDATE sources SET last_sync_at = ?, last_error = NULL, item_count = ? WHERE id = ?", [now_ms(), count, src["id"]])
            report["sources"].append({"id": src["id"], "label": src["label"], "ok": True, "count": count})
        except GoogleAuthError as e:
            report["googleAuthError"] = str(e)
            report["ok"] = False
            await run("UPDATE sources SET last_error = ?, last_sync_at = ? WHERE id = ?", [str(e)[:300], now_ms(), src["id"]])
            report["sources"].append({"id": src["id"], "label": src["label"], "ok": False, "count": 0, "error": str(e)})
        except Exception as e:  # noqa: BLE001
            report["ok"] = False
            await run("UPDATE sources SET last_error = ?, last_sync_at = ? WHERE id = ?", [str(e)[:300], now_ms(), src["id"]])
            report["sources"].append({"id": src["id"], "label": src["label"], "ok": False, "count": 0, "error": str(e)})

    report["newTasks"] = await _upsert_assignments(user, assignments, seen_by_source, task_from)
    await run("UPDATE users SET last_sync_at = ? WHERE id = ?", [now_ms(), user["id"]])
    await bump_version(user["id"])
    return report


async def rematch_places(user_id: str) -> None:
    places = await list_places(user_id)
    sources = await list_sources(user_id)
    evs = await all_rows("SELECT id, title, location, source_id, all_day FROM events WHERE user_id = ?", [user_id])
    stmts: list[tuple[str, list]] = []
    for e in evs:
        if e["all_day"]:
            continue
        src = next((s for s in sources if s["id"] == e["source_id"]), None)
        fallback = src["default_place_id"] if src else None
        stmts.append(("UPDATE events SET place_id = ? WHERE id = ?", [match_place(e["title"], e["location"], places, fallback), e["id"]]))
    await batch(stmts)
    await bump_version(user_id)

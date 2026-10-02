"""Build/cache the day plan, generate briefings, publish to Google Calendar.
Faithful port of src/lib/plan-service.ts."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from .ai.gemini import briefing as ai_briefing
from .integrations.google import GoogleAuthError, delete_event, ensure_planner_calendar, insert_event
from .integrations.routes import LegRequest, build_travel_lookup
from .planner.index import plan_day
from .planner.time import add_days, fmt_time, start_of_day
from .planner.types import DayOverrides, PlanInput
from .repo import get_day_state, get_user, list_events, list_places, list_routines, list_tasks, patch_day_state, settings_of
from .sync import sync_user

STALE_SYNC_MS = 20 * 60_000


def _legs_for(events, places, tz: str) -> list[LegRequest]:
    home = next((p.id for p in places if p.isHome), None)
    if not home:
        return []
    by_day: dict[str, list] = {}
    for e in events:
        if e.allDay or not e.placeId:
            continue
        d = datetime.fromtimestamp(e.start / 1000, tz=ZoneInfo(tz)).date().isoformat()
        by_day.setdefault(d, []).append(e)
    legs: list[LegRequest] = []
    for lst in by_day.values():
        lst.sort(key=lambda e: e.start)
        prev = home
        for e in lst:
            to = e.placeId
            if to != prev:
                legs.append(LegRequest(prev, to, e.start))
                if prev != home and to != home:
                    legs.append(LegRequest(prev, home, e.start))
                    legs.append(LegRequest(home, to, e.start))
            prev = to
        if prev != home:
            legs.append(LegRequest(prev, home, lst[-1].end + 3_600_000))
    legs.sort(key=lambda l: l.arriveBy)
    return legs


def plan_result_to_dict(plan) -> dict:
    d = asdict(plan)
    return d


async def ensure_fresh_sync(user: dict, force: bool = False) -> Optional[dict]:
    import time as _time
    now = int(_time.time() * 1000)
    if not force and user.get("last_sync_at") and now - user["last_sync_at"] < STALE_SYNC_MS:
        return None
    return await sync_user(user)


async def build_plan(user_id: str, date: str, force: bool = False) -> dict:
    user = await get_user(user_id)
    s = settings_of(user)
    tz = s.timezone
    today = datetime.now(ZoneInfo(tz)).date().isoformat()
    google_auth_error = None

    if date >= today:
        try:
            r = await ensure_fresh_sync(user)
            if r and r.get("googleAuthError"):
                google_auth_error = r["googleAuthError"]
        except Exception:  # noqa: BLE001
            pass
        user = await get_user(user_id)

    state = await get_day_state(user_id, date)
    places = await list_places(user_id)
    from_ms = start_of_day(add_days(date, -1, tz), tz)
    to_ms = start_of_day(add_days(date, s.lookaheadDays + 1, tz), tz)
    events = await list_events(user_id, from_ms, to_ms)

    day_start = start_of_day(date, tz)
    all_day = [
        {"id": e.id, "title": e.title, "sourceLabel": e.sourceLabel}
        for e in events if e.allDay and e.start < day_start + 86_400_000 and e.end > day_start
    ]

    cached = json.loads(state.planJson) if state.planJson else None
    is_today = date == today
    import time as _time
    fresh = (
        cached is not None and state.planVersion == user["data_version"] and not force
        and (not is_today or int(_time.time() * 1000) - cached["generatedAt"] < 30 * 60_000)
    )

    if fresh:
        plan = cached
    else:
        tasks = await list_tasks(user_id)
        routines = await list_routines(user_id)
        legs = _legs_for(events, places, tz)
        lookup = await build_travel_lookup(places, s.travelMode, tz, s.defaultTravelMin, legs)
        now = int(_time.time() * 1000) if is_today else None
        past_blocks = None
        if cached:
            from .planner.types import PlanBlock
            past_blocks = [PlanBlock(**b) for b in cached["blocks"]]
        result = plan_day(PlanInput(
            date=date, now=now, events=events, tasks=tasks, routines=routines, places=places,
            settings=s.as_planner_settings(), travel=lookup,
            overrides=DayOverrides(energy=state.energy, skippedEventIds=state.skipped),
            pastBlocks=past_blocks,
        ))
        plan = plan_result_to_dict(result)
        await patch_day_state(user_id, date, {"plan_json": json.dumps(plan), "plan_version": user["data_version"]})

    return {
        "plan": plan,
        "briefing": state.briefing,
        "checkinDone": state.checkinDone,
        "energy": state.energy,
        "skipped": state.skipped,
        "doneBlocks": state.doneBlocks,
        "published": bool(state.published),
        "allDay": all_day,
        "places": places,
        "lastSyncAt": user.get("last_sync_at"),
        "googleAuthError": google_auth_error,
        "dataVersion": user["data_version"],
    }


def template_briefing(plan: dict, tz: str) -> str:
    first_leave = next((b for b in plan["blocks"] if b["kind"] == "travel"), None)
    top = next((b for b in plan["blocks"] if b["kind"] == "task" and (b.get("priority") or 0) >= 3), None) \
        or next((b for b in plan["blocks"] if b["kind"] == "task"), None)
    parts = []
    if top:
        parts.append(f"Most important: {top['title']} at {fmt_time(top['start'], tz)}.")
    if first_leave:
        parts.append(f"Leave by {fmt_time(first_leave['start'], tz)} for {first_leave['title'].replace('Travel to ', '')}.")
    parts.append(f"{round(plan['stats']['focusMin'] / 6) / 10}h of focused work planned, {round(plan['stats']['travelMin'])} min travelling.")
    risk = next((w for w in plan["warnings"] if w["kind"] in ("atRisk", "late", "didntFit")), None)
    if risk:
        parts.append(risk["message"])
    return " ".join(parts)


async def make_briefing(user_id: str, date: str, plan: dict) -> str:
    user = await get_user(user_id)
    tz = settings_of(user).timezone
    lines = [
        f"{fmt_time(b['start'], tz)}–{fmt_time(b['end'], tz)} {b['kind']}: {b['title']}" + (" (must today)" if b.get("priority") == 4 else "")
        for b in plan["blocks"] if b["kind"] not in ("buffer", "break")
    ]
    warn = [f"WARNING: {w['message']}" for w in plan["warnings"]]
    text = await ai_briefing("\n".join([f"Date: {date}", *lines, *warn]))
    out = text or template_briefing(plan, tz)
    await patch_day_state(user_id, date, {"briefing": out})
    return out


_COLOR = {"task": "9", "routine": "10", "travel": "8", "meal": "5"}


async def publish_plan(user_id: str, date: str, plan: dict) -> dict:
    user = await get_user(user_id)
    if not user.get("google_json"):
        return {"ok": False, "count": 0, "error": "Google not connected"}
    tz = settings_of(user).timezone
    try:
        cal_id = await ensure_planner_calendar(user, tz)
        state = await get_day_state(user_id, date)
        import time as _time
        now = int(_time.time() * 1000)
        published = state.published or {}
        prev_events = published.get("events", [])
        kept = [e for e in prev_events if e["end"] <= now]
        for e in [x for x in prev_events if x["end"] > now]:
            await delete_event(user, published["calendarId"], e["id"])
        blocks = [b for b in plan["blocks"] if b["kind"] in ("task", "routine", "travel") and b["end"] > now]
        ids = []
        for b in blocks:
            summary = f"\U0001f687 {b['title']}" if b["kind"] == "travel" else (f"\U0001f4d6 {b['title']} (on the ride)" if b.get("onTransit") else b["title"])
            desc = "\n".join(x for x in [b.get("subtitle"), b.get("sourceLabel"), "Planned by Day Planner"] if x)
            eid = await insert_event(user, cal_id, summary, b["start"], b["end"], tz, description=desc, color_id=_COLOR.get(b["kind"]))
            ids.append({"id": eid, "end": b["end"]})
        await patch_day_state(user_id, date, {"published_json": json.dumps({"calendarId": cal_id, "events": kept + ids})})
        return {"ok": True, "count": len(ids)}
    except GoogleAuthError as e:
        return {"ok": False, "count": 0, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "count": 0, "error": str(e)}

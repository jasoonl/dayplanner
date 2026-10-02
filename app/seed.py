"""Demo-mode seed data, mirroring src/lib/seed.ts: Dalton 8:10-3:30 weekdays,
fencing Mon/Wed/Fri, violin lesson + SAT tutor Tuesday, MSM + Columbia SHP
Saturday, church Sunday, plus a realistic task/routine list and a pre-seeded
travel cache so the demo works with zero API keys."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .db import batch, new_id, now_ms, one_row, run
from .integrations.routes import bucket_of
from .repo import default_app_settings

DEMO_ID = "u_demo"

PLACES = [
    {"id": "p_home", "name": "Home", "address": "E 86th St & Lexington Ave, New York, NY", "aliases": [], "home": 1},
    {"id": "p_dalton", "name": "Dalton", "address": "108 E 89th St, New York, NY 10128", "aliases": ["dalton", "school"], "home": 0},
    {"id": "p_msm", "name": "Manhattan School of Music", "address": "130 Claremont Ave, New York, NY 10027", "aliases": ["msm", "precollege", "violin lesson"], "home": 0},
    {"id": "p_columbia", "name": "Columbia SHP", "address": "Columbia University, 116th St & Broadway, New York, NY 10027", "aliases": ["shp", "columbia"], "home": 0},
    {"id": "p_mfc", "name": "Manhattan Fencing Center", "address": "Manhattan Fencing Center, New York, NY", "aliases": ["fencing", "mfc"], "home": 0},
    {"id": "p_church", "name": "Church", "address": "Church (set the address in Settings)", "aliases": ["church"], "home": 0},
]

DEMO_TRAVEL = [
    ("p_home", "p_dalton", 15), ("p_home", "p_msm", 40), ("p_home", "p_columbia", 38), ("p_home", "p_mfc", 35),
    ("p_home", "p_church", 15), ("p_dalton", "p_msm", 40), ("p_dalton", "p_mfc", 35), ("p_msm", "p_columbia", 8),
    ("p_msm", "p_mfc", 40), ("p_columbia", "p_mfc", 40), ("p_dalton", "p_columbia", 38),
]


def _tz() -> str:
    return os.environ.get("DEFAULT_TIMEZONE", "America/New_York")


async def ensure_demo_user() -> str:
    tz = _tz()
    today = datetime.now(ZoneInfo(tz)).date().isoformat()
    u = await one_row("SELECT settings_json FROM users WHERE id = ?", [DEMO_ID])
    if u:
        s = json.loads(u["settings_json"])
        seeded_on = s.get("demoSeededOn")
        if seeded_on:
            days_since = (datetime.fromisoformat(today) - datetime.fromisoformat(seeded_on)).days
            if days_since < 2:
                return DEMO_ID
    keep = json.loads(u["settings_json"]) if u else None
    await seed_demo(tz, today, keep)
    return DEMO_ID


async def seed_demo(tz: str, today: str, keep_settings: dict | None) -> None:
    base_settings = default_app_settings(tz).__dict__.copy()
    if keep_settings:
        base_settings.update({k: v for k, v in keep_settings.items() if k in base_settings})
    base_settings["onboarded"] = True
    base_settings["demoSeededOn"] = today
    settings_json = json.dumps({**base_settings, "days": {k: (v if isinstance(v, dict) else v.__dict__) for k, v in base_settings["days"].items()},
                                 "meals": [m if isinstance(m, dict) else m.__dict__ for m in base_settings["meals"]]})

    stmts: list[tuple[str, list]] = []
    for t in ["events", "tasks", "routines", "places", "sources", "day_state", "work_log"]:
        stmts.append((f"DELETE FROM {t} WHERE user_id = ?", [DEMO_ID]))

    now = now_ms()
    stmts.append((
        "INSERT INTO users (id, email, name, settings_json, created_at) VALUES (?, 'demo@local', 'Demo', ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET settings_json = excluded.settings_json, data_version = data_version + 1, last_sync_at = ?",
        [DEMO_ID, settings_json, now, now],
    ))

    for p in PLACES:
        stmts.append((
            "INSERT INTO places (id, user_id, name, address, aliases_json, is_home) VALUES (?,?,?,?,?,?)",
            [p["id"], DEMO_ID, p["name"], p["address"], json.dumps(p["aliases"]), p["home"]],
        ))

    sources = [
        {"id": "s_dalton", "label": "Dalton schedule", "category": "school", "place": "p_dalton"},
        {"id": "s_personal", "label": "My calendar", "category": "personal", "place": None},
        {"id": "s_msm", "label": "MSM Precollege", "category": "music", "place": "p_msm"},
    ]
    for s in sources:
        stmts.append((
            "INSERT INTO sources (id, user_id, kind, label, role, category, default_place_id, last_sync_at, item_count) VALUES (?,?,?,?,?,?,?,?,?)",
            [s["id"], DEMO_ID, "demo", s["label"], "auto", s["category"], s["place"], now, 0],
        ))

    base = datetime.fromisoformat(today).replace(tzinfo=ZoneInfo(tz))

    def ev(d: datetime, title: str, s: str, e: str, place: str | None, src: str, location: str | None = None) -> None:
        sh, sm = (int(x) for x in s.split(":"))
        eh, em = (int(x) for x in e.split(":"))
        start = int(d.replace(hour=sh, minute=sm, second=0, microsecond=0).timestamp() * 1000)
        end = int(d.replace(hour=eh, minute=em, second=0, microsecond=0).timestamp() * 1000)
        stmts.append((
            "INSERT INTO events (id, user_id, source_id, title, start, end, all_day, location, place_id) VALUES (?,?,?,?,?,?,0,?,?)",
            [f"{src}:{title}:{start}", DEMO_ID, src, title, start, end, location, place],
        ))

    for i in range(-1, 22):
        d = base + timedelta(days=i)
        wd = d.isoweekday()
        if wd <= 5:
            ev(d, "School", "08:10", "15:30", "p_dalton", "s_dalton", "Dalton")
        if wd == 1:
            ev(d, "Fencing practice", "19:00", "21:00", "p_mfc", "s_personal", "Manhattan Fencing Center")
        if wd == 2:
            ev(d, "Violin lesson", "16:30", "17:30", "p_msm", "s_msm", "Manhattan School of Music")
            ev(d, "SAT tutor (Zoom)", "19:00", "20:00", None, "s_personal", "https://zoom.us/j/demo")
        if wd == 3:
            ev(d, "Fencing practice", "18:30", "20:30", "p_mfc", "s_personal", "Manhattan Fencing Center")
        if wd == 5:
            ev(d, "Fencing practice", "19:30", "21:30", "p_mfc", "s_personal", "Manhattan Fencing Center")
        if wd == 6:
            ev(d, "MSM Precollege", "09:00", "13:00", "p_msm", "s_msm", "Manhattan School of Music")
            ev(d, "Columbia SHP", "14:00", "16:30", "p_columbia", "s_personal", "Columbia University")
        if wd == 7:
            ev(d, "Church", "09:00", "11:00", "p_church", "s_personal")

    def due(days: int, hhmm: str | None = None) -> dict:
        d = base + timedelta(days=days)
        if not hhmm:
            return {"at": int(d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000), "allDay": 1}
        h, m = (int(x) for x in hhmm.split(":"))
        return {"at": int(d.replace(hour=h, minute=m, second=0, microsecond=0).timestamp() * 1000), "allDay": 0}

    next_sat = ((6 - base.isoweekday() + 7) % 7) or 7
    tasks = [
        {"title": "Unit 2 Test", "course": "AP Biology", "cat": "school", "src": "s_dalton", "due": due(2), "est": 180, "pri": 3, "where": "anywhere"},
        {"title": "Gatsby ch. 5–6 response", "course": "English 11", "cat": "school", "src": "s_dalton", "due": due(1), "est": 50, "pri": 2, "where": "anywhere"},
        {"title": "Problem set 3.4", "course": "Precalculus", "cat": "school", "src": "s_dalton", "due": due(1), "est": 45, "pri": 2, "where": "anywhere"},
        {"title": "DBQ essay draft", "course": "US History", "cat": "school", "src": "s_dalton", "due": due(3), "est": 150, "pri": 3, "where": "anywhere", "spent": 30},
        {"title": "Lab report: enzyme kinetics", "course": "Chemistry", "cat": "school", "src": "s_dalton", "due": due(5), "est": 120, "pri": 2, "where": "anywhere"},
        {"title": "Spanish vocab — Unidad 3", "course": "Spanish IV", "cat": "school", "src": "s_dalton", "due": due(2), "est": 30, "pri": 2, "where": "portable"},
        {"title": "Theory worksheet 4", "course": "MSM Theory", "cat": "music", "src": "s_msm", "due": due(next_sat, "08:00"), "est": 40, "pri": 2, "where": "anywhere"},
        {"title": "Kandel ch. 2 reading", "course": "Columbia SHP", "cat": "activity", "src": None, "due": due(next_sat, "08:00"), "est": 60, "pri": 2, "where": "portable"},
        {"title": "NAC registration + travel form", "course": None, "cat": "activity", "src": None, "due": due(6, "20:00"), "est": 20, "pri": 3, "where": "anywhere", "split": 0},
        {"title": "StudyScribes: fix transcript export", "course": None, "cat": "personal", "src": None, "due": None, "est": 120, "pri": 2, "where": "anywhere"},
        {"title": "Research: stress & device-use survey draft", "course": None, "cat": "personal", "src": None, "due": None, "est": 180, "pri": 3, "where": "anywhere"},
    ]
    for t in tasks:
        stmts.append((
            "INSERT INTO tasks (id, user_id, source_id, external_uid, title, course, category, source_label, due_at, due_all_day, "
            "estimate_min, estimate_source, spent_min, priority, where_, splittable, done, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
            [new_id("t_"), DEMO_ID, t["src"], new_id("x") if t["src"] else None, t["title"], t["course"], t["cat"], t["course"],
             t["due"]["at"] if t["due"] else None, t["due"]["allDay"] if t["due"] else 0, t["est"], "ai" if t["src"] else "user",
             t.get("spent", 0), t["pri"], t["where"], t.get("split", 1), now, now],
        ))

    routines = [
        {"title": "Violin practice (Bruch mvt 3)", "min": 45, "days": [1, 3, 4, 5, 6, 7], "where": "home", "cat": "music", "ws": "15:30", "we": "22:00"},
        {"title": "Fencing conditioning", "min": 30, "days": [2, 4, 6], "where": "home", "cat": "activity", "ws": None, "we": None},
        {"title": "SAT practice section", "min": 30, "days": [1, 3, 4, 7], "where": "anywhere", "cat": "school", "ws": None, "we": None},
    ]
    for r in routines:
        stmts.append((
            "INSERT INTO routines (id, user_id, title, minutes, days_json, where_, category, priority, window_start, window_end, active) VALUES (?,?,?,?,?,?,?,3,?,?,1)",
            [new_id("r_"), DEMO_ID, r["title"], r["min"], json.dumps(r["days"]), r["where"], r["cat"], r["ws"], r["we"]],
        ))

    def addr(pid: str) -> str:
        return next(p for p in PLACES if p["id"] == pid)["address"].lower().strip()

    bands = set()
    for h in range(24):
        for wd in (3, 6):
            dd = base + timedelta(days=(wd - base.isoweekday()))
            bands.add(bucket_of(int(dd.replace(hour=h % 24).timestamp() * 1000), tz))
    for mode in ["TRANSIT"]:
        for a, b, m in DEMO_TRAVEL:
            for band in bands:
                rush = 5 if band.endswith("am") or band.endswith("pm") else 0
                for x, y in ((a, b), (b, a)):
                    stmts.append((
                        "INSERT OR REPLACE INTO travel_cache (key, minutes, fetched_at) VALUES (?, ?, ?)",
                        [f"{mode}|{addr(x)}|{addr(y)}|{band}", m + rush, now + 365 * 86_400_000],
                    ))

    await batch(stmts)
    await run("UPDATE users SET data_version = data_version + 1 WHERE id = ?", [DEMO_ID])

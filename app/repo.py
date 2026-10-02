"""Data access layer mirroring src/lib/repo.ts, adapted to the sync-style
dataclasses used by the Python planner engine."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from .db import all_rows, bump_version, now_ms, one_row, run
from .planner.defaults import default_settings
from .planner.types import DayWindowConfig, FixedEvent, MealConfig, Place, PlannerSettings, Routine, Task

DEFAULT_TZ = "America/New_York"


@dataclass
class AppSettings:
    timezone: str
    days: dict[str, DayWindowConfig]
    morningRoutineMin: int
    windDownMin: int
    focusMin: int
    breakMin: int
    minChunkMin: int
    arriveEarlyMin: int
    goHomeThresholdMin: int
    maxWorkMinPerDay: int
    lookaheadDays: int
    travelMode: str
    meals: list[MealConfig]
    checkinTime: str = "07:00"
    autoPublish: bool = True
    defaultTravelMin: int = 30
    onboarded: bool = False
    demoSeededOn: Optional[str] = None

    def as_planner_settings(self) -> PlannerSettings:
        return PlannerSettings(
            timezone=self.timezone, days=self.days, morningRoutineMin=self.morningRoutineMin,
            windDownMin=self.windDownMin, focusMin=self.focusMin, breakMin=self.breakMin,
            minChunkMin=self.minChunkMin, arriveEarlyMin=self.arriveEarlyMin,
            goHomeThresholdMin=self.goHomeThresholdMin, maxWorkMinPerDay=self.maxWorkMinPerDay,
            lookaheadDays=self.lookaheadDays, travelMode=self.travelMode, meals=self.meals,
        )

    def to_json(self) -> str:
        d = asdict(self)
        d["days"] = {k: {"wake": v["wake"], "bedtime": v["bedtime"]} for k, v in d["days"].items()}
        d["meals"] = [m for m in d["meals"]]
        return json.dumps(d)

    @staticmethod
    def from_dict(d: dict) -> "AppSettings":
        base = asdict(default_app_settings())
        merged = {**base, **d}
        merged["days"] = {**base["days"], **(d.get("days") or {})}
        days = {k: DayWindowConfig(**v) if isinstance(v, dict) else v for k, v in merged["days"].items()}
        meals = [MealConfig(**m) if isinstance(m, dict) else m for m in merged["meals"]]
        merged["days"] = days
        merged["meals"] = meals
        return AppSettings(**merged)


def default_app_settings(tz: str = DEFAULT_TZ) -> AppSettings:
    s = default_settings(tz)
    return AppSettings(
        timezone=s.timezone, days=s.days, morningRoutineMin=s.morningRoutineMin, windDownMin=s.windDownMin,
        focusMin=s.focusMin, breakMin=s.breakMin, minChunkMin=s.minChunkMin, arriveEarlyMin=s.arriveEarlyMin,
        goHomeThresholdMin=s.goHomeThresholdMin, maxWorkMinPerDay=s.maxWorkMinPerDay, lookaheadDays=s.lookaheadDays,
        travelMode=s.travelMode, meals=s.meals, checkinTime="07:00", autoPublish=True, defaultTravelMin=30, onboarded=False,
    )


async def get_user(user_id: str) -> Optional[dict]:
    return await one_row("SELECT * FROM users WHERE id = ?", [user_id])


def settings_of(user_row: dict) -> AppSettings:
    d = default_app_settings()
    try:
        s = json.loads(user_row["settings_json"])
        return AppSettings.from_dict(s)
    except Exception:
        return d


async def save_settings(user_id: str, s: AppSettings) -> None:
    await run("UPDATE users SET settings_json = ? WHERE id = ?", [s.to_json(), user_id])
    await bump_version(user_id)


async def create_user(email: Optional[str], name: Optional[str], id_: Optional[str] = None) -> str:
    from .db import new_id
    uid = id_ or new_id("u_")
    await run(
        "INSERT INTO users (id, email, name, settings_json, created_at) VALUES (?, ?, ?, ?, ?)",
        [uid, email, name, default_app_settings().to_json(), now_ms()],
    )
    return uid


async def list_places(user_id: str) -> list[Place]:
    rows = await all_rows("SELECT * FROM places WHERE user_id = ? ORDER BY is_home DESC, name", [user_id])
    return [Place(id=r["id"], name=r["name"], address=r["address"], aliases=json.loads(r["aliases_json"]), isHome=bool(r["is_home"])) for r in rows]


async def list_sources(user_id: str) -> list[dict]:
    return await all_rows("SELECT * FROM sources WHERE user_id = ? ORDER BY kind, label", [user_id])


def _row_to_task(r: dict) -> Task:
    return Task(
        id=r["id"], title=r["title"], category=r["category"],
        sourceLabel=r["course"] or r["source_label"],
        dueAt=r["due_at"], dueAllDay=bool(r["due_all_day"]), estimateMin=r["estimate_min"],
        spentMin=r["spent_min"], priority=min(4, max(1, r["priority"])), where=r["where_"],
        splittable=bool(r["splittable"]), done=bool(r["done"]), notBefore=r["not_before"],
    )


async def list_tasks(user_id: str, include_done_since: Optional[int] = None) -> list[Task]:
    since = include_done_since if include_done_since is not None else now_ms() + 1
    rows = await all_rows(
        "SELECT * FROM tasks WHERE user_id = ? AND (done = 0 OR done_at >= ?) ORDER BY COALESCE(due_at, 9000000000000000), priority DESC",
        [user_id, since],
    )
    return [_row_to_task(r) for r in rows]


async def list_tasks_full(user_id: str, include_done_since: Optional[int] = None) -> list[dict]:
    """Row dicts for the UI (keeps course/url/notes/etc)."""
    since = include_done_since if include_done_since is not None else now_ms() + 1
    return await all_rows(
        "SELECT * FROM tasks WHERE user_id = ? AND (done = 0 OR done_at >= ?) ORDER BY COALESCE(due_at, 9000000000000000), priority DESC",
        [user_id, since],
    )


async def list_routines(user_id: str) -> list[Routine]:
    rows = await all_rows("SELECT * FROM routines WHERE user_id = ? ORDER BY title", [user_id])
    return [
        Routine(
            id=r["id"], title=r["title"], minutes=r["minutes"], days=json.loads(r["days_json"]),
            where=r["where_"], category=r["category"], priority=r["priority"],
            windowStart=r["window_start"], windowEnd=r["window_end"], active=bool(r["active"]),
        )
        for r in rows
    ]


async def list_events(user_id: str, from_ms: int, to_ms: int) -> list[FixedEvent]:
    rows = await all_rows(
        "SELECT e.*, s.label FROM events e LEFT JOIN sources s ON s.id = e.source_id "
        "WHERE e.user_id = ? AND e.end > ? AND e.start < ? ORDER BY e.start",
        [user_id, from_ms, to_ms],
    )
    return [
        FixedEvent(
            id=r["id"], title=r["title"], start=r["start"], end=r["end"], allDay=bool(r["all_day"]),
            placeId=r["place_id"], sourceId=r["source_id"], sourceLabel=r["label"] or "Calendar",
            location=r["location"],
        )
        for r in rows
    ]


@dataclass
class DayState:
    checkinDone: bool = False
    energy: Optional[str] = None
    skipped: list[str] = field(default_factory=list)
    planJson: Optional[str] = None
    planVersion: Optional[int] = None
    briefing: Optional[str] = None
    published: Optional[dict] = None
    doneBlocks: list[str] = field(default_factory=list)


async def get_day_state(user_id: str, date: str) -> DayState:
    r = await one_row("SELECT * FROM day_state WHERE user_id = ? AND date = ?", [user_id, date])
    if not r:
        return DayState()
    return DayState(
        checkinDone=bool(r["checkin_done"]),
        energy=r["energy"],
        skipped=json.loads(r["skipped_json"]),
        planJson=r["plan_json"],
        planVersion=r["plan_version"],
        briefing=r["briefing"],
        published=json.loads(r["published_json"]) if r["published_json"] else None,
        doneBlocks=json.loads(r["done_blocks_json"]),
    )


async def patch_day_state(user_id: str, date: str, patch: dict[str, Any]) -> None:
    await run("INSERT INTO day_state (user_id, date) VALUES (?, ?) ON CONFLICT DO NOTHING", [user_id, date])
    if not patch:
        return
    keys = list(patch.keys())
    sets = ", ".join(f"{k} = ?" for k in keys)
    await run(f"UPDATE day_state SET {sets} WHERE user_id = ? AND date = ?", [patch[k] for k in keys] + [user_id, date])

"""Plan one day, looking ahead lookaheadDays so deadlines later in the week
get their fair share of today. Pure function: no I/O.

Faithful port of src/lib/planner/index.ts.
"""
from __future__ import annotations

import time as _time

from .allocate import DayCapacity, allocate, last_work_day
from .place import PlaceItem, place_items
from .skeleton import build_skeleton, usable_minutes
from .time import add_days, fmt_time, MIN, weekday_of
from .types import (
    AtRiskItem,
    DayLoad,
    DayOverrides,
    DaySkeleton,
    PlanBlock,
    PlanInput,
    PlanResult,
    PlanStats,
    PlanWarning,
    Routine,
    UnplacedItem,
)

ENERGY_FACTOR = {"low": 0.7, "ok": 1.0, "high": 1.15}


def _routines_for(date: str, routines: list[Routine], tz: str, skipped: list[str] | None = None) -> list[Routine]:
    skipped = skipped or []
    wd = weekday_of(date, tz)
    return [r for r in routines if r.active and wd in r.days and r.id not in skipped]


def _capacity_of(sk: DaySkeleton, inp: PlanInput, is_today: bool) -> float:
    s = inp.settings
    raw = sum(
        usable_minutes((w.end - w.start) / MIN, s.focusMin, s.breakMin)
        for w in sk.windows if w.where != "transit"
    )
    energy = ENERGY_FACTOR[(inp.overrides.energy if (is_today and inp.overrides and inp.overrides.energy) else "ok")] if is_today else 1.0
    skipped = (inp.overrides.skippedEventIds if (is_today and inp.overrides) else None) or []
    routine_min = sum(r.minutes for r in _routines_for(sk.date, inp.routines, s.timezone, skipped))
    return max(0.0, min(raw, s.maxWorkMinPerDay * energy) - routine_min)


def _kind_order(b: PlanBlock) -> int:
    return 0 if b.kind == "travel" else 1 if b.kind == "event" else 2


def plan_day(inp: PlanInput) -> PlanResult:
    date, settings = inp.date, inp.settings
    tz = settings.timezone
    now_ms = inp.now if inp.now is not None else int(_time.time() * 1000)

    horizon = [add_days(date, i, tz) for i in range(max(1, settings.lookaheadDays))]
    skeletons = [
        build_skeleton(
            d,
            inp.events,
            inp.places,
            settings,
            inp.travel,
            inp.overrides if i == 0 else DayOverrides(),
            inp.now if i == 0 else None,
        )
        for i, d in enumerate(horizon)
    ]
    today = skeletons[0]

    caps = [DayCapacity(date=sk.date, capacityMin=_capacity_of(sk, inp, i == 0)) for i, sk in enumerate(skeletons)]
    alloc = allocate(inp.tasks, caps, settings, now_ms)
    quotas = alloc.byDay.get(date, {})

    energy = (inp.overrides.energy if inp.overrides else None) or "ok"
    if energy == "low":
        place_settings = settings.__class__(**{**settings.__dict__, "focusMin": max(25, round(settings.focusMin * 0.6))})
    else:
        place_settings = settings

    task_by_id = {t.id: t for t in inp.tasks}
    items: list[PlaceItem] = []
    skipped_ids = (inp.overrides.skippedEventIds if inp.overrides else None) or []
    for r in _routines_for(date, inp.routines, tz, skipped_ids):
        items.append(PlaceItem(
            id=r.id, kind="routine", title=r.title, minutes=r.minutes, where=r.where, splittable=False,
            priority=r.priority, category=r.category, windowStart=r.windowStart, windowEnd=r.windowEnd,
        ))
    for id_ in alloc.order:
        m = quotas.get(id_)
        t = task_by_id.get(id_)
        if not m or not t:
            continue
        items.append(PlaceItem(
            id=id_, kind="task", title=t.title, minutes=m, where=t.where, splittable=t.splittable,
            priority=t.priority, category=t.category, sourceLabel=t.sourceLabel,
        ))

    def rank_of(it: PlaceItem) -> int:
        if it.kind == "routine":
            return 2
        if it.priority == 4 or it.id in alloc.overdue:
            return 0
        t = task_by_id.get(it.id)
        return 1 if (t and last_work_day(t, tz) == date) else 3

    items.sort(key=rank_of)

    placed = place_items(date, today.windows, items, place_settings)

    warnings: list[PlanWarning] = list(today.warnings)
    for id_ in alloc.overdue:
        t = task_by_id.get(id_)
        if t:
            warnings.append(PlanWarning(kind="overdue", taskId=id_, message=f"“{t.title}” is past due — scheduled first today."))
    for r in alloc.atRisk:
        t = task_by_id.get(r.taskId)
        if t:
            due_str = ""
            if t.dueAt:
                from datetime import datetime
                from zoneinfo import ZoneInfo
                dt = datetime.fromtimestamp(t.dueAt / 1000, tz=ZoneInfo(tz))
                due_str = f" {dt.strftime('%a')}" + ("" if t.dueAllDay else f" {fmt_time(t.dueAt, tz)}")
            warnings.append(PlanWarning(
                kind="atRisk", taskId=r.taskId, minutes=r.shortfallMin,
                message=(f"“{t.title}” needs ~{round(r.shortfallMin)} more min than your free time before it's due{due_str}. "
                         "Start earlier, trim the estimate, or drop something."),
            ))
    for u in placed.unplaced:
        title = task_by_id.get(u.id).title if (u.kind == "task" and task_by_id.get(u.id)) else next((r.title for r in inp.routines if r.id == u.id), None)
        warnings.append(PlanWarning(kind="didntFit", taskId=u.id, minutes=u.minutes, message=f"{round(u.minutes)} min of “{title}” didn't fit today."))

    past_kept: list[PlanBlock] = []
    if inp.now:
        for b in (inp.pastBlocks or []):
            if b.kind in ("task", "routine", "break") and b.end <= inp.now:
                past_kept.append(b)

    blocks = sorted(list(today.blocks) + past_kept + list(placed.blocks), key=lambda b: (b.start, _kind_order(b)))

    def sum_kinds(kinds: tuple[str, ...]) -> float:
        return round(sum((b.end - b.start) for b in blocks if b.kind in kinds) / MIN)

    week: list[DayLoad] = []
    for i, sk in enumerate(skeletons):
        week.append(DayLoad(
            date=sk.date,
            eventMin=round(sum((b.end - b.start) for b in sk.blocks if b.kind == "event") / MIN),
            travelMin=round(sum((b.end - b.start) for b in sk.blocks if b.kind == "travel") / MIN),
            capacityMin=caps[i].capacityMin,
            allocatedMin=sum(alloc.byDay.get(sk.date, {}).values()),
        ))

    return PlanResult(
        date=date,
        generatedAt=now_ms,
        blocks=blocks,
        warnings=warnings,
        stats=PlanStats(
            focusMin=sum_kinds(("task", "routine")),
            travelMin=sum_kinds(("travel",)),
            eventMin=sum_kinds(("event",)),
            freeMin=placed.freeMin,
            dayMin=round((today.dayEnd - today.dayStart) / MIN),
        ),
        quotas=quotas,
        atRisk=[AtRiskItem(taskId=a.taskId, shortfallMin=a.shortfallMin) for a in alloc.atRisk],
        week=week,
        unplaced=[UnplacedItem(taskId=u.id, minutes=u.minutes) for u in placed.unplaced if u.kind == "task"],
        dueSoon=[t.id for t in inp.tasks if not t.done and t.dueAt and (last_work_day(t, tz) or "9999") <= date],
    )

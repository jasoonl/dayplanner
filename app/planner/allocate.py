"""Spread every open task's remaining minutes across the look-ahead horizon.

Faithful port of src/lib/planner/allocate.ts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .time import add_days, date_of, minutes_of_day
from .types import PlannerSettings, Task


@dataclass
class DayCapacity:
    date: str
    capacityMin: float


@dataclass
class AtRisk:
    taskId: str
    shortfallMin: float


@dataclass
class Allocation:
    byDay: dict[str, dict[str, float]]
    atRisk: list[AtRisk] = field(default_factory=list)
    overdue: list[str] = field(default_factory=list)
    order: list[str] = field(default_factory=list)


def round5(n: float) -> float:
    return math.ceil(n / 5) * 5


def last_work_day(task: Task, tz: str) -> str | None:
    """Last calendar day on which work on this task still counts."""
    if not task.dueAt:
        return None
    due_day = date_of(task.dueAt, tz)
    if task.dueAllDay:
        return add_days(due_day, -1, tz)
    return due_day if minutes_of_day(task.dueAt, tz) >= 15 * 60 else add_days(due_day, -1, tz)


def remaining_min(t: Task) -> float:
    return max(0, round(t.estimateMin - t.spentMin))


@dataclass
class _Row:
    t: Task
    rem: float
    last: str | None
    overdue: bool


def allocate(tasks: list[Task], days: list[DayCapacity], settings: PlannerSettings, now: int) -> Allocation:
    tz = settings.timezone
    today = days[0].date
    horizon_end = days[-1].date
    cap: dict[str, float] = {d.date: max(0.0, d.capacityMin) for d in days}
    by_day: dict[str, dict[str, float]] = {d.date: {} for d in days}
    at_risk: list[AtRisk] = []
    overdue: list[str] = []

    def give(date: str, id_: str, m: float) -> None:
        if m <= 0:
            return
        by_day[date][id_] = by_day[date].get(id_, 0) + m
        cap[date] -= m

    rows: list[_Row] = []
    for t in tasks:
        if t.done or remaining_min(t) <= 0:
            continue
        last = last_work_day(t, tz)
        is_overdue = bool(t.dueAt) and (t.dueAt <= now or (last is not None and last < today))
        rows.append(_Row(t=t, rem=remaining_min(t), last=last, overdue=is_overdue))

    def rank(r: _Row) -> int:
        if r.t.priority == 4:
            return 0
        if r.overdue:
            return 1
        if r.last:
            return 2
        return 3

    rows.sort(key=lambda r: (rank(r), r.last or "9999", -r.t.priority, -r.rem))

    day_list = [d.date for d in days]

    for r in rows:
        t = r.t
        if r.overdue:
            overdue.append(t.id)

        if t.notBefore:
            first = sorted([date_of(t.notBefore, tz), today])[1]
        else:
            first = today

        if rank(r) <= 1:
            if first in by_day:
                give(first, t.id, r.rem)
            continue

        if not r.last:
            per_day = settings.focusMin * 2 if t.priority >= 3 else settings.focusMin
            left = r.rem
            for d in day_list:
                if d < first or left <= 0:
                    continue
                m = min(per_day, left, max(0.0, cap[d]))
                if m >= min(settings.minChunkMin, left):
                    give(d, t.id, m)
                    left -= m
            continue

        last_in_horizon = r.last if r.last < horizon_end else horizon_end
        eligible = [d for d in day_list if first <= d <= last_in_horizon]
        if not eligible:
            at_risk.append(AtRisk(taskId=t.id, shortfallMin=r.rem))
            continue

        target = r.rem
        if r.last > horizon_end:
            total_days = len(eligible)
            d = add_days(horizon_end, 1, tz)
            guard = 0
            while d <= r.last and total_days < 400 and guard < 1000:
                total_days += 1
                d = add_days(d, 1, tz)
                guard += 1
            target = round5((r.rem * len(eligible)) / total_days)

        if not t.splittable:
            found = next((x for x in eligible if cap[x] >= target), None)
            if found:
                give(found, t.id, target)
            elif r.last <= horizon_end:
                at_risk.append(AtRisk(taskId=t.id, shortfallMin=target))
            continue

        left = target
        per = round5(max(settings.minChunkMin, target / len(eligible)))
        for d in eligible:
            m = min(per, left, max(0.0, cap[d]))
            if m >= min(settings.minChunkMin, left):
                give(d, t.id, m)
                left -= m
        for d in eligible:
            if left <= 0:
                break
            m = min(left, max(0.0, cap[d]))
            if m >= min(settings.minChunkMin, left):
                give(d, t.id, m)
                left -= m
        if left > 0 and r.last <= horizon_end:
            at_risk.append(AtRisk(taskId=t.id, shortfallMin=left))

    return Allocation(byDay=by_day, atRisk=at_risk, overdue=overdue, order=[r.t.id for r in rows])

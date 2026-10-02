"""Pack items (already in priority order) into free windows, earliest first.

Focus blocks are capped at focusMin with a breakMin break between them;
portable items ride transit first; home-only items wait for home windows.

Faithful port of src/lib/planner/place.ts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .time import at_time, ceil_to, MIN
from .types import Category, FreeWindow, PlanBlock, PlannerSettings, Priority, Where


@dataclass
class PlaceItem:
    id: str
    kind: str  # "task" | "routine"
    title: str
    minutes: float
    where: Where
    splittable: bool
    priority: Priority
    category: Category
    sourceLabel: Optional[str] = None
    windowStart: Optional[str] = None
    windowEnd: Optional[str] = None


@dataclass
class _Slot:
    start: int
    end: int
    where: str
    placeId: Optional[str]
    cursor: int
    streak: float = 0


@dataclass
class Unplaced:
    id: str
    kind: str
    minutes: float


@dataclass
class PlaceResult:
    blocks: list[PlanBlock]
    unplaced: list[Unplaced]
    freeMin: float


def _fits(item: PlaceItem, s: _Slot) -> bool:
    if s.where == "transit":
        return item.where == "portable"
    if s.where == "away":
        return item.where != "home"
    return True


def place_items(date: str, windows: list[FreeWindow], items: list[PlaceItem], settings: PlannerSettings) -> PlaceResult:
    tz = settings.timezone
    focus_min, break_min, min_chunk_min = settings.focusMin, settings.breakMin, settings.minChunkMin
    blocks: list[PlanBlock] = []
    unplaced: list[Unplaced] = []
    n = [0]

    slots: list[_Slot] = sorted(
        (_Slot(start=w.start, end=w.end, where=w.where, placeId=w.placeId, cursor=w.start) for w in windows),
        key=lambda s: s.start,
    )

    def mk(item: PlaceItem, start: int, end: int, s: _Slot) -> PlanBlock:
        b = PlanBlock(
            id=f"{item.kind}-{item.id}-{n[0]}",
            kind=item.kind,  # type: ignore[arg-type]
            start=start,
            end=end,
            title=item.title,
            placeId=s.placeId,
            taskId=item.id if item.kind == "task" else None,
            routineId=item.id if item.kind == "routine" else None,
            category=item.category,
            priority=item.priority,
            sourceLabel=item.sourceLabel,
            onTransit=True if s.where == "transit" else None,
        )
        n[0] += 1
        return b

    def break_block(start: int, end: int) -> PlanBlock:
        b = PlanBlock(id=f"break-{date}-{n[0]}", kind="break", start=start, end=end, title="Break")
        n[0] += 1
        return b

    # Phase 1: routines that want a specific time window get carved first.
    constrained = [i for i in items if i.kind == "routine" and (i.windowStart or i.windowEnd)]
    constrained_ids = {id(i) for i in constrained}
    rest = [i for i in items if id(i) not in constrained_ids]
    for item in constrained:
        lo = at_time(date, item.windowStart, tz) if item.windowStart else 0
        hi = at_time(date, item.windowEnd, tz) if item.windowEnd else 2**62
        dur = item.minutes * MIN
        done = False
        i = 0
        while i < len(slots) and not done:
            s = slots[i]
            if not _fits(item, s) or s.where == "transit":
                i += 1
                continue
            start = ceil_to(max(s.start, lo))
            end = start + dur
            if end <= min(s.end, hi):
                blocks.append(mk(item, start, end, s))
                after = end + break_min * MIN
                parts: list[_Slot] = []
                if start - s.start >= 10 * MIN:
                    parts.append(_Slot(start=s.start, end=start, where=s.where, placeId=s.placeId, cursor=s.start))
                if s.end - after >= 10 * MIN:
                    parts.append(_Slot(start=after, end=s.end, where=s.where, placeId=s.placeId, cursor=after))
                slots[i:i + 1] = parts
                done = True
            else:
                i += 1
        if not done:
            fallback = PlaceItem(**{**item.__dict__, "windowStart": None, "windowEnd": None})
            rest.insert(0, fallback)
    slots.sort(key=lambda s: s.start)

    # Phase 2: greedy fill.
    for item in rest:
        need = item.minutes
        if item.where == "portable":
            order = [s for s in slots if s.where == "transit"] + [s for s in slots if s.where != "transit"]
            whole = next((s for s in order if s.where == "transit" and (s.end - s.cursor) / MIN >= need), None)
            if whole:
                order = [whole] + [s for s in order if s is not whole]
        else:
            order = [s for s in slots if s.where != "transit"]

        for s in order:
            if need <= 0:
                break
            if not _fits(item, s):
                continue

            if not item.splittable:
                start = s.cursor + break_min * MIN if s.streak > 0 else s.cursor
                if s.end - start >= need * MIN:
                    if s.streak > 0:
                        blocks.append(break_block(start - break_min * MIN, start))
                    blocks.append(mk(item, start, start + need * MIN, s))
                    s.cursor = start + need * MIN
                    s.streak = focus_min
                    need = 0
                continue

            transit = s.where == "transit"
            min_chunk = 10 if transit else min_chunk_min
            while need > 0:
                start = s.cursor
                pending_break = False
                if not transit and s.streak >= focus_min:
                    start = s.cursor + break_min * MIN
                    pending_break = True
                room = math.floor((s.end - start) / MIN)
                cap = room if transit else min(room, focus_min if pending_break else focus_min - s.streak)
                chunk = min(need, cap)
                if chunk <= 0 or chunk < min(min_chunk, need):
                    if (not transit and not pending_break and s.streak > 0
                            and s.end - (s.cursor + break_min * MIN) >= min(min_chunk, need) * MIN):
                        s.streak = focus_min
                        continue
                    break
                if pending_break:
                    blocks.append(break_block(s.cursor, start))
                blocks.append(mk(item, start, start + chunk * MIN, s))
                s.cursor = start + chunk * MIN
                s.streak = chunk if pending_break else s.streak + chunk
                need -= chunk
        if need > 0:
            unplaced.append(Unplaced(id=item.id, kind=item.kind, minutes=need))

    # Merge adjacent blocks of the same item.
    blocks.sort(key=lambda b: b.start)
    merged: list[PlanBlock] = []
    for b in blocks:
        prev = merged[-1] if merged else None
        if (prev and prev.kind == b.kind and prev.kind != "break" and prev.end == b.start
                and (prev.taskId or prev.routineId) == (b.taskId or b.routineId) and prev.onTransit == b.onTransit):
            prev.end = b.end
        else:
            import copy
            merged.append(copy.copy(b))

    window_min = sum((w.end - w.start) for w in windows if w.where != "transit")
    used_min = sum((b.end - b.start) for b in merged if not b.onTransit)
    free_min = max(0, round((window_min - used_min) / MIN))

    return PlaceResult(blocks=merged, unplaced=unplaced, freeMin=free_min)

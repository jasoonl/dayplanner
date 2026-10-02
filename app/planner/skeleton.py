"""Fixed structure of one day: events, travel legs, meals, prep — and the
free windows (with where you physically are) that remain for work.

Faithful port of src/lib/planner/skeleton.ts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .time import at_time, ceil_to, floor_to, fmt_time, MIN, start_of_day, weekday_of
from .types import (
    DayOverrides,
    DaySkeleton,
    FixedEvent,
    FreeWindow,
    Place,
    PlanBlock,
    PlannerSettings,
    PlanWarning,
    TravelLookup,
)


@dataclass
class _Seg:
    start: int
    end: int
    placeId: Optional[str]


def day_bounds(date: str, settings: PlannerSettings) -> tuple[int, int, int]:
    tz = settings.timezone
    wd = str(weekday_of(date, tz))
    cfg = settings.days.get(wd)
    wake_s = cfg.wake if cfg else "07:00"
    bed_s = cfg.bedtime if cfg else "23:00"
    wake = at_time(date, wake_s, tz)
    bed = at_time(date, bed_s, tz)
    if bed <= wake:
        bed += 24 * 60 * MIN
    day_end = bed - settings.windDownMin * MIN
    return wake, bed, day_end


def build_skeleton(
    date: str,
    all_events: list[FixedEvent],
    places: list[Place],
    settings: PlannerSettings,
    travel: TravelLookup,
    overrides: Optional[DayOverrides] = None,
    now: Optional[int] = None,
) -> DaySkeleton:
    overrides = overrides or DayOverrides()
    tz = settings.timezone
    wake, bedtime, day_end = day_bounds(date, settings)
    midnight = start_of_day(date, tz)
    next_midnight = midnight + 24 * 60 * MIN
    home = next((p.id for p in places if p.isHome), None)

    def place_name(pid: Optional[str]) -> str:
        for p in places:
            if p.id == pid:
                return p.name
        return "?"

    skipped = set(overrides.skippedEventIds or [])

    blocks: list[PlanBlock] = []
    warnings: list[PlanWarning] = []
    segs: list[_Seg] = []

    events = sorted(
        (e for e in all_events if not e.allDay and e.id not in skipped and e.end > midnight and e.start < next_midnight),
        key=lambda e: (e.start, -e.end),
    )

    prep_end = wake + settings.morningRoutineMin * MIN
    if settings.morningRoutineMin > 0:
        blocks.append(PlanBlock(id=f"prep-{date}", kind="prep", start=wake, end=prep_end, title="Get ready", placeId=home))

    cur: Optional[str] = home
    free = prep_end
    last_event: Optional[FixedEvent] = None
    leg_n = 0

    def add_seg(s: int, e: int, p: Optional[str]) -> None:
        start = max(s, wake)
        end = min(e, day_end)
        if end - start >= MIN:
            segs.append(_Seg(start, end, p))

    def add_leg(frm: str, to: str, s: int, e: int, late: bool = False) -> None:
        nonlocal leg_n
        blocks.append(
            PlanBlock(
                id=f"travel-{date}-{leg_n}",
                kind="travel",
                start=s,
                end=e,
                title=f"Travel to {place_name(to)}",
                subtitle=f"Leave {place_name(frm)} by {fmt_time(s, tz)}",
                fromPlaceId=frm,
                toPlaceId=to,
                mode=settings.travelMode,
                late=late,
            )
        )
        leg_n += 1

    for idx, ev in enumerate(events):
        if not ev.placeId and home and cur and cur != home:
            next_located = next((e for e in events[idx + 1:] if e.placeId), None)
            if (next_located.placeId if next_located else None) != cur:
                t = travel(cur, home, ev.start) * MIN
                if free + t <= ev.start:
                    add_leg(cur, home, free, free + t)
                    free += t
                    cur = home

        if last_event and ev.start < last_event.end:
            warnings.append(
                PlanWarning(
                    kind="conflict",
                    eventId=ev.id,
                    message=f"“{ev.title}” overlaps “{last_event.title}” ({fmt_time(ev.start, tz)}).",
                )
            )

        if ev.placeId and home and cur and ev.placeId != cur:
            arrive_by = ev.start - settings.arriveEarlyMin * MIN
            went_home = False

            if cur != home and ev.placeId != home:
                t1 = travel(cur, home, free + 60 * MIN) * MIN
                t2 = travel(home, ev.placeId, arrive_by) * MIN
                home_start = free + t1
                leave_home = floor_to(arrive_by - t2)
                if leave_home - home_start >= settings.goHomeThresholdMin * MIN:
                    add_leg(cur, home, free, home_start)
                    add_seg(home_start, leave_home, home)
                    add_leg(home, ev.placeId, leave_home, leave_home + t2)
                    if ev.start > leave_home + t2:
                        blocks.append(PlanBlock(id=f"buf-{ev.id}", kind="buffer", start=leave_home + t2, end=ev.start, title="Arrive early"))
                    went_home = True

            if not went_home:
                t = travel(cur, ev.placeId, arrive_by) * MIN
                leave = floor_to(arrive_by - t)
                late = False
                if leave < free:
                    leave = free
                    arrive = leave + t
                    if arrive > ev.start:
                        late = True
                        late_min = round((arrive - ev.start) / MIN)
                        warnings.append(
                            PlanWarning(
                                kind="late",
                                eventId=ev.id,
                                minutes=late_min,
                                message=(
                                    f"You'd reach “{ev.title}” about {late_min} min late "
                                    f"— {round(t / MIN)} min trip from {place_name(cur)}."
                                ),
                            )
                        )
                add_seg(free, leave, cur)
                add_leg(cur, ev.placeId, leave, leave + t, late)
                if ev.start > leave + t:
                    blocks.append(PlanBlock(id=f"buf-{ev.id}", kind="buffer", start=leave + t, end=ev.start, title="Arrive early"))
            cur = ev.placeId
        else:
            add_seg(free, ev.start, cur)
            if ev.placeId and not home:
                cur = ev.placeId

        blocks.append(
            PlanBlock(
                id=f"ev-{ev.id}",
                kind="event",
                start=ev.start,
                end=ev.end,
                title=ev.title,
                subtitle=ev.location,
                placeId=ev.placeId,
                eventId=ev.id,
                sourceLabel=ev.sourceLabel,
            )
        )
        free = max(free, ev.end)
        if not last_event or ev.end > last_event.end:
            last_event = ev

    if home and cur and cur != home:
        t = travel(cur, home, free + 60 * MIN) * MIN
        add_leg(cur, home, free, free + t)
        free += t
        cur = home
    add_seg(free, day_end, cur)

    busy_ends = [b.end for b in blocks if b.kind in ("event", "travel")]
    last_busy_end = max(busy_ends) if busy_ends else 0
    if last_busy_end > bedtime:
        warnings.append(
            PlanWarning(
                kind="pastBedtime",
                message=f"You won't be home and done until {fmt_time(last_busy_end, tz)}, past your {fmt_time(bedtime, tz)} bedtime.",
            )
        )

    # Meals: carve out of free segments (preferred time first, then nearest)
    wd = weekday_of(date, tz)
    for meal in [m for m in settings.meals if wd in m.days]:
        lo = at_time(date, meal.earliest, tz)
        hi = at_time(date, meal.latest, tz) - meal.minutes * MIN
        pref = at_time(date, meal.preferred, tz)
        dur = meal.minutes * MIN
        placed = False
        candidates: list[int] = []
        d = 0
        while pref - d >= lo or pref + d <= hi:
            if pref + d <= hi:
                candidates.append(pref + d)
            if d > 0 and pref - d >= lo:
                candidates.append(pref - d)
            d += 5 * MIN
        for s in segs:
            if s.end - dur >= lo and s.end - dur <= hi:
                candidates.append(s.end - dur)
            if s.start >= lo and s.start <= hi:
                candidates.append(s.start)
        candidates.sort(key=lambda a: abs(a - pref))
        for t in candidates:
            i = next((j for j, s in enumerate(segs) if s.start <= t and s.end >= t + dur), -1)
            if i == -1:
                continue
            s = segs[i]
            parts: list[_Seg] = []
            if t - s.start >= MIN:
                parts.append(_Seg(s.start, t, s.placeId))
            if s.end - (t + dur) >= MIN:
                parts.append(_Seg(t + dur, s.end, s.placeId))
            segs[i:i + 1] = parts
            blocks.append(
                PlanBlock(
                    id=f"meal-{date}-{meal.title}",
                    kind="meal",
                    start=t,
                    end=t + dur,
                    title=f"{meal.title} (near {place_name(s.placeId)})" if s.placeId and s.placeId != home else meal.title,
                    placeId=s.placeId,
                )
            )
            placed = True
            break
        if not placed:
            warnings.append(
                PlanWarning(
                    kind="noMeal",
                    message=f"No {meal.minutes}-min gap for {meal.title.lower()} between {meal.earliest} and {meal.latest}. Pack food or eat on the way.",
                )
            )

    # Free windows (clipped to "now" for replans)
    floor = max(wake, ceil_to(now)) if now else wake
    windows: list[FreeWindow] = []
    for s in sorted(segs, key=lambda s: s.start):
        start = max(ceil_to(s.start), floor)
        end = floor_to(s.end)
        if end - start >= 10 * MIN:
            windows.append(FreeWindow(start=start, end=end, where=("home" if (s.placeId == home or not home) else "away"), placeId=s.placeId))

    if settings.travelMode == "TRANSIT":
        for b in [x for x in blocks if x.kind == "travel"]:
            start = max(ceil_to(b.start + 5 * MIN), floor)
            end = floor_to(b.end - 5 * MIN)
            if end - start >= 15 * MIN:
                windows.append(FreeWindow(start=start, end=end, where="transit", placeId=None))

    blocks.sort(key=lambda b: b.start)
    return DaySkeleton(date=date, dayStart=wake, dayEnd=day_end, blocks=blocks, windows=windows, warnings=warnings)


def usable_minutes(len_min: float, focus_min: int, break_min: int) -> float:
    if len_min <= 0:
        return 0
    breaks = int(len_min // (focus_min + break_min))
    return max(0.0, len_min - breaks * break_min)

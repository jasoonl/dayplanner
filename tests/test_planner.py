"""Port of tests/planner.test.ts — same 20 cases, same semantics."""
from __future__ import annotations

import pytest

from app.planner.allocate import last_work_day
from app.planner.defaults import default_settings
from app.planner.index import plan_day
from app.planner.time import at_time, fmt_time
from app.planner.types import DayOverrides, FixedEvent, Place, PlanInput, Routine, Task

TZ = "America/New_York"
settings = default_settings(TZ)
TUE = "2026-09-22"


def at(d: str, t: str) -> int:
    return at_time(d, t, TZ)


places = [
    Place(id="home", name="Home", address="UES", aliases=[], isHome=True),
    Place(id="dalton", name="Dalton", address="108 E 89th St", aliases=["dalton"]),
    Place(id="msm", name="MSM", address="130 Claremont Ave", aliases=["msm"]),
    Place(id="mfc", name="Manhattan Fencing Center", address="MFC", aliases=["fencing"]),
]

TT = {
    "home>dalton": 25, "dalton>home": 25, "dalton>msm": 30, "msm>dalton": 30,
    "home>msm": 35, "msm>home": 35, "home>mfc": 60, "mfc>home": 60,
    "dalton>mfc": 50, "mfc>dalton": 50, "msm>mfc": 45, "mfc>msm": 45,
}


def travel(a: str, b: str, arrive_by: int) -> int:
    return TT.get(f"{a}>{b}", 30)


def ev(id_: str, title: str, d: str, s: str, e: str, place_id: str | None) -> FixedEvent:
    return FixedEvent(id=id_, title=title, start=at(d, s), end=at(d, e), placeId=place_id, sourceId="src", sourceLabel="Test")


tuesday_events = [
    ev("school", "School", TUE, "08:10", "15:30", "dalton"),
    ev("violin", "Violin lesson", TUE, "16:30", "17:30", "msm"),
    ev("sat", "SAT tutor (Zoom)", TUE, "19:00", "20:00", None),
]


def task(id_: str, **over) -> Task:
    defaults = dict(title=id_, category="school", estimateMin=60, spentMin=0, priority=2, where="anywhere",
                     splittable=True, done=False)
    defaults.update(over)
    return Task(id=id_, **defaults)


def base(**over) -> PlanInput:
    defaults = dict(date=TUE, now=at(TUE, "06:00"), events=tuesday_events, tasks=[], routines=[],
                     places=places, settings=settings, travel=travel)
    defaults.update(over)
    return PlanInput(**defaults)


def assert_no_overlaps(blocks):
    solid = sorted((b for b in blocks if b.kind != "buffer" and not b.onTransit), key=lambda b: b.start)
    for i in range(1, len(solid)):
        assert solid[i].start >= solid[i - 1].end, f"{solid[i-1].title} overlaps {solid[i].title}"
    legs = [b for b in blocks if b.kind == "travel"]
    for b in blocks:
        if b.onTransit:
            assert any(l.start <= b.start and l.end >= b.end for l in legs), f"{b.title} not inside a ride"


# --- travel and locations ---------------------------------------------------

def test_leave_by_leg_and_route():
    r = plan_day(base())
    legs = [b for b in r.blocks if b.kind == "travel"]
    assert [f"{l.fromPlaceId}>{l.toPlaceId}" for l in legs] == ["home>dalton", "dalton>msm", "msm>home"]
    assert fmt_time(legs[0].start, TZ) == "7:35 AM"
    assert fmt_time(legs[1].start, TZ) == "3:50 PM"
    assert fmt_time(legs[2].end, TZ) == "6:05 PM"
    assert_no_overlaps(r.blocks)


def test_go_home_between_events_when_worth_it():
    WED = "2026-09-23"
    events = [ev("school", "School", WED, "08:10", "15:30", "dalton"), ev("fence", "Fencing", WED, "18:30", "20:30", "mfc")]
    r = plan_day(base(date=WED, now=at(WED, "06:00"), events=events))
    legs = [f"{l.fromPlaceId}>{l.toPlaceId}" for l in r.blocks if l.kind == "travel"]
    assert legs == ["home>dalton", "dalton>home", "home>mfc", "mfc>home"]

    tight = [ev("school", "School", WED, "08:10", "15:30", "dalton"), ev("fence", "Fencing", WED, "16:30", "18:00", "mfc")]
    r2 = plan_day(base(date=WED, now=at(WED, "06:00"), events=tight))
    assert [f"{l.fromPlaceId}>{l.toPlaceId}" for l in r2.blocks if l.kind == "travel"] == ["home>dalton", "dalton>mfc", "mfc>home"]


def test_warns_when_cannot_arrive_on_time():
    events = [ev("a", "School", TUE, "08:10", "15:30", "dalton"), ev("b", "Fencing", TUE, "15:45", "17:00", "mfc")]
    r = plan_day(base(events=events))
    late = next((w for w in r.warnings if w.kind == "late"), None)
    assert late is not None and late.minutes == 35
    leg = next((b for b in r.blocks if b.kind == "travel" and b.toPlaceId == "mfc"), None)
    assert leg is not None and leg.late is True


def test_flags_overlapping_events():
    events = tuesday_events + [ev("dup", "Club meeting", TUE, "15:00", "16:00", "dalton")]
    r = plan_day(base(events=events))
    assert any(w.kind == "conflict" for w in r.warnings)


def test_warns_past_bedtime():
    FRI = "2026-09-25"
    events = [ev("f", "Fencing", FRI, "21:30", "23:15", "mfc")]
    r = plan_day(base(date=FRI, now=at(FRI, "06:00"), events=events))
    assert any(w.kind == "pastBedtime" for w in r.warnings)


# --- meals and prep ----------------------------------------------------------

def test_protects_dinner_after_violin():
    r = plan_day(base())
    dinner = next((b for b in r.blocks if b.kind == "meal"), None)
    assert dinner is not None
    assert dinner.start >= at(TUE, "18:05")
    assert dinner.end <= at(TUE, "19:00")
    prep = next((b for b in r.blocks if b.kind == "prep"), None)
    assert prep is not None and prep.end == at(TUE, "07:25")


# --- task scheduling ----------------------------------------------------------

def test_spreads_essay_across_two_days():
    essay = task("essay", title="History essay", estimateMin=240, dueAt=at("2026-09-24", "00:00"), dueAllDay=True, priority=3)
    assert last_work_day(essay, TZ) == "2026-09-23"
    r = plan_day(base(tasks=[essay]))
    assert r.quotas["essay"] == 120
    placed = sum((b.end - b.start) / 60000 for b in r.blocks if b.taskId == "essay")
    assert placed == 120
    assert r.week[1].allocatedMin == 120
    assert_no_overlaps(r.blocks)


def test_must_today_first_never_overlapping():
    t = task("must", title="Permission form", estimateMin=20, priority=4, where="home")
    r = plan_day(base(tasks=[t]))
    b = next((x for x in r.blocks if x.taskId == "must"), None)
    assert b is not None
    assert_no_overlaps(r.blocks)


def test_caps_focus_blocks_at_50():
    t = task("big", title="Lab report", estimateMin=150, dueAt=at(TUE, "23:59"), priority=3)
    r = plan_day(base(tasks=[t]))
    chunks = [b for b in r.blocks if b.taskId == "big"]
    for c in chunks:
        assert (c.end - c.start) / 60000 <= 50
    assert sum((c.end - c.start) / 60000 for c in chunks) == 150
    assert_no_overlaps(r.blocks)


def test_home_only_routine_window():
    practice = Routine(id="practice", title="Violin practice", minutes=45, days=[2], where="home", category="music",
                        priority=3, windowStart="20:00", windowEnd="22:30", active=True)
    r = plan_day(base(routines=[practice]))
    b = next((x for x in r.blocks if x.routineId == "practice"), None)
    assert b is not None
    assert b.placeId == "home"
    assert b.start >= at(TUE, "20:00")
    assert_no_overlaps(r.blocks)


def test_uses_subway_for_portable_work():
    WED = "2026-09-23"
    events = [ev("fence", "Fencing", WED, "18:30", "20:30", "mfc")]
    t = task("vocab", title="Spanish vocab", estimateMin=30, where="portable", dueAt=at(WED, "23:00"), priority=3)
    r = plan_day(base(date=WED, now=at(WED, "06:00"), events=events, tasks=[t]))
    b = next((x for x in r.blocks if x.taskId == "vocab"), None)
    assert b is not None and b.onTransit is True


def test_reports_at_risk():
    t = task("huge", title="Research paper", estimateMin=900, dueAt=at("2026-09-23", "23:59"), priority=3)
    r = plan_day(base(tasks=[t]))
    risk = next((a for a in r.atRisk if a.taskId == "huge"), None)
    assert risk is not None and risk.shortfallMin > 0
    assert any(w.kind == "atRisk" for w in r.warnings)


def test_only_fair_share_of_far_off_project():
    t = task("proj", title="Science fair", estimateMin=1400, dueAt=at("2026-10-19", "23:59"), priority=2)
    r = plan_day(base(tasks=[t]))
    week_total = sum(d.allocatedMin for d in r.week)
    assert 200 < week_total < 450
    assert len(r.atRisk) == 0


def test_schedules_overdue_and_warns():
    t = task("late", title="Reading response", estimateMin=30, dueAt=at("2026-09-21", "23:59"))
    r = plan_day(base(tasks=[t]))
    assert r.quotas["late"] == 30
    assert any(w.kind == "overdue" for w in r.warnings)


def test_replans_without_placing_in_past():
    t = task("hw", title="Math HW", estimateMin=60, dueAt=at("2026-09-23", "08:00"))
    now = at(TUE, "18:40")
    r = plan_day(base(tasks=[t], now=now))
    for b in r.blocks:
        if b.kind == "task":
            assert b.start >= now
    assert len([b for b in r.blocks if b.taskId == "hw"]) > 0


def test_low_energy_shortens_blocks():
    t = task("big", title="Lab report", estimateMin=90, dueAt=at(TUE, "23:59"), priority=3)
    r = plan_day(base(tasks=[t], overrides=DayOverrides(energy="low")))
    for c in r.blocks:
        if c.taskId == "big":
            assert (c.end - c.start) / 60000 <= 30


def test_skips_cancelled_events():
    r = plan_day(base(overrides=DayOverrides(skippedEventIds=["violin"])))
    assert not any(b.eventId == "violin" for b in r.blocks)
    assert [l.toPlaceId for l in r.blocks if l.kind == "travel"] == ["dalton", "home"]


def test_dst_change_day_no_crash():
    d = "2026-11-01"
    r = plan_day(base(date=d, now=at(d, "07:00"), events=[], tasks=[task("x", estimateMin=45)]))
    assert any(b.taskId == "x" for b in r.blocks)


def test_never_double_books_busy_day():
    tasks = [
        task("a", estimateMin=45, dueAt=at("2026-09-23", "08:00"), priority=3),
        task("b", estimateMin=120, dueAt=at("2026-09-25", "08:00"), priority=2),
        task("c", estimateMin=25, where="portable", priority=2, dueAt=at("2026-09-23", "08:00")),
        task("d", estimateMin=60, where="home", priority=4),
        task("e", estimateMin=90, splittable=False, dueAt=at("2026-09-24", "23:00"), priority=3),
    ]
    routines = [Routine(id="p", title="Practice", minutes=45, days=[2], where="home", category="music", priority=3, active=True)]
    r = plan_day(base(tasks=tasks, routines=routines))
    assert_no_overlaps(r.blocks)
    day_end = at(TUE, "22:30")
    for b in r.blocks:
        if b.kind in ("task", "routine"):
            assert b.end <= day_end

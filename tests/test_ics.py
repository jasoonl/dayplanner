"""Port of tests/ics.test.ts — same 5 cases."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.integrations.ics import parse_ics, split_course

TZ = "America/New_York"
_from = int(datetime(2026, 9, 1, tzinfo=ZoneInfo(TZ)).timestamp() * 1000)
_to = int(datetime(2026, 10, 31, tzinfo=ZoneInfo(TZ)).timestamp() * 1000)


def fmt(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=ZoneInfo(TZ)).strftime("%Y-%m-%d %H:%M")


def wrap(body: str, extra: str = "") -> str:
    parts = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//test//EN"]
    if extra:
        parts.append(extra)
    parts.append(body)
    parts.append("END:VCALENDAR")
    return "\r\n".join(parts)


NY_TZ = "\r\n".join([
    "BEGIN:VTIMEZONE", "TZID:America/New_York",
    "BEGIN:DAYLIGHT", "TZOFFSETFROM:-0500", "TZOFFSETTO:-0400", "TZNAME:EDT", "DTSTART:19700308T020000",
    "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU", "END:DAYLIGHT",
    "BEGIN:STANDARD", "TZOFFSETFROM:-0400", "TZOFFSETTO:-0500", "TZNAME:EST", "DTSTART:19701101T020000",
    "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU", "END:STANDARD",
    "END:VTIMEZONE",
])


def test_blackbaud_midnight_all_day():
    ics = wrap("\r\n".join([
        "BEGIN:VEVENT", "UID:bb-1", "SUMMARY:AP Biology - 2: Unit 3 Test",
        "DTSTART:20260925T040000Z", "DTEND:20260926T040000Z", "END:VEVENT",
        "BEGIN:VEVENT", "UID:bb-2", "SUMMARY:English 10 - 1: Gatsby ch. 4 response",
        "DTSTART;VALUE=DATE:20260923", "END:VEVENT",
    ]))
    items = parse_ics(ics, from_ms=_from, to_ms=_to, tz=TZ, role="assignments")
    assert len(items) == 2
    assert all(i.kind == "assignment" and i.allDay for i in items)
    assert [i.date for i in items] == ["2026-09-23", "2026-09-25"]
    assert split_course(items[1].title) == {"title": "Unit 3 Test", "course": "AP Biology"}


def test_classifies_canvas_mixed_feed():
    ics = wrap("\r\n".join([
        "BEGIN:VEVENT", "UID:event-assignment-4512", "SUMMARY:Scales & arpeggios log [Precollege Theory]",
        "DTSTART:20260927T035900Z", "DTEND:20260927T035900Z",
        "URL:https://msmnyc.instructure.com/courses/1/assignments/4512", "END:VEVENT",
        "BEGIN:VEVENT", "UID:event-calendar-event-99", "SUMMARY:Orchestra rehearsal",
        "DTSTART:20260926T140000Z", "DTEND:20260926T160000Z", "LOCATION:Manhattan School of Music", "END:VEVENT",
    ]))
    items = parse_ics(ics, from_ms=_from, to_ms=_to, tz=TZ, role="auto")
    a = next(i for i in items if "assignment" in i.uid)
    e = next(i for i in items if i.title == "Orchestra rehearsal")
    assert a.kind == "assignment"
    assert fmt(a.start) == "2026-09-26 23:59"
    assert e.kind == "event"
    assert fmt(e.start) == "2026-09-26 10:00"
    assert split_course(a.title) == {"title": "Scales & arpeggios log", "course": "Precollege Theory"}


def test_expands_weekly_recurrence_with_exceptions():
    ics = wrap("\r\n".join([
        "BEGIN:VEVENT", "UID:fence", "SUMMARY:Fencing practice", "LOCATION:Manhattan Fencing Center",
        "DTSTART;TZID=America/New_York:20260907T190000", "DTEND;TZID=America/New_York:20260907T210000",
        "RRULE:FREQ=WEEKLY;BYDAY=MO", "EXDATE;TZID=America/New_York:20260914T190000", "END:VEVENT",
        "BEGIN:VEVENT", "UID:fence", "RECURRENCE-ID;TZID=America/New_York:20260921T190000", "SUMMARY:Fencing practice (moved)",
        "DTSTART;TZID=America/New_York:20260921T180000", "DTEND;TZID=America/New_York:20260921T200000", "END:VEVENT",
    ]), NY_TZ)
    to_far = int(datetime(2026, 11, 10, tzinfo=ZoneInfo(TZ)).timestamp() * 1000)
    items = parse_ics(ics, from_ms=_from, to_ms=to_far, tz=TZ, role="events")
    starts = [fmt(i.start) for i in items]
    assert "2026-09-07 19:00" in starts
    assert "2026-09-14 19:00" not in starts
    assert "2026-09-21 18:00" in starts
    assert "2026-11-02 19:00" in starts
    moved_ms = int(datetime(2026, 9, 21, 18, 0, tzinfo=ZoneInfo(TZ)).timestamp() * 1000)
    moved = next((i for i in items if i.start == moved_ms), None)
    assert moved is not None and moved.title == "Fencing practice (moved)"


def test_floating_time_and_cancelled():
    ics = wrap("\r\n".join([
        "BEGIN:VEVENT", "UID:f1", "SUMMARY:Church", "DTSTART:20260927T090000", "DTEND:20260927T110000", "END:VEVENT",
        "BEGIN:VEVENT", "UID:c1", "SUMMARY:Cancelled thing", "STATUS:CANCELLED", "DTSTART:20260927T120000", "DTEND:20260927T130000", "END:VEVENT",
    ]))
    items = parse_ics(ics, from_ms=_from, to_ms=_to, tz=TZ, role="events")
    assert len(items) == 1
    assert fmt(items[0].start) == "2026-09-27 09:00"


def test_all_day_info_in_auto_feed():
    ics = wrap("BEGIN:VEVENT\r\nUID:h\r\nSUMMARY:No School - Yom Kippur\r\nDTSTART;VALUE=DATE:20260921\r\nEND:VEVENT")
    items = parse_ics(ics, from_ms=_from, to_ms=_to, tz=TZ, role="auto")
    assert items[0].kind == "info"

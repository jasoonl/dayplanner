"""ICS calendar parsing, replicating the quirks handled by
src/lib/integrations/ics.ts: Blackbaud all-day-as-midnight-datetime,
RRULE/EXDATE/RECURRENCE-ID expansion, VALUE=DATE all-day handling, floating
time treated as the user's timezone, and CANCELLED status filtering.

Recurrence expansion is delegated to the `recurring_ical_events` package
(built on `icalendar`), which mirrors what ical.js does in the original.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal, Optional
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events

FeedRole = Literal["events", "assignments", "auto"]

ASSIGNMENT_WORDS = re.compile(
    r"\b(test|quiz|exam|midterm|final|essay|paper|project|lab|homework|hw|reading|read|worksheet|"
    r"problem set|pset|assignment|due|presentation|draft|response|journal|practice log|study guide|review)\b",
    re.I,
)


@dataclass
class IcsItem:
    uid: str
    title: str
    start: int
    end: int
    allDay: bool
    kind: str
    date: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None


def classify(item: dict, role: FeedRole) -> str:
    if role == "assignments":
        return "assignment"
    canvas_assignment = bool(re.search(r"assignment", item.get("uid", ""), re.I)) or bool(
        re.search(r"/assignments/", item.get("url") or "", re.I)
    )
    if role == "events":
        return "info" if item["allDay"] else "event"
    if canvas_assignment:
        return "assignment"
    if item["allDay"]:
        return "assignment" if ASSIGNMENT_WORDS.search(item["title"]) else "info"
    return "event"


def split_course(raw: str) -> dict:
    canvas = re.match(r"^(.*)\s\[(.+)\]$", raw)
    if canvas:
        return {"title": canvas.group(1).strip(), "course": canvas.group(2).strip()}
    bb = re.match(r"^(.+?)\s-\s[\w.]+:\s(.+)$", raw)
    if bb:
        return {"title": bb.group(2).strip(), "course": bb.group(1).strip()}
    return {"title": raw.strip()}


def _iso_date(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _ms_of_date(d: date, tz: str) -> int:
    dt = datetime(d.year, d.month, d.day, tzinfo=ZoneInfo(tz))
    return int(dt.timestamp() * 1000)


def _ms_of_dt(dt: datetime, tz: str) -> int:
    """Convert an icalendar-produced datetime to epoch ms, honouring TZID/UTC
    and treating a floating (naive) datetime as the user's own timezone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz))
    return int(dt.timestamp() * 1000)


def _text(v) -> Optional[str]:
    if v is None:
        return None
    return str(v)


def parse_ics(text: str, from_ms: int, to_ms: int, tz: str, role: FeedRole) -> list[IcsItem]:
    cal = icalendar.Calendar.from_ical(text)

    window_start = datetime.fromtimestamp(from_ms / 1000, tz=ZoneInfo(tz)) - timedelta(days=1)
    window_end = datetime.fromtimestamp(to_ms / 1000, tz=ZoneInfo(tz)) + timedelta(days=1)

    try:
        occurrences = recurring_ical_events.of(cal, keep_recurrence_attributes=True).between(window_start, window_end)
    except Exception:
        occurrences = []

    out: list[IcsItem] = []
    for comp in occurrences:
        status = _text(comp.get("STATUS"))
        if status and status.upper() == "CANCELLED":
            continue

        dtstart_prop = comp.get("DTSTART")
        if dtstart_prop is None:
            continue
        dtstart = dtstart_prop.dt
        dtend_prop = comp.get("DTEND")
        dtend = dtend_prop.dt if dtend_prop is not None else dtstart

        is_date_only = not isinstance(dtstart, datetime) and isinstance(dtstart, date)
        if is_date_only:
            start = _ms_of_date(dtstart, tz)
            if isinstance(dtend, datetime):
                end = _ms_of_dt(dtend, tz)
            elif dtend != dtstart:
                end = _ms_of_date(dtend, tz)
            else:
                end = start + 86_400_000
            if end <= start:
                end = start + 86_400_000
            all_day = True
        else:
            start = _ms_of_dt(dtstart, tz)
            end = _ms_of_dt(dtend, tz) if dtend_prop is not None else start
            all_day = False

        # Blackbaud quirk: all-day items exported as midnight datetimes.
        if not all_day and role != "events":
            local = datetime.fromtimestamp(start / 1000, tz=ZoneInfo(tz))
            if local.hour == 0 and local.minute == 0 and (end - start == 0 or end - start >= 86_400_000 - 60_000):
                all_day = True
                end = start + 86_400_000

        if end < from_ms or start >= to_ms:
            continue
        if end < start:
            start, end = end, start

        uid = _text(comp.get("UID")) or ""
        title = (_text(comp.get("SUMMARY")) or "(untitled)").strip()
        url = _text(comp.get("URL"))
        location = _text(comp.get("LOCATION"))
        description = _text(comp.get("DESCRIPTION"))

        base = {"uid": uid, "title": title, "allDay": all_day, "url": url}
        kind = classify(base, role)

        occurrence_key = None
        rid = comp.get("RECURRENCE-ID")
        if rid is not None:
            occurrence_key = str(rid.dt)
        elif comp.get("RRULE") is not None:
            occurrence_key = str(dtstart)

        out.append(
            IcsItem(
                uid=f"{uid}@{occurrence_key}" if occurrence_key else uid,
                title=title,
                start=start,
                end=end,
                allDay=all_day,
                date=datetime.fromtimestamp(start / 1000, tz=ZoneInfo(tz)).strftime("%Y-%m-%d") if all_day else None,
                location=location.strip() if location else None,
                description=description[:500] if description else None,
                url=url,
                kind=kind,
            )
        )

    out.sort(key=lambda i: i.start)
    return out


def fetch_ics_sync(url: str) -> str:
    """Synchronous fetch helper (used by tests/scripts). The FastAPI routes use
    the async version in app/integrations/http.py."""
    import httpx

    u = re.sub(r"^webcals?://", "https://", url.strip(), flags=re.I)
    resp = httpx.get(
        u,
        headers={"User-Agent": "DayPlanner/1.0 (+calendar sync)", "Accept": "text/calendar, text/plain, */*"},
        timeout=15.0,
        follow_redirects=True,
    )
    resp.raise_for_status()
    text = resp.text
    if "BEGIN:VCALENDAR" not in text:
        raise ValueError("That link didn't return a calendar feed (no BEGIN:VCALENDAR).")
    return text

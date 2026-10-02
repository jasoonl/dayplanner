"""Timezone-safe date/time helpers mirroring src/lib/planner/time.ts.

Deliberately avoids naive datetime math: every wall-clock string is
interpreted through zoneinfo in the given timezone, and every instant is
represented as epoch milliseconds (int), matching the TS original.
"""
from __future__ import annotations

from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

MIN = 60_000  # one minute in milliseconds

_zone_cache: dict[str, ZoneInfo] = {}


def _zone(tz: str) -> ZoneInfo:
    z = _zone_cache.get(tz)
    if z is None:
        z = ZoneInfo(tz)
        _zone_cache[tz] = z
    return z


def _parse_date(date: str) -> _date:
    y, m, d = (int(x) for x in date.split("-"))
    return _date(y, m, d)


def at_time(date: str, hhmm: str, tz: str) -> int:
    h, m = (int(x) for x in hhmm.split(":"))
    d = _parse_date(date)
    dt = datetime(d.year, d.month, d.day, h, m, 0, 0, tzinfo=_zone(tz))
    return int(dt.timestamp() * 1000)


def start_of_day(date: str, tz: str) -> int:
    d = _parse_date(date)
    dt = datetime(d.year, d.month, d.day, 0, 0, 0, 0, tzinfo=_zone(tz))
    return int(dt.timestamp() * 1000)


def weekday_of(date: str, tz: str) -> int:
    """Luxon-style weekday: 1 = Monday ... 7 = Sunday."""
    d = _parse_date(date)
    dt = datetime(d.year, d.month, d.day, 12, 0, tzinfo=_zone(tz))
    return dt.isoweekday()


def add_days(date: str, n: int, tz: str) -> str:
    d = _parse_date(date)
    return (d + timedelta(days=n)).isoformat()


def date_of(ms: int, tz: str) -> str:
    dt = datetime.fromtimestamp(ms / 1000, tz=_zone(tz))
    return dt.date().isoformat()


def today_in(tz: str, now_ms: int | None = None) -> str:
    import time as _time

    now = now_ms if now_ms is not None else int(_time.time() * 1000)
    return date_of(now, tz)


def fmt_time(ms: int, tz: str) -> str:
    dt = datetime.fromtimestamp(ms / 1000, tz=_zone(tz))
    h12 = dt.strftime("%I:%M %p")
    if h12.startswith("0"):
        h12 = h12[1:]
    return h12


def minutes_of_day(ms: int, tz: str) -> int:
    dt = datetime.fromtimestamp(ms / 1000, tz=_zone(tz))
    return dt.hour * 60 + dt.minute


def ceil_to(ms: int, step_min: int = 5) -> int:
    step = step_min * MIN
    return -(-ms // step) * step


def floor_to(ms: int, step_min: int = 5) -> int:
    step = step_min * MIN
    return (ms // step) * step


def mins(ms: int) -> int:
    return round(ms / MIN)

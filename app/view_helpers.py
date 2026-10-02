"""Shared helpers for turning plan/task data into template-friendly dicts."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo


def fmt_hhmm_ampm(ms: int, tz: str) -> str:
    dt = datetime.fromtimestamp(ms / 1000, tz=ZoneInfo(tz))
    s = dt.strftime("%I:%M %p")
    return s[1:] if s.startswith("0") else s


def annotate_blocks(blocks: list[dict], tz: str, now_ms: Optional[int], done_blocks: list[str]) -> list[dict]:
    out = []
    for b in blocks:
        out.append({
            **b,
            "startFmt": fmt_hhmm_ampm(b["start"], tz),
            "endFmt": fmt_hhmm_ampm(b["end"], tz),
            "isPast": bool(now_ms) and b["end"] <= now_ms,
            "isCurrent": bool(now_ms) and b["start"] <= now_ms < b["end"],
            "isDone": b["id"] in done_blocks,
        })
    return out


def fmt_date_title(date: str, tz: str) -> dict:
    y, m, d = (int(x) for x in date.split("-"))
    dt = datetime(y, m, d, tzinfo=ZoneInfo(tz))
    return {"weekday": dt.strftime("%A"), "long": dt.strftime("%B %-d") if hasattr(dt, "strftime") else dt.isoformat()}

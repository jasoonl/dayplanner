"""Canvas LMS integration: ICS-feed based (via app.integrations.ics), plus an
optional Planner API bearer token for submission status. Mirrors
src/lib/integrations/canvas.ts."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

PLANNABLE_TYPES = {"assignment", "quiz", "discussion_topic", "planner_note", "wiki_page"}


@dataclass
class CanvasItem:
    uid: str
    title: str
    course: Optional[str]
    dueAt: Optional[int]
    url: Optional[str]
    submitted: bool
    type: str


async def fetch_canvas_planner(base_url: str, token: str, from_ms: int, to_ms: int) -> list[CanvasItem]:
    base = re.sub(r"/+$", "", base_url)
    base = re.sub(r"/api/v1$", "", base)
    out: list[CanvasItem] = []
    start_iso = datetime.fromtimestamp(from_ms / 1000, tz=timezone.utc).isoformat()
    end_iso = datetime.fromtimestamp(to_ms / 1000, tz=timezone.utc).isoformat()
    url: Optional[str] = f"{base}/api/v1/planner/items?per_page=100&start_date={start_iso}&end_date={end_iso}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        for _ in range(10):
            if not url:
                break
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code == 401:
                raise RuntimeError("Canvas rejected the token (it may be expired, or your school disabled tokens)")
            if resp.status_code >= 400:
                raise RuntimeError(f"Canvas API {resp.status_code}")
            items = resp.json()
            for it in items:
                if it.get("plannable_type") not in PLANNABLE_TYPES:
                    continue
                plannable = it.get("plannable") or {}
                due = plannable.get("due_at") or plannable.get("todo_date")
                sub = it.get("submissions") or {}
                override = it.get("planner_override") or {}
                out.append(CanvasItem(
                    uid=f"canvas-{it['plannable_type']}-{it['plannable_id']}",
                    title=plannable.get("title", "Untitled"),
                    course=it.get("context_name"),
                    dueAt=int(datetime.fromisoformat(due.replace("Z", "+00:00")).timestamp() * 1000) if due else None,
                    url=f"{base}{it['html_url']}" if it.get("html_url") else None,
                    submitted=bool(sub.get("submitted") or sub.get("graded") or sub.get("excused") or override.get("marked_complete")),
                    type=it["plannable_type"],
                ))
            link = resp.headers.get("link", "")
            m = re.search(r'<([^>]+)>;\s*rel="next"', link)
            url = m.group(1) if m else None
    return out

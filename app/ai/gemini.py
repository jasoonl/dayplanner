"""Gemini free-tier calls via plain httpx (generateContent + responseSchema),
with the deterministic rule-based fallback (app.ai.rules) used automatically
when GEMINI_API_KEY is unset, the call fails, or it's rate-limited.

Mirrors src/lib/ai/gemini.ts, minus the SDK dependency.
"""
from __future__ import annotations

import json
import os
from typing import Optional

import httpx

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")


def gemini_configured() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


async def _generate(prompt: str, response_schema: Optional[dict] = None) -> Optional[str]:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{DEFAULT_MODEL}:generateContent?key={key}"
    body: dict = {"contents": [{"parts": [{"text": prompt}]}]}
    if response_schema:
        body["generationConfig"] = {"responseMimeType": "application/json", "responseSchema": response_schema}
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(url, json=body)
        if resp.status_code >= 400:
            return None
        j = resp.json()
        parts = j["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    except Exception:  # noqa: BLE001
        return None


async def briefing(context: str) -> Optional[str]:
    """Short natural-language day briefing; None triggers the template fallback."""
    return await _generate(
        f"Write one short, warm, specific 2-3 sentence morning briefing for this day plan. "
        f"No greeting, no markdown, just prose.\n\n{context}"
    )


async def parse_checkin(text: str, today: str, tz: str) -> Optional[list[dict]]:
    """Structured extraction of check-in free text into task drafts; None triggers
    the deterministic app.ai.rules.parse_free_text fallback."""
    schema = {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {
                "title": {"type": "STRING"},
                "minutes": {"type": "INTEGER"},
                "priority": {"type": "INTEGER"},
                "due": {"type": "STRING"},
                "where": {"type": "STRING"},
                "category": {"type": "STRING"},
            },
        },
    }
    raw = await _generate(
        f"Today is {today} ({tz}). Split this free text into a JSON array of task drafts "
        f"(title, minutes, priority 1-4, due yyyy-mm-dd or null, where home/anywhere/portable, "
        f"category school/music/activity/personal/work):\n\n{text}",
        response_schema=schema,
    )
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return None

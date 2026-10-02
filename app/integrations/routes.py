"""Google Routes API (computeRoutes) lookup with a 14-day DB cache, mirroring
src/lib/integrations/routes.ts. Plain httpx calls (no heavy SDK) to stay
within Vercel's Python function size limits."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import httpx

from ..db import all_rows, now_ms, run
from ..planner.types import Place

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
TTL_MS = 14 * 24 * 3_600_000

_last_error: Optional[str] = None


def maps_last_error() -> Optional[str]:
    return _last_error


def maps_enabled() -> bool:
    return bool(os.environ.get("GOOGLE_MAPS_API_KEY"))


def bucket_of(arrive_by: int, tz: str) -> str:
    dt = datetime.fromtimestamp(arrive_by / 1000, tz=ZoneInfo(tz))
    weekend = "we" if dt.isoweekday() >= 6 else "wd"
    h = dt.hour
    band = "night" if h < 6 else "am" if h < 10 else "mid" if h < 15 else "pm" if h < 19 else "eve" if h < 23 else "night"
    return f"{weekend}-{band}"


def address_of(place_id: str, places: list[Place]) -> Optional[str]:
    if place_id.startswith("addr:"):
        return place_id[5:]
    return next((p.address for p in places if p.id == place_id), None)


def _cache_key(mode: str, frm: str, to: str, bucket: str) -> str:
    return f"{mode}|{frm.lower().strip()}|{to.lower().strip()}|{bucket}"


async def _compute_route(frm: str, to: str, mode: str, arrive_by: int) -> Optional[int]:
    global _last_error
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        return None
    body: dict = {"origin": {"address": frm}, "destination": {"address": to}, "travelMode": mode}
    now = now_ms()
    future = arrive_by > now + 5 * 60_000
    if mode == "TRANSIT" and future:
        body["arrivalTime"] = datetime.utcfromtimestamp(arrive_by / 1000).isoformat() + "Z"
    if mode == "DRIVE":
        body["routingPreference"] = "TRAFFIC_AWARE"
        dep = arrive_by - 45 * 60_000
        if dep > now + 5 * 60_000:
            body["departureTime"] = datetime.utcfromtimestamp(dep / 1000).isoformat() + "Z"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                ROUTES_URL, json=body,
                headers={"Content-Type": "application/json", "X-Goog-Api-Key": key,
                         "X-Goog-FieldMask": "routes.duration,routes.distanceMeters"},
            )
        if resp.status_code >= 400:
            _last_error = f"Routes API {resp.status_code}: {resp.text[:160]}"
            return None
        j = resp.json()
        routes = j.get("routes") or []
        d = routes[0].get("duration") if routes else None
        if not d:
            _last_error = f"No {mode.lower()} route found between “{frm}” and “{to}”"
            return None
        _last_error = None
        seconds = int(str(d).rstrip("s"))
        return max(1, -(-seconds // 60))
    except Exception as e:  # noqa: BLE001
        _last_error = f"Routes API failed: {e}"
        return None


@dataclass
class LegRequest:
    frm: str
    to: str
    arriveBy: int


async def build_travel_lookup(places: list[Place], mode: str, tz: str, fallback_min: int, legs: list[LegRequest], max_live: int = 16):
    table: dict[str, int] = {}
    wanted: dict[str, dict] = {}

    for leg in legs:
        if leg.frm == leg.to:
            continue
        a = address_of(leg.frm, places)
        b = address_of(leg.to, places)
        if not a or not b:
            continue
        key = _cache_key(mode, a, b, bucket_of(leg.arriveBy, tz))
        if key not in wanted:
            wanted[key] = {"from": a, "to": b, "arriveBy": leg.arriveBy, "key": key}

    keys = list(wanted.keys())
    if keys:
        placeholders = ",".join("?" for _ in keys)
        rows = await all_rows(f"SELECT key, minutes, fetched_at FROM travel_cache WHERE key IN ({placeholders})", keys)
        now = now_ms()
        for r in rows:
            if now - r["fetched_at"] < TTL_MS:
                table[r["key"]] = r["minutes"]

    misses = sorted((w for w in wanted.values() if w["key"] not in table), key=lambda w: w["arriveBy"])
    for w in misses[:max_live]:
        m = await _compute_route(w["from"], w["to"], mode, w["arriveBy"])
        if m is not None:
            table[w["key"]] = m
            await run("INSERT OR REPLACE INTO travel_cache (key, minutes, fetched_at) VALUES (?, ?, ?)", [w["key"], m, now_ms()])

    any_band: dict[str, int] = {}
    pair_rows = await all_rows("SELECT key, minutes FROM travel_cache WHERE key LIKE ?", [f"{mode}|%"])
    for r in pair_rows:
        pair = "|".join(r["key"].split("|")[:3])
        if pair not in any_band:
            any_band[pair] = r["minutes"]

    def lookup(from_id: str, to_id: str, arrive_by: int) -> int:
        if from_id == to_id:
            return 0
        a = address_of(from_id, places)
        b = address_of(to_id, places)
        if not a or not b:
            return fallback_min
        k = _cache_key(mode, a, b, bucket_of(arrive_by, tz))
        if k in table:
            return table[k]
        p1 = f"{mode}|{a.lower().strip()}|{b.lower().strip()}"
        p2 = f"{mode}|{b.lower().strip()}|{a.lower().strip()}"
        return any_band.get(p1) or any_band.get(p2) or fallback_min

    return lookup

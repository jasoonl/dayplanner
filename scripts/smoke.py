#!/usr/bin/env python3
"""Boots the app in demo mode and exercises the key pages + a couple of
htmx/API endpoints, asserting on status codes and key strings in the HTML.
Analogous to the original scripts/smoke.mjs.

Usage: python scripts/smoke.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("DEMO_MODE", "1")
os.environ.setdefault("DATABASE_URL", "file:data/smoke.db")
os.environ.setdefault("SESSION_SECRET", "smoke-test-secret-0123456789abcdef0123456789")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Start each run from a clean DB file so seeding is deterministic.
db_path = ROOT / "data" / "smoke.db"
if db_path.exists():
    db_path.unlink()

from starlette.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
failures: list[str] = []


def check(name: str, condition: bool) -> None:
    status = "OK" if condition else "FAIL"
    print(f"[{status}] {name}")
    if not condition:
        failures.append(name)


# --- Pages -------------------------------------------------------------
r = client.get("/")
check("GET / -> 200", r.status_code == 200)
check("GET / has Today", "Today" in r.text)
check("GET / has Schedule", "Schedule" in r.text)

r = client.get("/tasks")
check("GET /tasks -> 200", r.status_code == 200)
check("GET /tasks has Tasks heading", "Tasks" in r.text)

r = client.get("/week")
check("GET /week -> 200", r.status_code == 200)
check("GET /week has Week heading", "Week" in r.text)

r = client.get("/settings")
check("GET /settings -> 200", r.status_code == 200)
check("GET /settings has Settings heading", "Settings" in r.text)

r = client.get("/checkin")
check("GET /checkin -> 200", r.status_code == 200)
check("GET /checkin has morning check-in copy", "Morning check-in" in r.text)

r = client.get("/login")
check("GET /login -> 200", r.status_code == 200)

# --- htmx / API endpoints ------------------------------------------------
r = client.post("/checkin/parse", data={"text": "Unit 3 test Friday 2 hours"})
check("POST /checkin/parse -> 200", r.status_code == 200)
check("POST /checkin/parse rendered a draft title input", "draft_title" in r.text)

r = client.post("/plan/build", data={})
check("POST /plan/build -> 200", r.status_code == 200)
check("POST /plan/build re-renders schedule", "Schedule" in r.text)

r = client.post("/tasks", data={"title": "Smoke test task", "minutes": "30", "priority": "2", "where": "anywhere", "category": "personal"})
check("POST /tasks -> 200", r.status_code == 200)
check("POST /tasks shows the new task", "Smoke test task" in r.text)

r = client.get("/push/vapid-public-key")
check("GET /push/vapid-public-key -> 200", r.status_code == 200)

r = client.get("/api/cron/daily")
check("GET /api/cron/daily -> 200", r.status_code == 200)

print()
if failures:
    print(f"{len(failures)} check(s) failed:")
    for f in failures:
        print(f" - {f}")
    sys.exit(1)
print("All smoke checks passed.")

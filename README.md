# Day Planner (Python)

A deterministic, server-rendered day-planner: it turns your school/music/activity
calendar, open tasks and travel times into a single realistic schedule for
today, then re-plans as the day changes. This is a Python/FastAPI port of the
original Next.js/TypeScript app — same scheduling engine, same behavior,
server-rendered HTML + htmx instead of a React SPA.

## Stack

- **FastAPI** + **Jinja2** templates, **htmx** for partial-page interactivity
  (check-in, replan, task edits, block actions) — no client-side build step.
- **Planner engine** (`app/planner/`): pure, deterministic, dependency-free
  Python — no AI in the scheduling arithmetic. Ported line-for-line from the
  TypeScript original (`skeleton.py` → `allocate.py` → `place.py` → `index.py`).
- **Database**: `libsql-client` (async), which works against a local
  `file:./data/planner.db` (dev) or a remote Turso `libsql://...` URL
  (production) via the same `DATABASE_URL` / `DATABASE_AUTH_TOKEN` env vars.
- **Session**: JWT cookie via `PyJWT`.
- **Validation**: `pydantic` models (`app/schemas.py`).
- **ICS parsing**: `icalendar` + `recurring_ical_events`, replicating the
  Blackbaud all-day-as-midnight quirk, TZID/UTC/floating-time handling, and
  RRULE/EXDATE/RECURRENCE-ID expansion.
- **Google OAuth + Calendar, Routes (travel times), Canvas**: plain `httpx`
  REST calls (no heavy SDKs, to stay within Vercel's Python function size
  limits).
- **Gemini (free tier)**: plain `httpx` calls to `generateContent` with a
  JSON `responseSchema`; every call has a deterministic rule-based fallback
  (`app/ai/rules.py`) used automatically when no key is set or the call fails.
- **Web push**: `pywebpush` + VAPID keys (`scripts/vapid.py` generates them).
- **Demo mode**: with no Google/database keys, the app seeds and serves a
  realistic sample week (Dalton 8:10–3:30, fencing Mon/Wed/Fri, violin
  Tuesday, MSM + Columbia SHP Saturday, church Sunday) so it works out of the
  box.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000 — with no `GOOGLE_CLIENT_ID`/`DATABASE_URL` set,
it runs entirely in demo mode against a local SQLite file
(`data/planner.db`), no external services required.

## Tests

```bash
pytest                 # 27 tests: 19 planner + 5 ICS + 3 rule-engine, ported
                        # 1:1 from tests/planner.test.ts, ics.test.ts, rules.test.ts
python scripts/smoke.py  # boots the app in demo mode and exercises the main routes
```

## Project layout

```
app/
  planner/        pure scheduling engine (types, time, skeleton, allocate, place, index)
  ai/              rules.py (deterministic fallback), gemini.py (httpx + fallback)
  integrations/    ics.py, google.py, routes.py (travel cache), canvas.py
  routers/         FastAPI routes: pages, checkin, blocks, tasks, settings, sources, auth, push, cron
  db.py            libsql-client wrapper + schema
  repo.py          data access / settings
  seed.py          demo-mode sample data
  session.py       JWT cookie session
  plan_service.py  build/cache plan, briefing, publish to Google Calendar
  sync.py          pull events/assignments from ICS/Google/Canvas
templates/         Jinja2 pages + htmx partials
static/            CSS (ported design system), manifest, service worker
tests/             pytest port of the original vitest suite
scripts/           vapid.py (VAPID keygen), smoke.py
api/index.py       Vercel Python entrypoint (ASGI `app`)
vercel.json        rewrites everything to api/index, + daily cron
```

See `SETUP.md` for environment variables and deployment.

# Setup

## 1. Local development (zero keys)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # optional — defaults work with no keys at all
uvicorn app.main:app --reload
```

Visit http://localhost:8000. With no `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`,
the app is in demo mode: it seeds a realistic sample week into
`data/planner.db` (a local SQLite file via libsql) and logs you in as the demo
user automatically.

## 2. Database (Turso)

The same `libsql-client` works locally (SQLite file) and against a hosted
[Turso](https://turso.tech) database in production — no code changes.

```bash
turso db create day-planner
turso db show day-planner --url          # -> DATABASE_URL
turso db tokens create day-planner       # -> DATABASE_AUTH_TOKEN
```

Set both in your environment (or Vercel project settings). The schema is
created automatically on first connection.

## 3. Google OAuth + Calendar

1. In Google Cloud Console, create an OAuth 2.0 Client ID (Web application).
2. Authorized redirect URI: `https://<your-domain>/api/auth/google/callback`
   (or `http://localhost:8000/api/auth/google/callback` for local dev).
3. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `APP_URL`.
4. Once connected, the app creates a secondary "Day Planner" calendar
   (`calendar.app.created` scope) and writes planned blocks into it.

## 4. Google Routes API (travel times)

Enable the Routes API and set `GOOGLE_MAPS_API_KEY`. Without it, the app
falls back to a flat `defaultTravelMin` (configurable in Settings) plus
whatever demo/cached travel times already exist.

## 5. Gemini (optional, free tier)

Set `GEMINI_API_KEY` (and optionally `GEMINI_MODEL`, default
`gemini-3.5-flash-lite`). Without a key, or if a call fails/rate-limits, the
app automatically falls back to the deterministic rule engine
(`app/ai/rules.py`) for both check-in parsing and estimate guessing — the
scheduling math itself never depends on AI either way.

## 6. Web push

```bash
python scripts/vapid.py
```

Copy the printed `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT`
into your environment.

## 7. Deploying to Vercel

This repo is structured for Vercel's Python runtime:

- `api/index.py` exposes the FastAPI `app` as a single ASGI function.
- `vercel.json` rewrites every route to it, plus a `functions.maxDuration`
  and a daily cron hitting `GET /api/cron/daily`.

```bash
vercel link
vercel env add DATABASE_URL
vercel env add DATABASE_AUTH_TOKEN
vercel env add SESSION_SECRET
vercel env add GOOGLE_CLIENT_ID
vercel env add GOOGLE_CLIENT_SECRET
vercel env add GOOGLE_MAPS_API_KEY
vercel env add GEMINI_API_KEY
vercel env add VAPID_PUBLIC_KEY
vercel env add VAPID_PRIVATE_KEY
vercel env add CRON_SECRET
vercel deploy --prod
```

Project settings: Framework Preset "Other", no build command needed —
Vercel's Python runtime installs `requirements.txt` automatically and runs
`api/index.py` as a serverless function per the `rewrites` in `vercel.json`.

## 8. Tests

```bash
pytest
python scripts/smoke.py
```

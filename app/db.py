"""Async libsql client wrapper, mirroring src/lib/db.ts. Works transparently
against a local file:./data/planner.db URL (dev) or a remote libsql://...
Turso URL (production) via the same DATABASE_URL / DATABASE_AUTH_TOKEN env
vars as the original .env.example.
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import libsql_client

SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE,
        name TEXT,
        settings_json TEXT NOT NULL,
        google_json TEXT,
        planner_calendar_id TEXT,
        data_version INTEGER NOT NULL DEFAULT 1,
        last_sync_at INTEGER,
        created_at INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS sources (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        label TEXT NOT NULL,
        url TEXT,
        role TEXT NOT NULL DEFAULT 'auto',
        category TEXT NOT NULL DEFAULT 'school',
        default_place_id TEXT,
        token TEXT,
        meta_json TEXT,
        enabled INTEGER NOT NULL DEFAULT 1,
        last_sync_at INTEGER,
        last_error TEXT,
        item_count INTEGER
    )""",
    """CREATE TABLE IF NOT EXISTS places (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        name TEXT NOT NULL,
        address TEXT NOT NULL,
        aliases_json TEXT NOT NULL DEFAULT '[]',
        is_home INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        title TEXT NOT NULL,
        start INTEGER NOT NULL,
        end INTEGER NOT NULL,
        all_day INTEGER NOT NULL DEFAULT 0,
        location TEXT,
        place_id TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS events_user_time ON events(user_id, start)",
    """CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        source_id TEXT,
        external_uid TEXT,
        title TEXT NOT NULL,
        course TEXT,
        category TEXT NOT NULL,
        source_label TEXT,
        due_at INTEGER,
        due_all_day INTEGER NOT NULL DEFAULT 0,
        estimate_min INTEGER NOT NULL,
        estimate_source TEXT NOT NULL DEFAULT 'rule',
        spent_min INTEGER NOT NULL DEFAULT 0,
        priority INTEGER NOT NULL DEFAULT 2,
        where_ TEXT NOT NULL DEFAULT 'anywhere',
        splittable INTEGER NOT NULL DEFAULT 1,
        done INTEGER NOT NULL DEFAULT 0,
        done_at INTEGER,
        not_before INTEGER,
        url TEXT,
        notes TEXT,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS tasks_ext ON tasks(user_id, source_id, external_uid)",
    """CREATE TABLE IF NOT EXISTS routines (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        minutes INTEGER NOT NULL,
        days_json TEXT NOT NULL,
        where_ TEXT NOT NULL DEFAULT 'home',
        category TEXT NOT NULL DEFAULT 'routine',
        priority INTEGER NOT NULL DEFAULT 3,
        window_start TEXT,
        window_end TEXT,
        active INTEGER NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE IF NOT EXISTS day_state (
        user_id TEXT NOT NULL,
        date TEXT NOT NULL,
        checkin_done INTEGER NOT NULL DEFAULT 0,
        energy TEXT,
        skipped_json TEXT NOT NULL DEFAULT '[]',
        plan_json TEXT,
        plan_version INTEGER,
        briefing TEXT,
        published_json TEXT,
        done_blocks_json TEXT NOT NULL DEFAULT '[]',
        PRIMARY KEY (user_id, date)
    )""",
    """CREATE TABLE IF NOT EXISTS work_log (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        task_id TEXT,
        routine_id TEXT,
        category TEXT,
        start INTEGER NOT NULL,
        minutes INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS travel_cache (
        key TEXT PRIMARY KEY,
        minutes INTEGER NOT NULL,
        fetched_at INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS ai_cache (
        key TEXT PRIMARY KEY,
        json TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS push_subs (
        endpoint TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        json TEXT NOT NULL
    )""",
]

_client: Optional[libsql_client.Client] = None
_ready = False


def _make_client() -> libsql_client.Client:
    url = os.environ.get("DATABASE_URL", "file:data/planner.db")
    if url.startswith("file:"):
        p = Path(url[5:])
        p.parent.mkdir(parents=True, exist_ok=True)
    return libsql_client.create_client(url, auth_token=os.environ.get("DATABASE_AUTH_TOKEN") or None)


async def db() -> libsql_client.Client:
    global _client, _ready
    if _client is None:
        _client = _make_client()
    if not _ready:
        for stmt in SCHEMA_STATEMENTS:
            await _client.execute(stmt)
        _ready = True
    return _client


async def reset_client() -> None:
    """Used by tests/smoke to force a fresh connection against a temp DB."""
    global _client, _ready
    if _client is not None:
        try:
            await _client.close()
        except Exception:
            pass
    _client = None
    _ready = False


async def all_rows(sql: str, args: Optional[list[Any]] = None) -> list[dict]:
    c = await db()
    rs = await c.execute(sql, args or [])
    cols = rs.columns
    return [dict(zip(cols, row)) for row in rs.rows]


async def one_row(sql: str, args: Optional[list[Any]] = None) -> Optional[dict]:
    rows = await all_rows(sql, args)
    return rows[0] if rows else None


async def run(sql: str, args: Optional[list[Any]] = None) -> None:
    c = await db()
    await c.execute(sql, args or [])


async def batch(stmts: list[tuple[str, list[Any]]]) -> None:
    if not stmts:
        return
    c = await db()
    await c.batch([libsql_client.Statement(sql, args) for sql, args in stmts])


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:16]}"


async def bump_version(user_id: str) -> None:
    await run("UPDATE users SET data_version = data_version + 1 WHERE id = ?", [user_id])


def now_ms() -> int:
    return int(time.time() * 1000)

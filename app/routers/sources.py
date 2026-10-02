from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..db import bump_version, new_id, run
from ..integrations.ics import fetch_ics_sync, parse_ics
from ..main import render, templates
from ..repo import list_sources
from ..session import current_user_id

router = APIRouter()


async def _render_sources(request: Request, uid: str) -> HTMLResponse:
    sources = await list_sources(uid)
    return render("partials/sources_list.html", {"request": request, "sources": sources})


@router.post("/sources", response_class=HTMLResponse)
async def sources_create(
    request: Request, kind: str = Form(...), label: str = Form(...), url: str = Form(None),
    role: str = Form("auto"), category: str = Form("school"), token: str = Form(None),
):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    await run(
        "INSERT INTO sources (id, user_id, kind, label, url, role, category, token, enabled) VALUES (?,?,?,?,?,?,?,?,1)",
        [new_id("src_"), uid, kind, label, url or None, role, category, token or None],
    )
    await bump_version(uid)
    return await _render_sources(request, uid)


@router.post("/sources/{source_id}/delete", response_class=HTMLResponse)
async def sources_delete(request: Request, source_id: str):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    await run("DELETE FROM sources WHERE id = ? AND user_id = ?", [source_id, uid])
    await run("DELETE FROM events WHERE user_id = ? AND source_id = ?", [uid, source_id])
    await bump_version(uid)
    return await _render_sources(request, uid)


@router.post("/sources/test", response_class=HTMLResponse)
async def sources_test(request: Request, url: str = Form(...)):
    uid = await current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    try:
        text = fetch_ics_sync(url)
        import time
        now = int(time.time() * 1000)
        items = parse_ics(text, from_ms=now - 86_400_000, to_ms=now + 30 * 86_400_000, tz="UTC", role="auto")
        message = f"Looks good — found {len(items)} item(s) in the next 30 days."
        ok = True
    except Exception as e:  # noqa: BLE001
        message = f"Couldn't read that feed: {e}"
        ok = False
    return render("partials/toast.html", {"request": request, "message": message, "ok": ok})

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def render(name: str, context: dict):
    """TemplateResponse helper matching this Starlette version's
    request-first signature, while callers keep passing context["request"]."""
    return templates.TemplateResponse(context["request"], name, context)


def create_app() -> FastAPI:
    app = FastAPI(title="Day Planner")

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    from .routers import auth, blocks, checkin, cron, pages, push_api, settings_router, sources, tasks_router

    app.include_router(pages.router)
    app.include_router(auth.router)
    app.include_router(checkin.router)
    app.include_router(blocks.router)
    app.include_router(tasks_router.router)
    app.include_router(settings_router.router)
    app.include_router(sources.router)
    app.include_router(push_api.router)
    app.include_router(cron.router)

    return app


app = create_app()

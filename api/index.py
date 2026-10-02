"""Vercel Python runtime entrypoint: a single ASGI app, as vercel.json rewrites
every route to this function."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402

__all__ = ["app"]

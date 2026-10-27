"""FastAPI app: wires the three lanes' routers and serves the pages. Lanes don't edit this file."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from app.api import core, dashboards, onboard, venues  # noqa: E402  (after .env is loaded)

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="TimeWeave")
# signed session cookie = who is signed in (set TIMEWEAVE_SECRET in production)
# public demo without TIMEWEAVE_SECRET: a random secret (sign-ins end when the server restarts, which is fine)
_secret = os.getenv("TIMEWEAVE_SECRET") or (secrets.token_hex(32) if core.HOSTED else "timeweave-dev-secret-change-me")
app.add_middleware(SessionMiddleware, secret_key=_secret,
                   session_cookie="tw_session", same_site="lax", max_age=7 * 24 * 3600)
app.include_router(core.auth_router)  # Lane A: /api/auth/... (sign-in, no session needed)
app.include_router(core.router)  # Lane A: /api/...
app.include_router(dashboards.router)  # Lane B: /api/dash/...
app.include_router(venues.router)  # Lane C: /api/venues/...
app.include_router(onboard.router)  # Lane A: /api/onboard/... (another college, from Excel; no sign-in, nothing kept)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")  # Lane B's page (timetable + dashboards)


@app.get("/venues.html")
def venues_page() -> FileResponse:
    return FileResponse(STATIC / "venues.html")  # Lane C's page (venues + events)


@app.get("/login.html")
def login_page() -> FileResponse:
    return FileResponse(STATIC / "login.html")  # Lane A: sign-in


@app.get("/audit.html")
def audit_page() -> FileResponse:
    return FileResponse(STATIC / "audit.html")  # Lane A: audit log (admin, Dean)


@app.get("/concerns.html")
def concerns_page() -> FileResponse:
    return FileResponse(STATIC / "concerns.html")  # Lane A: students' timetable concerns


@app.get("/onboard.html")
def onboard_page() -> FileResponse:
    return FileResponse(STATIC / "onboard.html")  # Lane A: set up another college from Excel


@app.get("/favicon.ico")
def favicon() -> Response:
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#4f46e5"/>'
           '<text x="16" y="21" font-family="sans-serif" font-size="13" font-weight="700" fill="#fff" text-anchor="middle">TW</text></svg>')
    return Response(svg, media_type="image/svg+xml")


@app.get("/compare.html")
def compare_page() -> FileResponse:
    return FileResponse(STATIC / "compare.html")  # Lane A: published vs optimised CSE timetable

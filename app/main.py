"""FastAPI app: wires the three lanes' routers and serves the pages. Lanes don't edit this file."""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from app.api import core, dashboards, venues  # noqa: E402  (after .env is loaded)

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="TimeWeave")
app.include_router(core.router)  # Lane A: /api/...
app.include_router(dashboards.router)  # Lane B: /api/dash/...
app.include_router(venues.router)  # Lane C: /api/venues/...
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")  # Lane B's page (timetable + dashboards)


@app.get("/venues.html")
def venues_page() -> FileResponse:
    return FileResponse(STATIC / "venues.html")  # Lane C's page (venues + events)


@app.get("/compare.html")
def compare_page() -> FileResponse:
    return FileResponse(STATIC / "compare.html")  # Lane A: published vs optimised CSE timetable

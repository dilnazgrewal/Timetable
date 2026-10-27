"""Onboarding another college from its Excel workbook, on the website (Lane A).

Separate from GNDEC's data: nothing here reads or writes STORE, and nothing is kept on the server. A visiting
college has no account here yet, so these endpoints need no sign-in; they are bounded instead (file size, size of
the college, one generation at a time, a short time limit).
    GET  /api/onboard/template    the blank workbook (one example row per sheet)
    GET  /api/onboard/sample      a filled-in, made-up sample college
    POST /api/onboard/check       body = the .xlsx file: problems by sheet and row, or what was found
    POST /api/onboard/generate    body = the .xlsx file: a timetable, checked by the independent validator
"""
from __future__ import annotations

import base64
import io
import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from app.auth import HOSTED
from app.importers import sheets
from app.models import DAYS

router = APIRouter(prefix="/api/onboard", tags=["onboard"])

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "colleges" / "demo_institute" / "demo_institute.xlsx"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_BYTES = 2_000_000
MAX_SESSIONS = 600  # weekly sessions: a few departments; a whole college goes in through the command line for now
_busy = threading.Lock()


def _read(body: bytes):
    if not body:
        raise HTTPException(400, "Please choose your filled-in Excel workbook (.xlsx).")
    if len(body) > MAX_BYTES:
        raise HTTPException(413, "That file is larger than 2 MB. Is it the TimeWeave template?")
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        f.write(body)
        path = Path(f.name)
    try:
        wb, errors = sheets.read_workbook(path)
    except Exception:
        raise HTTPException(400, "This doesn't open as an Excel workbook (.xlsx). Start from the template.")
    finally:
        path.unlink(missing_ok=True)
    college, profile, more = sheets.build_college(wb) if not errors else (None, {}, [])
    return college, profile, errors + more


def _summary(college, profile) -> dict:
    return {"college": str(profile.get("college") or "Your college"), "departments": len(college.departments),
            "rooms": len(college.rooms), "teachers": len(college.teachers), "sections": len(college.sections),
            "lessons": len(college.lessons), "sessions": sum(l.sessions for l in college.lessons),
            "periods": profile["period_times"]}


@router.get("/template")
def template() -> Response:
    buf = io.BytesIO()
    sheets.write_workbook(buf, sheets.HELP)
    return Response(buf.getvalue(), media_type=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="timeweave_college_template.xlsx"'})


@router.get("/sample")
def sample() -> FileResponse:
    return FileResponse(SAMPLE, media_type=XLSX, filename="sample_college.xlsx")


@router.post("/check")
async def check(request: Request) -> dict:
    college, profile, problems = _read(await request.body())
    if problems:
        return {"ok": False, "problems": problems}
    return {"ok": True, "problems": [], "summary": _summary(college, profile)}


@router.post("/generate")
async def generate(request: Request) -> dict:
    from starlette.concurrency import run_in_threadpool

    college, profile, problems = _read(await request.body())
    if problems:
        return {"ok": False, "problems": problems}
    if sum(l.sessions for l in college.lessons) > MAX_SESSIONS:
        raise HTTPException(413, f"More than {MAX_SESSIONS} classes a week: on this demo server, set up a few "
                                 "departments at a time.")
    if not _busy.acquire(blocking=False):
        raise HTTPException(429, "Another college's timetable is being made right now. Please try again in a minute.")
    try:
        return await run_in_threadpool(_generate, college, profile)
    finally:
        _busy.release()


def _generate(college, profile) -> dict:
    from app.solver import solve
    from app.validator import metrics, split_issues, validate

    res = solve(college, time_limit=15 if HOSTED else 20, workers=2 if HOSTED else 8)
    if not res.entries:
        return {"ok": False, "problems": res.problems or ["No timetable fits these classes, teachers and rooms."]}
    clashes, _ = split_issues(validate(college, res.entries))
    m = metrics(college, res.entries)
    periods = profile["period_times"]
    grids = []
    for s in college.sections:
        g = sheets.section_grid(college, res.entries, s)
        grids.append({"id": s.id, "rows": [[g.get((d, p), []) for d in range(len(DAYS))] for p in range(len(periods))]})
    buf = io.BytesIO()
    sheets.write_timetable(buf, college, res.entries, periods)
    return {"ok": True, "summary": _summary(college, profile), "seconds": round(res.seconds, 1),
            "clashes": [str(c) for c in clashes][:20], "idle_per_day": m["idle_per_day"], "lonely_days": m["lonely_days"],
            "days": DAYS, "sections": grids, "file": base64.b64encode(buf.getvalue()).decode()}

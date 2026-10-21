"""FastAPI app: serves the single-page UI and a small JSON API over the in-memory college."""
from __future__ import annotations

import json
import threading
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.models import DAYS, LUNCH, LUNCH_AFTER, PERIODS, Entry
from app.seed import build_college
from app.solver import solve
from app.validator import metrics, validate

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "solution.json"
STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="TimeWeave")
COLLEGE = build_college()
STATE: dict = {"result": None}
_solve_lock = threading.Lock()


def _publish(raw: dict) -> dict:
    """Re-validate with the independent checker every time a timetable is loaded or generated."""
    entries = [Entry(**e) for e in raw["entries"]]
    raw["issues"] = validate(COLLEGE, entries)
    raw["metrics"] = metrics(COLLEGE, entries)
    STATE["result"] = raw
    STATE["entries"] = entries
    return raw


if CACHE.exists():
    try:
        _publish(json.loads(CACHE.read_text()))
    except Exception:  # a broken cache must never stop the demo
        STATE["result"] = None


def _entry_view(e: Entry) -> dict:
    l = COLLEGE.lesson_by_id[e.lesson]
    t = COLLEGE.teacher_by_id[l.teacher]
    return {**asdict(e), "code": l.code, "name": l.name, "kind": l.kind, "dept": l.dept,
            "teacher": t.id, "teacher_name": t.name, "section": l.section, "batches": l.batches,
            "section_id": l.batches[0].rsplit("-", 1)[0]}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/meta")
def meta() -> dict:
    return {
        "days": DAYS,
        "periods": [{"label": p, "start": s, "end": e} for p, s, e in PERIODS],
        "lunch": {"after": LUNCH_AFTER, "start": LUNCH[0], "end": LUNCH[1]},
        "departments": [asdict(d) for d in COLLEGE.departments],
        "sections": [{**asdict(s), "batches": s.batches} for s in COLLEGE.sections],
        "teachers": [asdict(t) for t in COLLEGE.teachers],
        "rooms": [asdict(r) for r in COLLEGE.rooms],
        "counts": {"sections": len(COLLEGE.sections), "teachers": len(COLLEGE.teachers),
                   "rooms": len(COLLEGE.rooms), "lessons": len(COLLEGE.lessons),
                   "sessions": sum(l.sessions for l in COLLEGE.lessons)},
    }


@app.get("/api/timetable")
def timetable() -> dict:
    r = STATE["result"]
    if not r:
        return {"ready": False}
    return {"ready": True, "status": r["status"], "seconds": r["seconds"], "issues": r["issues"],
            "metrics": r["metrics"], "baseline": r.get("baseline"), "problems": r.get("problems", []),
            "entries": [_entry_view(e) for e in STATE["entries"]]}


@app.post("/api/generate")
def generate(time_limit: float = 30) -> dict:
    if not _solve_lock.acquire(blocking=False):
        raise HTTPException(409, "A timetable is already being generated.")
    try:
        base = solve(COLLEGE, optimize=False, time_limit=15)
        res = solve(COLLEGE, time_limit=time_limit)
        if not res.entries:
            return {"ok": False, "status": res.status, "problems": res.problems}
        raw = {"status": res.status, "seconds": res.seconds, "objective": res.objective,
               "entries": [asdict(e) for e in res.entries],
               "baseline": metrics(COLLEGE, base.entries) if base.entries else None}
        if raw["baseline"]:
            raw["baseline"].pop("teacher_load", None)
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(raw))
        _publish(raw)
        return {"ok": True, "status": res.status}
    finally:
        _solve_lock.release()


@app.get("/api/free-rooms")
def free_rooms(day: int, period: int, min_capacity: int = 0, kind: str = "") -> dict:
    if not (0 <= day < len(DAYS) and 0 <= period < len(PERIODS)):
        raise HTTPException(400, "Invalid day or period")
    busy: dict[str, str] = {}
    for e in STATE.get("entries") or []:
        if e.day == day and period in e.slots:
            l = COLLEGE.lesson_by_id[e.lesson]
            busy[e.room] = f"{l.code} · {l.section}"
    # when is each free room next needed today?
    rooms = []
    for r in COLLEGE.rooms:
        if r.id in busy or r.capacity < min_capacity or (kind and r.kind != kind):
            continue
        next_use = min((e.start for e in STATE.get("entries") or []
                        if e.room == r.id and e.day == day and e.start > period), default=None)
        rooms.append({**asdict(r), "free_until": PERIODS[next_use][1] if next_use is not None else "16:30"})
    rooms.sort(key=lambda r: (r["kind"] != "Classroom", r["id"]))
    return {"day": DAYS[day], "period": PERIODS[period][0], "free": rooms, "busy_count": len(busy)}

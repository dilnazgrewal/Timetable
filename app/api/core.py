"""Lane A (Core and data): timetable, generation, free rooms, accounts, notifications, chat."""
from __future__ import annotations

import os
import threading
from dataclasses import asdict
from datetime import date

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import current_user, require
from app.chat import Assistant
from app.models import DAYS, FEATURES, LUNCH_WINDOW, PERIODS, Entry, User
from app.solver import solve
from app.store import STORE, Occupancy
from app.validator import metrics

router = APIRouter(prefix="/api", tags=["core"])
_solve_lock = threading.Lock()


def entry_view(e: Entry) -> dict:
    c = STORE.college
    l = c.lesson_by_id[e.lesson]
    t = c.teacher_by_id[l.teacher]
    return {**asdict(e), "code": l.code, "name": l.name, "kind": l.kind, "dept": l.dept,
            "teacher": t.id, "teacher_name": t.name, "section": l.section, "batches": l.batches,
            "section_id": l.batches[0].rsplit("-", 1)[0]}


def occupancy_view(o: Occupancy) -> dict:
    c = STORE.college
    l = c.lesson_by_id.get(o.lesson or "")
    t = c.teacher_by_id.get(o.teacher or "")
    return {**asdict(o), "code": l.code if l else "", "name": l.name if l else o.title,
            "section": l.section if l else "", "teacher_name": t.name if t else ""}


def user_view(u: User) -> dict:
    return asdict(u)


@router.get("/meta")
def meta() -> dict:
    c = STORE.college
    return {
        "days": DAYS,
        "periods": [{"label": p, "start": s, "end": e} for p, s, e in PERIODS],
        "lunch": {"window": list(LUNCH_WINDOW), "start": PERIODS[LUNCH_WINDOW[0]][1],
                  "end": PERIODS[LUNCH_WINDOW[-1]][2]},
        "departments": [asdict(d) for d in c.departments],
        "buildings": [asdict(b) for b in c.buildings],
        "features": list(FEATURES),
        "sections": [{**asdict(s), "batches": s.batches} for s in c.sections],
        "teachers": [asdict(t) for t in c.teachers],
        "rooms": [asdict(r) for r in c.rooms],
        "counts": {"sections": len(c.sections), "teachers": len(c.teachers), "rooms": len(c.rooms),
                   "lessons": len(c.lessons), "sessions": sum(l.sessions for l in c.lessons)},
    }


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return user_view(user)


@router.get("/users")
def users() -> dict:
    """Demo accounts for the account switcher, grouped by role."""
    groups: dict[str, list[dict]] = {}
    for u in STORE.users.values():
        groups.setdefault(u.role, []).append({"id": u.id, "name": u.name, "dept": u.dept})
    return {"roles": groups, "clubs": [asdict(c) for c in STORE.clubs.values()]}


@router.get("/timetable")
def timetable() -> dict:
    r = STORE.result
    if not r:
        return {"ready": False}
    return {"ready": True, "status": r["status"], "seconds": r["seconds"], "issues": r["issues"],
            "notes": r.get("notes", []), "source": r.get("source", ""), "compare": r.get("compare"),
            "metrics": r["metrics"], "baseline": r.get("baseline"), "problems": r.get("problems", []),
            "entries": [entry_view(e) for e in STORE.entries]}


@router.get("/effective")
def effective(on: str) -> dict:
    """Everything happening on a real date (classes after substitutions/cancellations, plus bookings)."""
    try:
        d = date.fromisoformat(on)
    except ValueError:
        raise HTTPException(400, "Use a date like 2026-10-23")
    return {"date": d.isoformat(), "weekday": d.weekday(),
            "items": [occupancy_view(o) for o in STORE.effective(d)]}


@router.post("/generate")
def generate(time_limit: float = 30, user: User = Depends(current_user)) -> dict:
    require(user, "timetable.generate")
    if not _solve_lock.acquire(blocking=False):
        raise HTTPException(409, "A timetable is already being generated.")
    try:
        c = STORE.college
        base = solve(c, optimize=False, time_limit=15)
        res = solve(c, time_limit=time_limit)
        if not res.entries:
            return {"ok": False, "status": res.status, "problems": res.problems}
        raw = {"status": res.status, "seconds": res.seconds, "objective": res.objective,
               "entries": [asdict(e) for e in res.entries],
               "baseline": metrics(c, base.entries, fixed=False) if base.entries else None,
               "source": "Real CSE timetable (GNDEC, imported from FET) + generated departments"}
        if raw["baseline"]:
            raw["baseline"].pop("teacher_load", None)
        STORE.save_solution(raw)
        return {"ok": True, "status": res.status}
    finally:
        _solve_lock.release()


@router.get("/free-rooms")
def free_rooms(period: int, day: int | None = None, on: str | None = None, min_capacity: int = 0,
               kind: str = "", sittable_only: bool = False, building: str = "", floor: str = "") -> dict:
    """Free rooms for a weekday template (`day`) or a real date (`on`, includes bookings/cancellations)."""
    if not 0 <= period < len(PERIODS):
        raise HTTPException(400, "Invalid period")
    if on:
        occ, label = STORE.effective(on), on
        wd = date.fromisoformat(on).weekday()
    else:
        if day is None or not 0 <= day < len(DAYS):
            raise HTTPException(400, "Give `day` (0-4) or `on` (YYYY-MM-DD)")
        occ, wd, label = [o for o in STORE.week() if o.day == day], day, DAYS[day]
    busy = STORE.busy_rooms(occ, period)
    rooms = []
    for r in STORE.college.rooms:
        if (r.id in busy or r.capacity < min_capacity or (kind and r.kind != kind) or (sittable_only and not r.sittable)
                or (building and r.building != building) or (floor and r.floor != floor)):
            continue
        next_use = min((o.start for o in occ if o.room == r.id and o.start > period), default=None)
        rooms.append({**asdict(r), "free_until": PERIODS[next_use][1] if next_use is not None else PERIODS[-1][2]})
    def floor_rank(r: dict) -> int:
        b = STORE.college.building_by_id.get(r["building"])
        return b.floors.index(r["floor"]) if b and r["floor"] in b.floors else 99

    rooms.sort(key=lambda r: (r["building"], floor_rank(r), r["kind"] != "Classroom", r["id"]))
    return {"day": DAYS[wd] if wd < len(DAYS) else "", "date": on, "label": label, "period": PERIODS[period][0],
            "free": rooms, "busy_count": len(busy)}


@router.get("/notifications")
def notifications(user: User = Depends(current_user)) -> dict:
    mine = [asdict(n) for n in STORE.notifications if n.user == user.id]
    return {"items": mine[::-1], "unread": sum(not n["read"] for n in mine)}


@router.post("/notifications/read")
def notifications_read(user: User = Depends(current_user)) -> dict:
    with STORE.lock:
        for n in STORE.notifications:
            if n.user == user.id:
                n.read = True
        STORE.save()
    return {"ok": True}


@router.post("/demo/reset")
def demo_reset(user: User = Depends(current_user)) -> dict:
    require(user, "demo.reset")  # admin only
    STORE.reset_state()
    return {"ok": True}


ASSISTANT = Assistant(STORE.college, lambda: STORE.entries)


class ChatRequest(BaseModel):
    messages: list[dict]


@router.post("/chat")
def chat(req: ChatRequest) -> dict:
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        return {"answer": "The assistant isn't configured: add ANTHROPIC_API_KEY to the .env file.", "tools_used": []}
    try:
        return ASSISTANT.ask(req.messages)
    except anthropic.AuthenticationError:
        return {"answer": "The assistant isn't configured: add ANTHROPIC_API_KEY to the .env file.", "tools_used": []}
    except anthropic.APIConnectionError:
        return {"answer": "I can't reach the AI service right now. The timetable and room finder still work.",
                "tools_used": []}
    except anthropic.APIStatusError as e:
        return {"answer": f"The AI service returned an error ({e.status_code}). Please try again.", "tools_used": []}
    except anthropic.AnthropicError:  # e.g. no credentials configured at all
        return {"answer": "The assistant isn't configured: add ANTHROPIC_API_KEY to the .env file.", "tools_used": []}

"""Lane A (Core and data): timetable, generation, free rooms, accounts, notifications, chat."""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict
from datetime import date

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth import DEMO_MODE, ROLES, authorize, capabilities, current_user, require
from app.chat import Assistant
from app.models import DAYS, FEATURES, LUNCH_WINDOW, PERIODS, Entry, User
from app.solver import solve
from app import optimise
from app import rules as college_rules
from app.importers import fet
from app import substitutions as subs
from app.store import STORE, Occupancy, now_iso
from app.validator import metrics

# every core endpoint needs a signed-in user; sign-in itself lives on auth_router
router = APIRouter(prefix="/api", tags=["core"], dependencies=[Depends(current_user)])
auth_router = APIRouter(prefix="/api/auth", tags=["auth"])
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
        "student_types": [_type_view(t) for t in c.student_types],
        "teachers": [asdict(t) for t in c.teachers],
        "rooms": [asdict(r) for r in c.rooms],
        "counts": {"sections": len(c.sections), "teachers": len(c.teachers), "rooms": len(c.rooms),
                   "lessons": len(c.lessons), "sessions": sum(l.sessions for l in c.lessons)},
    }


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    """The signed-in person and what they may do (the UI builds navigation, tabs and buttons from `can`)."""
    return {**user_view(user), "role_name": ROLES.get(user.role, user.role), "can": capabilities(user),
            "demo": DEMO_MODE}


def _accounts() -> dict:
    groups: dict[str, list[dict]] = {}
    for u in STORE.users.values():
        groups.setdefault(u.role, []).append({"id": u.id, "name": u.name, "dept": u.dept, "section": u.section})
    return {"roles": groups, "role_names": ROLES, "clubs": [asdict(c) for c in STORE.clubs.values()]}


@router.get("/users")
def users(user: User = Depends(current_user)) -> dict:
    """All accounts (timetable office only). Others use the demo sign-in list."""
    require(user, "accounts.view")
    return _accounts()


# --- sign-in (no session needed) -------------------------------------------------------------------
class DemoLogin(BaseModel):
    user: str


@auth_router.get("/demo-accounts")
def demo_accounts() -> dict:
    """Demo mode only: the accounts anyone may sign in as, grouped by role."""
    if not DEMO_MODE:
        raise HTTPException(404, "Demo sign-in is switched off.")
    return _accounts()


@auth_router.post("/demo-login")
def demo_login(body: DemoLogin, request: Request) -> dict:
    """Demo mode only: sign in as a demo account (no password). Real sign-in plugs in next to this."""
    if not DEMO_MODE:
        raise HTTPException(404, "Demo sign-in is switched off.")
    user = STORE.users.get(body.user)
    if user is None:
        raise HTTPException(404, f"No account '{body.user}'")
    request.session["user"] = user.id
    return {"ok": True, "user": user_view(user), "can": capabilities(user)}


@auth_router.post("/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


@router.get("/audit")
def audit(limit: int = 200, user: User = Depends(current_user)) -> dict:
    """Privileged actions, newest first (who, what, on what, allowed or refused)."""
    require(user, "audit.view")
    return {"items": STORE.audit[::-1][:limit]}


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
        if (r.id in busy or r.kind == fet.OUTSIDE_ROOM.kind or r.capacity < min_capacity or (kind and r.kind != kind) or (sittable_only and not r.sittable)
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


ASSISTANT = Assistant()


class ChatRequest(BaseModel):
    messages: list[dict]


@router.post("/chat")
def chat(req: ChatRequest, user: User = Depends(current_user)) -> dict:
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        return {"answer": "The assistant isn't configured: add ANTHROPIC_API_KEY to the .env file.", "tools_used": []}
    try:
        return ASSISTANT.ask(req.messages, user)
    except anthropic.AuthenticationError:
        return {"answer": "The assistant isn't configured: add ANTHROPIC_API_KEY to the .env file.", "tools_used": []}
    except anthropic.APIConnectionError:
        return {"answer": "I can't reach the AI service right now. The timetable and room finder still work.",
                "tools_used": []}
    except anthropic.APIStatusError as e:
        return {"answer": f"The AI service returned an error ({e.status_code}). Please try again.", "tools_used": []}
    except anthropic.AnthropicError:  # e.g. no credentials configured at all
        return {"answer": "The assistant isn't configured: add ANTHROPIC_API_KEY to the .env file.", "tools_used": []}


# --- absences and substitutions ---------------------------------------------------------------
class LeaveIn(BaseModel):
    teacher: str
    date: str
    periods: list[int] = []  # empty = the whole day
    reason: str = ""


class SubstituteIn(BaseModel):
    date: str
    entry_key: str
    teacher: str | None = None  # the substitute; omit with cancel=true
    cancel: bool = False


def _teacher_or_404(teacher_id: str):
    t = STORE.college.teacher_by_id.get(teacher_id)
    if t is None:
        raise HTTPException(404, f"No teacher '{teacher_id}'")
    return t


@router.post("/leave")
def mark_leave(body: LeaveIn, user: User = Depends(current_user)) -> dict:
    """Mark a teacher absent for a date: returns the affected classes with ranked substitutes."""
    t = _teacher_or_404(body.teacher)
    require(user, "leave.mark", t)
    d = _date_or_400(body.date)
    if d.weekday() >= len(DAYS):
        raise HTTPException(400, "That's a weekend: there are no classes to cover.")
    if any(not 0 <= p < len(PERIODS) for p in body.periods):
        raise HTTPException(400, "Invalid period")
    ov = subs.mark_leave(t.id, d.isoformat(), body.periods, body.reason, user.id)
    rows = subs.affected(t.id, d, body.periods)
    hods = [u.id for u in STORE.users.values() if u.role == "hod" and u.dept == t.dept]
    for h in hods:
        STORE.notify(h, f"{t.name} is on leave on {d:%a %d %b}: {sum(r['state'] == 'open' for r in rows)} class(es) need cover",
                     "/#subs")
    return {"leave": asdict(ov), "classes": rows}


@router.get("/leave")
def leaves(on: str, dept: str = "", user: User = Depends(current_user)) -> dict:
    """Everyone on leave on a date (optionally one department), with each affected class and its cover."""
    d = _date_or_400(on)
    out = []
    for ov in STORE.overrides:
        if ov.kind != "leave" or ov.date != d.isoformat() or not ov.teacher:
            continue
        t = STORE.college.teacher_by_id.get(ov.teacher)
        if t is None or (dept and t.dept != dept):
            continue
        if not authorize(user, "leave.view", t):
            continue  # department staff see their department, teachers see themselves
        out.append({"leave": asdict(ov), "teacher_name": t.name, "dept": t.dept,
                    "classes": subs.affected(t.id, d, ov.periods)})
    return {"date": d.isoformat(), "leaves": out}


@router.post("/substitutions")
def substitute(body: SubstituteIn, user: User = Depends(current_user)) -> dict:
    """HOD/admin: put a substitute on one class on one date, or cancel it. Notifies everyone affected."""
    d = _date_or_400(body.date)
    o = next((x for x in (STORE._occ(e) for e in STORE.entries if e.day == d.weekday())
              if x.key == body.entry_key), None)
    if o is None:
        raise HTTPException(404, "That class doesn't happen on that date.")
    lesson = STORE.college.lesson_by_id[o.lesson]
    require(user, "override.create", lesson.dept)
    absent = next((ov.teacher for ov in STORE.overrides if ov.kind == "leave" and ov.date == d.isoformat()
                   and ov.teacher in (o.teacher, *o.co_teachers)), o.teacher)
    when = f"{d:%a %d %b} {subs.class_view(o)['time']}"
    if body.cancel:
        ov = subs.assign(d.isoformat(), o.key, None, True, user.id)
        msg = f"Cancelled: {lesson.code} for {lesson.section} on {when} ({o.room}). The room is free."
    else:
        t = _teacher_or_404(body.teacher or "")
        if t.id not in {c["teacher"] for c in subs.candidates(o, d, absent, limit=10_000)}:
            raise HTTPException(409, f"{t.name} isn't free for this class on {d:%a %d %b}.")
        ov = subs.assign(d.isoformat(), o.key, t.id, False, user.id)
        msg = f"Substitute: {t.name} takes {lesson.code} for {lesson.section} on {when} in {o.room}."
        for u in subs.users_of_teacher(t.id):
            STORE.notify(u, f"You're substituting {lesson.code} for {lesson.section} on {when} in {o.room}.", "/")
    for u in subs.users_of_groups(o.batches) + subs.users_of_teacher(absent):
        STORE.notify(u, msg, "/")
    return {"override": asdict(ov), "message": msg}


def _date_or_400(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, "Use a date like 2026-10-30")


# --- the real CSE timetable vs TimeWeave's optimised version of the same lessons -------------------
_opt = {"mtime": None, "data": None, "running": False, "error": ""}


def _optimised() -> dict | None:
    path = optimise.OUT
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    if _opt["mtime"] != mtime:
        _opt["data"], _opt["mtime"] = json.loads(path.read_text(encoding="utf-8")), mtime
    return _opt["data"]


def _compare_entry(e: Entry) -> dict:
    c = STORE.college
    l = c.lesson_by_id[e.lesson]
    names = [c.teacher_by_id[t].name for t in (l.teacher, *l.co_teachers) if t in c.teacher_by_id]
    return {**asdict(e), "code": l.code, "name": l.name, "kind": l.kind, "section": l.section, "batches": l.batches,
            "teacher": l.teacher, "teachers": [l.teacher, *l.co_teachers], "teacher_names": names}


@router.get("/compare/cse")
def compare_cse(user: User = Depends(current_user)) -> dict:
    """GNDEC's published CSE timetable next to TimeWeave's optimised version of exactly the same lessons."""
    require(user, "optimise.view", "CSE")
    data = _optimised()
    if not data:
        return {"available": False, "running": _opt["running"], "error": _opt["error"]}
    c = STORE.college
    before = [e for e in c.fixed_entries if c.lesson_by_id[e.lesson].dept == "CSE"]
    after = [Entry(**e) for e in data["entries"]]
    return {"available": True, "running": _opt["running"], "status": data["status"], "seconds": data["seconds"],
            "moved": data["moved"], "pinned": data["pinned"], "metrics": data["metrics"], "clashes": data["clashes"],
            "sections": [asdict(s) for s in c.sections if s.dept == "CSE"],
            "types": [{**_type_view(t), "lessons": t.lessons} for t in c.student_types if t.section.startswith("D")
                      and c.section_by_id[t.section].dept == "CSE"],
            "teachers": sorted({t for l in c.lessons if l.fixed and l.dept == "CSE" for t in (l.teacher, *l.co_teachers)}),
            "college": [_compare_entry(e) for e in before], "optimised": [_compare_entry(e) for e in after],
            "rules": college_rules.report(c, before, after),
            "publication": STORE.published.get("CSE", {"status": "draft"})}


@router.post("/compare/cse/run")
def compare_cse_run(seconds: float = 300, user: User = Depends(current_user)) -> dict:
    """Re-run the optimiser in the background (takes minutes); the page polls /api/compare/cse."""
    require(user, "optimise.run", "CSE")
    if _opt["running"]:
        raise HTTPException(409, "The optimiser is already running.")

    def work() -> None:
        _opt["running"], _opt["error"] = True, ""
        try:
            res = optimise.optimise_department(STORE.college, "CSE", time_limit=max(60.0, min(seconds, 1800.0)))
            if res.status == "IMPROVED":
                optimise.save(STORE.college, res)
            else:
                _opt["error"] = "; ".join(res.problems) or res.status
        except Exception as exc:  # report, never crash the server
            _opt["error"] = str(exc)
        finally:
            _opt["running"] = False

    threading.Thread(target=work, daemon=True).start()
    return {"started": True}



# --- students: real combinations of choices ("student types") --------------------------------------
def _type_view(t) -> dict:
    return {"id": t.id, "section": t.section, "name": t.name, "count": t.count, "details": t.details}


@router.get("/students/types")
def student_types(section: str = "", dept: str = "", year: int | None = None) -> dict:
    """Student types (real combinations: section + actual group + electives + lab groups) to pick from."""
    c = STORE.college
    out = [t for t in c.student_types
           if (not section or t.section == section)
           and (not dept or c.section_by_id[t.section].dept == dept)
           and (year is None or c.section_by_id[t.section].year == year)]
    return {"types": [_type_view(t) for t in out]}


@router.get("/students/{type_id}/timetable")
def student_timetable(type_id: str, on: str = "") -> dict:
    """Exactly the classes students of this type attend: the weekly timetable, or one real date (with
    substitutions, cancellations and events booked for their section)."""
    t = STORE.college.type_by_id.get(type_id)
    if t is None:
        raise HTTPException(404, f"No student type '{type_id}'")
    occ = STORE.effective(_date_or_400(on)) if on else STORE.week()
    items = [occupancy_view(o) for o in occ if STORE.attends(t.id, o)]
    items.sort(key=lambda i: (i["day"], i["start"]))
    return {"type": _type_view(t), "date": on or None, "items": items}



# --- propose and publish the optimised timetable -----------------------------------------------------
def _publication_users(dept: str) -> list[str]:
    c = STORE.college
    return [u.id for u in STORE.users.values()
            if (u.section and c.section_by_id.get(u.section) and c.section_by_id[u.section].dept == dept)
            or (u.teacher_id and any(l.fixed and l.dept == dept and u.teacher_id in (l.teacher, *l.co_teachers)
                                      for l in c.lessons))]


@router.post("/compare/cse/propose")
def compare_cse_propose(user: User = Depends(current_user)) -> dict:
    """Department (HOD / timetable coordinator) proposes the optimised timetable to the timetable office."""
    require(user, "optimise.propose", "CSE")
    if not _optimised():
        raise HTTPException(409, "There is no optimised timetable to propose yet.")
    STORE.set_published("CSE", {"status": "proposed", "proposed_by": user.name, "proposed_at": now_iso()})
    for u in [u.id for u in STORE.users.values() if u.role == "admin"]:
        STORE.notify(u, f"{user.name} proposed the optimised CSE timetable for publishing.", "/compare.html")
    return {"publication": STORE.published["CSE"]}


@router.post("/compare/cse/publish")
def compare_cse_publish(user: User = Depends(current_user)) -> dict:
    """Timetable office publishes it: it becomes everyone's real CSE timetable (rooms, teachers, students)."""
    require(user, "timetable.publish")
    data = _optimised()
    if not data or data.get("clashes", {}).get("optimised", 1) != 0:
        raise HTTPException(409, "Only a clash-free optimised timetable can be published.")
    c = STORE.college
    before = [e for e in c.fixed_entries if c.lesson_by_id[e.lesson].dept == "CSE"]
    broken = [r["text"] for r in college_rules.report(c, before, [Entry(**e) for e in data["entries"]])
              if r["optimised"] > r["college"]]
    if broken:
        raise HTTPException(409, "It breaks the college's rules more often than the current timetable: " + " ".join(broken))
    info = {**STORE.published.get("CSE", {}), "status": "published", "published_by": user.name, "published_at": now_iso()}
    STORE.set_published("CSE", info)
    if STORE.result and STORE.result["issues"]:  # the independent validator must still agree
        STORE.set_published("CSE", None)
        raise HTTPException(409, "The validator found clashes; publishing was undone.")
    for u in _publication_users("CSE"):
        STORE.notify(u, "The CSE timetable has been updated: fewer waiting gaps between classes. Check your week.", "/")
    return {"publication": info}


@router.post("/compare/cse/unpublish")
def compare_cse_unpublish(user: User = Depends(current_user)) -> dict:
    """Timetable office goes back to the college's original timetable."""
    require(user, "timetable.publish")
    STORE.set_published("CSE", None)
    for u in _publication_users("CSE"):
        STORE.notify(u, "The CSE timetable is back to the college's original version.", "/")
    return {"publication": {"status": "draft"}}

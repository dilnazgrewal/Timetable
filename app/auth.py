"""Accounts, sign-in and the single place where permissions are decided.

Sign-in: a signed session cookie (Starlette SessionMiddleware). In demo mode (TIMEWEAVE_DEMO=1, the
default) anyone may sign in as any demo account without a password, and API clients/tests may also
send `X-User: <account id>`. With TIMEWEAVE_DEMO=0 only a real session counts (college Google sign-in
plugs in at /api/auth/*). No session means no access: there is no default account.

Authorization: every action is a row in PERMISSIONS (deny by default). Routers call
require(user, action, resource); the UI reads capabilities(user) from /api/me and never re-implements
a rule. Privileged actions are written to the audit log (STORE.audit), allowed or refused.
"""
from __future__ import annotations

import os
from datetime import datetime

from fastapi import Header, HTTPException, Request

from app.models import BookingRequest, Club, College, MeetingRequest, Teacher, User

DEMO_MODE = os.getenv("TIMEWEAVE_DEMO", "1") != "0"
# public demo link (TIMEWEAVE_HOSTED=1): no optimiser runs (minutes of full CPU). The assistant works wherever an
# Anthropic key is set (on the host: an environment variable, never in the repo)
HOSTED = os.getenv("TIMEWEAVE_HOSTED", "0") == "1"


def assistant_ready() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
ROLES = {
    "student": "Student", "teacher": "Teacher", "club": "Club lead", "org": "Visitor / T&P",
    "coordinator": "Timetable coordinator", "hod": "HOD", "dean": "Dean (read-only)", "admin": "Timetable office (admin)",
}
DEPT_STAFF = ("hod", "coordinator")  # manage their own department's timetable


# --- accounts ------------------------------------------------------------------------------------
def demo_people(college: College) -> tuple[dict[str, User], dict[str, Club]]:
    users: list[User] = [User("admin", "Timetable Office (Admin)", "admin"),
                         User("dean", "Dean Academics (read-only)", "dean")]
    people = [t for t in college.teachers if not t.id.startswith("TBA-")]  # not "Major Project (staff)" stand-ins
    for d in [d.code for d in college.departments]:
        teachers = [t for t in people if t.dept == d]
        if teachers:
            users.append(User(f"hod-{d}", f"HOD {d} ({teachers[0].name})", "hod", d, teacher_id=teachers[0].id))
        if len(teachers) > 1 and any(s.dept == d for s in college.sections):
            users.append(User(f"coord-{d}", f"Timetable coordinator {d} ({teachers[1].name})", "coordinator", d,
                              teacher_id=teachers[1].id))
    for t in people:
        users.append(User(f"t-{t.id}", t.name, "teacher", t.dept, teacher_id=t.id))
    # one demo student per real combination of choices (student type); see app/importers/gndec_students.py
    for st in college.student_types:
        s = college.section_by_id[st.section]
        actual = st.details.get("Actual group") or st.details.get("Group") or ""
        users.append(User(f"s-{st.id}", f"Student · {st.name}", "student", s.dept,
                          group=f"{s.id}-{actual}" if actual else None, student_type=st.id, section=s.id))
    if not college.student_types:  # no types: one student per group
        for s in college.sections:
            for b in s.batches:
                users.append(User(f"s-{b}", f"Student · {s.name} {b.rsplit('-', 1)[-1]}", "student", s.dept,
                                  group=b, section=s.id))

    def advisor(dept: str) -> str:
        t = next((t for t in college.teachers if t.dept == dept), college.teachers[0])
        return f"t-{t.id}"

    clubs = [Club("DMC", "Digital Marketing Club", advisor("CSE"), "CSE"),
             Club("CODE", "Coding Club", advisor("IT"), "IT"),
             Club("ROBO", "Robotics Society", advisor("ME"), "ME")]
    for c in clubs:
        users.append(User(f"club-{c.id}", f"{c.name} (student lead)", "club", c.dept, club=c.id))
    users += [User("org-TNP", "Training & Placement Cell", "org"),
              User("org-visitor", "Visiting organisation (e.g. Infosys)", "org")]
    return {u.id: u for u in users}, {c.id: c for c in clubs}


def current_user(request: Request, x_user: str | None = Header(default=None)) -> User:
    """FastAPI dependency: `user: User = Depends(current_user)`. 401 when nobody is signed in."""
    from app.store import STORE

    uid = request.session.get("user") if "session" in request.scope else None
    if uid is None and DEMO_MODE and x_user:
        uid = x_user
    if uid is None:
        raise HTTPException(401, "Please sign in.")
    user = STORE.users.get(uid)
    if user is None:
        raise HTTPException(401, f"Unknown account '{uid}'. Please sign in again.")
    return user


# --- the permission table --------------------------------------------------------------------------
def _dept_staff(user: User, dept: object) -> bool:
    return user.role in DEPT_STAFF and (dept is None or dept == user.dept)


def _teacher_dept(resource: object) -> str | None:
    return resource.dept if isinstance(resource, Teacher) else None


def _endorse(user: User, req: object) -> bool:
    from app.store import STORE

    club = STORE.clubs.get(getattr(req, "club", None) or "")
    return isinstance(req, BookingRequest) and club is not None and club.advisor == user.id


def _approve(user: User, req: object) -> bool:
    from app.store import STORE

    if not isinstance(req, BookingRequest):
        return False
    room = STORE.college.room_by_id.get(req.room)
    if room is None:
        return False
    if room.dept and f"hod-{room.dept}" in STORE.users:  # a department's room: only that department's HOD
        return user.role == "hod" and room.dept == user.dept
    return user.role == "admin"  # central halls: the timetable office


# action -> (what it allows, in words, for refusals; rule(user, resource) -> bool). Admin may do everything.
PERMISSIONS: dict[str, tuple[str, object]] = {
    # everyone who is signed in
    "timetable.view": ("view timetables", lambda u, r: True),
    "rooms.view": ("see free rooms", lambda u, r: True),
    "chat.ask": ("use the assistant", lambda u, r: True),
    # students and teachers
    "meeting.request": ("request meetings (students only)", lambda u, r: u.role == "student"),
    "meeting.reply": ("reply to this meeting request",
                      lambda u, r: isinstance(r, MeetingRequest) and u.teacher_id == r.teacher),
    "leave.mark": ("mark this teacher on leave",
                   lambda u, r: isinstance(r, Teacher) and (u.teacher_id == r.id or _dept_staff(u, r.dept))),
    "leave.view": ("see this teacher's leave",
                   lambda u, r: isinstance(r, Teacher) and (u.teacher_id == r.id or _dept_staff(u, r.dept) or u.role == "dean")),
    # students' timetable concerns: students raise and agree; their department's staff see counts and answer
    "concern.raise": ("report a timetable concern (students only)", lambda u, r: u.role == "student" and bool(u.student_type)),
    "concern.view": ("see this department's student concerns", lambda u, r: _dept_staff(u, r) or u.role == "dean"),
    "concern.answer": ("answer this department's student concerns", lambda u, r: _dept_staff(u, r)),
    # department timetable work (HOD and timetable coordinator of that department)
    "override.create": ("change this department's classes", lambda u, r: _dept_staff(u, r)),
    "optimise.view": ("see this department's optimised timetable", lambda u, r: _dept_staff(u, r) or u.role == "dean"),
    "optimise.run": ("re-run the optimiser for this department", lambda u, r: _dept_staff(u, r)),
    "optimise.propose": ("propose the optimised timetable", lambda u, r: _dept_staff(u, r)),
    "insights.view": ("see this department's insights", lambda u, r: _dept_staff(u, r) or u.role == "dean"),
    # venues and events
    "booking.request": ("request venues", lambda u, r: u.role in ("club", "org") or u.teacher_id is not None),
    "booking.cancel": ("cancel this booking", lambda u, r: isinstance(r, BookingRequest) and r.requester == u.id),
    "booking.endorse": ("endorse this request (only the club's faculty advisor can)", _endorse),
    "booking.approve": ("approve this booking (only the HOD who owns the room can; central halls: the timetable office)", _approve),
    "slotfinder.use": ("use the event slot finder", lambda u, r: u.role in ("club", "org", "dean") or u.teacher_id is not None),
    # college-wide (admin; the Dean may look)
    "timetable.generate": ("regenerate the college timetable (timetable office only)", lambda u, r: False),
    "timetable.publish": ("publish a timetable (timetable office only)", lambda u, r: False),
    "audit.view": ("see the audit log", lambda u, r: u.role == "dean"),
    "accounts.view": ("see all accounts", lambda u, r: False),
    "demo.reset": ("reset the demo", lambda u, r: False),
}
READ_ONLY = {"timetable.view", "rooms.view", "chat.ask", "concern.view", "leave.view", "optimise.view", "insights.view", "audit.view",
             "accounts.view"}


# things a person does about their own timetable as a student: the timetable office sees and answers them instead
STUDENTS_ONLY = {"concern.raise", "meeting.request"}
# someone else's authority: a department's hall needs its HOD, a club's request its faculty advisor. The timetable
# office approves only what is its own (central halls), through the rule itself
OWN_AUTHORITY = {"booking.approve", "booking.endorse"}


def authorize(user: User, action: str, resource: object = None) -> bool:
    """Every permission rule lives in PERMISSIONS. Unknown actions are refused."""
    if action not in PERMISSIONS:
        return False
    if user.role == "admin" and action not in STUDENTS_ONLY | OWN_AUTHORITY:
        return True
    return bool(PERMISSIONS[action][1](user, resource))


def require(user: User, action: str, resource: object = None) -> None:
    allowed = authorize(user, action, resource)
    if action not in READ_ONLY:
        _audit(user, action, resource, allowed)
    if not allowed:
        what = PERMISSIONS.get(action, (action.replace(".", " "),))[0]
        raise HTTPException(403, f"{user.name} is not allowed to {what}.")


def _audit(user: User, action: str, resource: object, allowed: bool) -> None:
    from app.store import STORE

    label = getattr(resource, "id", None) or (resource if isinstance(resource, str) else "")
    STORE.audit.append({"at": datetime.now().isoformat(timespec="seconds"), "user": user.id, "name": user.name,
                        "role": user.role, "action": action, "on": str(label or ""), "allowed": allowed})
    del STORE.audit[:-2000]  # keep the latest entries


def capabilities(user: User) -> dict[str, bool]:
    """What the signed-in person can do, for the UI (navigation, tabs, buttons). Same rules as above."""
    from app.store import STORE

    a = lambda action, res=None: authorize(user, action, res)
    dept = user.dept
    teacher = STORE.college.teacher_by_id.get(user.teacher_id or "")
    return {
        "view_timetables": a("timetable.view"),
        "my_timetable": bool(user.student_type or user.teacher_id),
        "free_rooms": a("rooms.view"),
        "find_teacher": a("timetable.view"),
        "request_meeting": a("meeting.request"),
        "reply_meetings": user.teacher_id is not None,
        "mark_own_leave": teacher is not None and a("leave.mark", teacher),
        "mark_dept_leave": user.role in DEPT_STAFF or user.role == "admin",
        "substitutions": a("override.create", dept) if user.role != "admin" else True,
        "request_venue": a("booking.request"),
        "endorse_venues": user.role == "admin" or any(c.advisor == user.id for c in STORE.clubs.values()),
        "approve_venues": user.role in ("hod", "admin"),
        "slot_finder": a("slotfinder.use"),
        "optimised_view": a("optimise.view", dept or "CSE") or user.role == "dean",  # their department; Dean: all
        "optimised_run": a("optimise.run", dept or "CSE") and not HOSTED,
        "optimised_propose": a("optimise.propose", dept or "CSE"),
        "publish": a("timetable.publish"),
        "generate": a("timetable.generate"),
        "insights": user.role in ("dean", "admin") or a("insights.view", dept),
        "audit": a("audit.view"),
        "accounts": a("accounts.view"),
        "demo_reset": a("demo.reset"),
        "chat": a("chat.ask") and (assistant_ready() or not HOSTED),
        "raise_concerns": a("concern.raise"),
        "view_concerns": a("concern.view", dept) or user.role in ("dean", "admin"),
        "answer_concerns": a("concern.answer", dept) or user.role == "admin",
    }

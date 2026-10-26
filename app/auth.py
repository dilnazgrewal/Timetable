"""Demo accounts and the single place where permissions are decided.

There are no passwords in the demo: the page sends the chosen account id in the `X-User` header and
the server checks every action with authorize(). UI hiding is cosmetic; this file is the real gate.
"""
from __future__ import annotations

from fastapi import Header, HTTPException

from app.models import BookingRequest, Club, College, MeetingRequest, Teacher, User

DEFAULT_USER = "admin"


def demo_people(college: College) -> tuple[dict[str, User], dict[str, Club]]:
    users: list[User] = [User("admin", "Timetable Office (Admin)", "admin")]
    depts = [d.code for d in college.departments]
    for d in depts:
        teachers = [t for t in college.teachers if t.dept == d]
        if teachers:
            users.append(User(f"hod-{d}", f"HOD {d} ({teachers[0].name})", "hod", d, teacher_id=teachers[0].id))
    for t in college.teachers:
        users.append(User(f"t-{t.id}", t.name, "teacher", t.dept, teacher_id=t.id))
    for s in college.sections:
        for b in s.batches:
            users.append(User(f"s-{b}", f"Student · {s.name} {b.rsplit('-', 1)[-1]}", "student", s.dept, group=b))

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


def current_user(x_user: str | None = Header(default=None)) -> User:
    """FastAPI dependency: `user: User = Depends(current_user)`."""
    from app.store import STORE

    user = STORE.users.get(x_user or DEFAULT_USER)
    if user is None:
        raise HTTPException(401, f"Unknown demo account '{x_user}'")
    return user


def authorize(user: User, action: str, resource: object = None) -> bool:
    """Every permission rule lives here. Actions are dotted strings; add new ones here, not in routers."""
    from app.store import STORE

    r = user.role
    if r == "admin":
        return True
    if action in ("timetable.view", "rooms.view", "chat.ask"):
        return True
    if action == "timetable.generate":
        return r == "hod"
    if action == "override.create":  # substitutions / cancellations for a department
        return r == "hod" and (resource is None or resource == user.dept)
    if action == "booking.request":
        return r in ("club", "teacher", "hod", "org")
    if action == "booking.cancel" and isinstance(resource, BookingRequest):
        return resource.requester == user.id
    if action == "booking.endorse" and isinstance(resource, BookingRequest):
        club = STORE.clubs.get(resource.club or "")
        return club is not None and club.advisor == user.id
    if action == "booking.approve" and isinstance(resource, BookingRequest):
        room = STORE.college.room_by_id.get(resource.room)
        # department rooms: that department's HOD; central rooms: admin only (handled above)
        return r == "hod" and room is not None and room.dept == user.dept
    if action == "slotfinder.use":
        return r in ("org", "hod", "teacher", "club")
    if action == "leave.mark" and isinstance(resource, Teacher):  # mark a teacher absent for a date
        return user.teacher_id == resource.id or (r == "hod" and user.dept == resource.dept)
    if action == "leave.view" and isinstance(resource, Teacher):
        return user.teacher_id == resource.id or r == "hod"
    if action == "meeting.request":
        return r == "student"
    if action == "meeting.reply" and isinstance(resource, MeetingRequest):
        return user.teacher_id == resource.teacher
    return False


ACTION_TEXT = {
    "timetable.generate": "regenerate the timetable", "override.create": "change this department's classes",
    "booking.request": "request venues", "booking.cancel": "cancel this booking",
    "booking.endorse": "endorse this request (only the club's faculty advisor can)",
    "booking.approve": "approve this booking (only the HOD who owns the room can)",
    "slotfinder.use": "use the event slot finder", "meeting.request": "request meetings",
    "meeting.reply": "reply to this meeting request", "leave.mark": "mark this teacher on leave",
    "leave.view": "see this teacher's leave", "demo.reset": "reset the demo",
}


def require(user: User, action: str, resource: object = None) -> None:
    if not authorize(user, action, resource):
        raise HTTPException(403, f"{user.name} is not allowed to {ACTION_TEXT.get(action, action.replace('.', ' '))}.")

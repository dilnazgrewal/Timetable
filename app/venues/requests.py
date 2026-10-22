"""Booking requests and their approval chain: club lead → faculty advisor → HOD (or admin for central rooms).

Status moves pending → endorsed (advisor said yes) → approved, or to rejected / cancelled. Final approval
turns the request into an Override(kind="booking"), so the room leaves Free rooms for those periods.
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import HTTPException

from app.auth import authorize, require
from app.models import ApprovalStep, BookingRequest, Override, User
from app.store import new_id, now_iso
from app.venues.common import day_label, periods_label, room_view, store
from app.venues.ranking import ACTIVE, busy_reason, competing, conflicts

INBOX = "/venues.html#inbox"
MINE = "/venues.html#requests"
ROLE_LABEL = {"advisor": "Faculty advisor", "hod": "HOD", "admin": "Timetable office"}
ACTION = {"advisor": "booking.endorse", "hod": "booking.approve", "admin": "booking.approve"}


def build_steps(user: User, club: str | None, room_id: str) -> list[ApprovalStep]:
    """Club requests go to the club's faculty advisor first. Then the room's owner signs off:
    the HOD of the room's department, or the timetable office (admin) for central rooms."""
    s = store()
    steps = []
    if club and user.role == "club":  # teachers, HODs and organisations skip the advisor
        steps.append(ApprovalStep("advisor", s.clubs[club].advisor))
    room = s.college.room_by_id[room_id]
    hod = f"hod-{room.dept}" if room.dept else None
    steps.append(ApprovalStep("hod", hod) if hod in s.users else ApprovalStep("admin", "admin"))
    # the person who would approve it is asking: their own step needs no second click
    for st in steps:
        if st.approver == user.id:
            st.decision, st.note, st.at = "approved", "Requested by the approver", now_iso()
    return steps


def current_step(req: BookingRequest) -> ApprovalStep | None:
    if req.status not in ACTIVE:
        return None
    return next((st for st in req.steps if st.decision is None), None)


def who(user_id: str) -> str:
    u = store().users.get(user_id)
    return u.name if u else user_id


def summary(req: BookingRequest) -> str:
    return f"“{req.title}” · {req.room} · {day_label(req.date)}, {periods_label(req.periods)}"


def ensure_free(req: BookingRequest) -> None:
    clash = conflicts(req.room, store().effective(req.date), req.periods)
    if clash:
        raise HTTPException(409, f"{req.room} is no longer free on {day_label(req.date)}: "
                                 f"{busy_reason(clash[0]).lower()}. Ask for another venue or time.")


def find(req_id: str) -> BookingRequest:
    req = next((b for b in store().bookings if b.id == req_id), None)
    if req is None:
        raise HTTPException(404, "No such booking request")
    return req


def view(req: BookingRequest, user: User) -> dict:
    """The request as the UI shows it: room details, what it's waiting for, a timeline and what you can do."""
    s = store()
    step = current_step(req)
    room = s.college.room_by_id.get(req.room)
    timeline = [{"label": f"Requested by {who(req.requester)}", "at": req.created_at, "state": "done"}]
    for st in req.steps:
        label = f"{ROLE_LABEL[st.role]} · {who(st.approver)}"
        if st.decision:
            verb = ("endorsed" if st.role == "advisor" else "approved") if st.decision == "approved" else "rejected"
            timeline.append({"label": f"{label} {verb}", "at": st.at, "note": st.note,
                             "state": "done" if st.decision == "approved" else "rejected"})
        elif req.status in ACTIVE:
            timeline.append({"label": f"Waiting for {label}", "at": None,
                             "state": "current" if st is step else "todo"})
    if req.status == "cancelled":
        timeline.append({"label": "Cancelled", "at": None, "state": "rejected"})
    elif req.status == "approved":
        timeline.append({"label": "Booked: the room is reserved", "at": None, "state": "done"})
    waiting = f"{ROLE_LABEL[step.role]} ({who(step.approver)})" if step else None
    can_decide = step is not None and authorize(user, ACTION[step.role], req)
    can_cancel = req.status in (*ACTIVE, "approved") and authorize(user, "booking.cancel", req)
    others = [b.id for b in competing(req.room, req.date, req.periods, skip=req.id)] if req.status in ACTIVE else []
    return {**asdict(req), "room_info": room_view(room) if room else None,
            "requester_name": who(req.requester), "when": f"{day_label(req.date)}, {periods_label(req.periods)}",
            "waiting_for": waiting, "step_role": step.role if step else None, "timeline": timeline,
            "can_decide": can_decide, "can_cancel": can_cancel, "assigned_to_me": bool(step and step.approver == user.id),
            "competing": others}


def create(user: User, title: str, purpose: str, club: str | None, attendees: int, needs: list[str],
           on: str, periods: list[int], room_id: str) -> tuple[BookingRequest, list[str]]:
    s = store()
    require(user, "booking.request")
    room = s.college.room_by_id.get(room_id)
    if room is None or not room.bookable:
        raise HTTPException(400, f"{room_id} can't be booked for events.")
    if user.role == "club":
        club = user.club  # a club lead always books for their own club
    elif club and club not in s.clubs:
        raise HTTPException(400, f"Unknown club '{club}'")
    if not title.strip():
        raise HTTPException(400, "Give your event a title.")
    req = BookingRequest(new_id("bk"), title.strip(), user.id, club, attendees, needs, on, periods, room_id,
                         created_at=now_iso(), purpose=purpose.strip())
    ensure_free(req)
    warnings = []
    if attendees > room.capacity:
        warnings.append(f"{room_id} seats {room.capacity}, fewer than the {attendees} people you expect.")
    missing = [n for n in needs if n not in room.features]
    if missing:
        warnings.append(f"{room_id} doesn't list {', '.join(missing)}.")
    others = competing(room_id, on, periods)
    if others:
        warnings.append(f"{len(others)} other request(s) for {room_id} at this time are also waiting. "
                        "Whoever is approved first gets the room.")
    req.steps = build_steps(user, club, room_id)
    with s.lock:
        s.bookings.append(req)
        advance(req, user)
    return req, warnings


def advance(req: BookingRequest, actor: User) -> None:
    """Move status forward after a step was decided; finish the booking or ping the next approver."""
    s = store()
    step = current_step(req)
    if step is None:
        ensure_free(req)
        req.status = "approved"
        s.add_override(Override(new_id("ov"), req.date, "booking", periods=list(req.periods), room=req.room,
                                title=f"{req.club}: {req.title}" if req.club else req.title, ref=req.id,
                                created_by=actor.id))
        if req.requester != actor.id:
            s.notify(req.requester, f"✅ Approved: {summary(req)}. The room is yours.", MINE)
        return
    if any(st.role == "advisor" and st.decision == "approved" for st in req.steps):
        req.status = "endorsed"
    verb = "endorse" if step.role == "advisor" else "approve"
    s.notify(step.approver, f"📝 Please {verb}: {summary(req)} (from {who(req.requester)})", INBOX)
    if req.status == "endorsed" and req.requester != actor.id:
        s.notify(req.requester, f"👍 Endorsed by your faculty advisor: {summary(req)}. "
                                f"Now waiting for {ROLE_LABEL[step.role]}.", MINE)


def decide(user: User, req_id: str, decision: str, note: str) -> BookingRequest:
    s = store()
    with s.lock:
        req = find(req_id)
        step = current_step(req)
        if step is None:
            raise HTTPException(409, f"This request is already {req.status}.")
        require(user, ACTION[step.role], req)
        if decision not in ("approved", "rejected"):
            raise HTTPException(400, "Decision must be 'approved' or 'rejected'.")
        if decision == "rejected" and not note.strip():
            raise HTTPException(400, "Please give a reason so the requester knows what to change.")
        if decision == "approved" and all(st.decision for st in req.steps if st is not step):
            ensure_free(req)  # last step: refuse before recording a yes we can't honour
        step.decision, step.note, step.at = decision, note.strip(), now_iso()
        if decision == "rejected":
            req.status = "rejected"
            s.notify(req.requester, f"❌ Not approved: {summary(req)}. Reason: {step.note}", MINE)
        else:
            advance(req, user)
        s.save()
        return req


def cancel(user: User, req_id: str) -> BookingRequest:
    s = store()
    with s.lock:
        req = find(req_id)
        require(user, "booking.cancel", req)
        if req.status not in (*ACTIVE, "approved"):
            raise HTTPException(409, f"This request is already {req.status}.")
        was_booked = req.status == "approved"
        req.status = "cancelled"
        s.overrides = [o for o in s.overrides if not (o.kind == "booking" and o.ref == req.id)]
        if was_booked:  # let the person who approved it know the room is free again
            last = req.steps[-1].approver
            if last != user.id:
                s.notify(last, f"↩️ Cancelled by {who(req.requester)}: {summary(req)}. The room is free again.", INBOX)
        s.save()
        return req


def listing(user: User, inbox: bool = False, everything: bool = False) -> list[BookingRequest]:
    reqs = store().bookings
    if everything and user.role == "admin":
        out = list(reqs)
    elif inbox:
        out = [r for r in reqs if (st := current_step(r)) and authorize(user, ACTION[st.role], r)]
        if user.role == "admin":  # the office sees its own queue, not every club's advisor step
            out = [r for r in out if current_step(r).approver == user.id]
    else:
        out = [r for r in reqs if r.requester == user.id]
    return sorted(out, key=lambda r: r.created_at, reverse=True)

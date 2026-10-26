"""Lane B (Dashboards UI): role dashboards, filtered views, teacher free slots, meeting requests.

Owned by the Dashboards session. Read data through app.store.STORE (week() / effective(date)),
check permissions with app.auth.require(), and keep every route under /api/dash.
See docs/API.md for the contract.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import current_user, require
from app.models import DAYS, PERIODS, MeetingRequest, User
from app.store import STORE, Occupancy, new_id, now_iso

router = APIRouter(prefix="/api/dash", tags=["dashboards"])


# --- helpers -------------------------------------------------------------------------------------
def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, "Use a date like 2026-10-23")


def week_dates(d: date) -> list[date]:
    """Mon–Fri of the week containing d (a Saturday or Sunday means the coming week)."""
    monday = d - timedelta(days=d.weekday()) + (timedelta(days=7) if d.weekday() >= len(DAYS) else timedelta())
    return [monday + timedelta(days=i) for i in range(len(DAYS))]


def period_view(p: int) -> dict:
    label, start, end = PERIODS[p]
    return {"period": p, "label": label, "start": start, "end": end}


def item_view(o: Occupancy, on: date | None = None) -> dict:
    """An occupancy plus the names the UI needs (subject, teacher, section, lab or theory)."""
    c = STORE.college
    l = c.lesson_by_id.get(o.lesson or "")
    t = c.teacher_by_id.get(o.teacher or "")
    regular = c.teacher_by_id.get(l.teacher) if l and o.status == "substituted" else None
    return {**asdict(o), "date": on.isoformat() if on else None,
            "code": l.code if l else "EVENT", "name": l.name if l else o.title,
            "lesson_kind": l.kind if l else "booking", "dept": l.dept if l else "",
            "section": l.section if l else "", "teacher_name": t.name if t else "",
            "co_teacher_names": [c.teacher_by_id[x].name for x in o.co_teachers if x in c.teacher_by_id],
            "regular_teacher_name": regular.name if regular else "",  # set when a substitute takes the class
            "until": PERIODS[o.start + o.duration - 1][2]}


def groups_of(dept: str = "", year: int | None = None, section: str = "") -> set[str] | None:
    """Audience groups selected by dept / year / section (None = no audience filter)."""
    if not (dept or year or section):
        return None
    secs = [s for s in STORE.college.sections
            if (not dept or s.dept == dept) and (year is None or s.year == year) and (not section or s.id == section)]
    return {b for s in secs for b in s.batches}


def matcher(dept: str, year: int | None, section: str, group: str, teacher: str, room: str, student: str = ""):
    """Return a predicate over Occupancy for the chosen filters (all filters combine with AND).
    `student` is a student type (a real combination of group + electives): exactly the classes they attend."""
    groups = {group} if group else groups_of(dept, year, section)
    c = STORE.college
    teaching_dept = dept if groups == set() and not (year or section or group) else ""

    def ok(o: Occupancy) -> bool:
        if teacher and not teaches(o, teacher):
            return False
        if room and o.room != room:
            return False
        if student:
            return STORE.attends(student, o)
        if teaching_dept:  # a department with no sections of its own (e.g. Applied Sciences): what its teachers teach
            t = c.teacher_by_id.get(o.teacher or "")
            return bool(t and t.dept == teaching_dept)
        return groups is None or bool(set(o.batches) & groups)

    return ok


def teaches(o: Occupancy, teacher_id: str) -> bool:
    """Main teacher or co-teacher (labs have 2–3 teachers in the room)."""
    return o.teacher == teacher_id or teacher_id in o.co_teachers


def teacher_busy(teacher_id: str, occ: list[Occupancy]) -> dict[int, Occupancy]:
    return {p: o for o in occ if teaches(o, teacher_id) for p in o.slots}


def leave_periods(teacher_id: str, d: date) -> set[int]:
    """Periods a teacher is on leave that date (a leave override with no periods means the whole day)."""
    return {p for ov in STORE.overrides if ov.kind == "leave" and ov.teacher == teacher_id and ov.date == d.isoformat()
            for p in (ov.periods or range(len(PERIODS)))}


def teacher_free(teacher_id: str, d: date) -> dict:
    """A teacher's periods on a real date: leave, teaching (incl. co-taught labs), unavailable, meeting or free."""
    t = STORE.college.teacher_by_id.get(teacher_id)
    if t is None:
        raise HTTPException(404, f"No teacher '{teacher_id}'")
    wd = d.weekday()
    base = {"teacher": t.id, "name": t.name, "dept": t.dept, "date": d.isoformat(),
            "day": DAYS[wd] if wd < len(DAYS) else "", "periods": []}
    if wd >= len(DAYS):
        return {**base, "weekend": True, "free": []}
    busy = teacher_busy(t.id, STORE.effective(d))
    off = {p for day, p in t.unavailable if day == wd}
    leave = leave_periods(t.id, d)
    met = {m.period for m in STORE.meetings if m.teacher == t.id and m.date == d.isoformat() and m.status == "accepted"}
    periods = []
    for p in range(len(PERIODS)):
        if p in leave:
            state, what = "leave", "On leave"
        elif p in busy:
            o = busy[p]
            l = STORE.college.lesson_by_id.get(o.lesson or "")
            state, what = "teaching", f"{l.code} · {l.section} · {o.room}" if l else o.title
        elif p in off:
            state, what = "unavailable", "Not on campus"
        elif p in met:
            state, what = "meeting", "Meeting with a student"
        else:
            state, what = "free", ""
        periods.append({**period_view(p), "state": state, "what": what})
    return {**base, "weekend": False, "periods": periods, "free": [p for p in periods if p["state"] == "free"]}


def meeting_view(m: MeetingRequest) -> dict:
    t = STORE.college.teacher_by_id.get(m.teacher)
    s = STORE.users.get(m.student)
    d = parse_date(m.date)
    return {**asdict(m), "teacher_name": t.name if t else m.teacher, "student_name": s.name if s else m.student,
            "day": DAYS[d.weekday()] if d.weekday() < len(DAYS) else "", "slot": period_view(m.period)}


def teacher_users(teacher_id: str) -> list[str]:
    """Every demo account that is this teacher (their t- account, and the HOD account if they are HOD)."""
    return [u.id for u in STORE.users.values() if u.teacher_id == teacher_id]


# --- routes --------------------------------------------------------------------------------------
@router.get("/ping")
def ping(user: User = Depends(current_user)) -> dict:
    return {"lane": "dashboards", "user": user.id}


@router.get("/views")
def views(dept: str = "", year: int | None = None, section: str = "", group: str = "", student: str = "",
          teacher: str = "", room: str = "", on: str = "", week_of: str = "",
          user: User = Depends(current_user)) -> dict:
    """Filtered timetable. No date: the base weekly timetable. `on`: one real date. `week_of`: Mon–Fri
    of that date's week with every date's changes (substitutions, cancellations, bookings)."""
    require(user, "timetable.view")
    if student and student not in STORE.college.type_by_id:
        raise HTTPException(404, f"No student type '{student}'")
    ok = matcher(dept, year, section, group, teacher, room, student)
    if on:
        d = parse_date(on)
        items = [item_view(o, d) for o in STORE.effective(d) if ok(o)]
        dates = [d.isoformat()]
        mode = "date"
    elif week_of:
        dates_ = week_dates(parse_date(week_of))
        items = [item_view(o, d) for d in dates_ for o in STORE.effective(d) if ok(o)]
        dates = [d.isoformat() for d in dates_]
        mode = "week_of"
    else:
        items = [item_view(o) for o in STORE.week() if ok(o)]
        dates, mode = [], "week"
    items.sort(key=lambda i: (i["day"], i["start"], i["section"], i["room"]))
    return {"mode": mode, "dates": dates, "items": items,
            "filters": {"dept": dept, "year": year, "section": section, "group": group, "student": student, "teacher": teacher, "room": room}}


@router.get("/teacher/{teacher_id}/free")
def free_slots(teacher_id: str, on: str = "", user: User = Depends(current_user)) -> dict:
    """A teacher's day on a real date (default today): which periods are free to meet them."""
    require(user, "timetable.view")
    return teacher_free(teacher_id, parse_date(on) if on else date.today())


class MeetingIn(BaseModel):
    teacher: str
    date: str
    period: int
    note: str = ""


@router.post("/meetings")
def request_meeting(body: MeetingIn, user: User = Depends(current_user)) -> dict:
    require(user, "meeting.request")
    d = parse_date(body.date)
    if not 0 <= body.period < len(PERIODS):
        raise HTTPException(400, "Pick a valid period")
    if d < date.today():
        raise HTTPException(400, "That date has already passed")
    day = teacher_free(body.teacher, d)
    if day["weekend"]:
        raise HTTPException(400, "There are no classes at the weekend; pick a weekday")
    slot = day["periods"][body.period]
    if slot["state"] != "free":
        raise HTTPException(409, f"{day['name']} is not free in {slot['label']} ({slot['state']}). Pick a free period.")
    with STORE.lock:
        if any(m.student == user.id and m.teacher == body.teacher and m.date == body.date and m.period == body.period
               and m.status != "declined" for m in STORE.meetings):
            raise HTTPException(409, "You have already asked for this slot.")
        m = MeetingRequest(new_id("m"), user.id, body.teacher, body.date, body.period, body.note.strip()[:300],
                           created_at=now_iso())
        STORE.meetings.append(m)
        STORE.save()
    for uid in teacher_users(body.teacher):
        STORE.notify(uid, f"{user.name} asked to meet you on {day['day']} {body.date}, {slot['label']} ({slot['start']})",
                     "/#meetings")
    return meeting_view(m)


@router.get("/meetings")
def my_meetings(user: User = Depends(current_user)) -> dict:
    """Meetings I asked for (students) and meetings asked of me (teachers / HODs), newest first."""
    sent = [meeting_view(m) for m in STORE.meetings if m.student == user.id]
    received = [meeting_view(m) for m in STORE.meetings if user.teacher_id and m.teacher == user.teacher_id]
    return {"sent": sent[::-1], "received": received[::-1],
            "pending": sum(m["status"] == "pending" for m in received)}


class ReplyIn(BaseModel):
    status: str
    reply: str = ""


@router.post("/meetings/{meeting_id}/reply")
def reply_meeting(meeting_id: str, body: ReplyIn, user: User = Depends(current_user)) -> dict:
    m = next((m for m in STORE.meetings if m.id == meeting_id), None)
    if m is None:
        raise HTTPException(404, "No such meeting request")
    require(user, "meeting.reply", m)
    if body.status not in ("accepted", "declined"):
        raise HTTPException(400, "status must be 'accepted' or 'declined'")
    with STORE.lock:
        m.status, m.reply = body.status, body.reply.strip()[:300]
        STORE.save()
    t = STORE.college.teacher_by_id.get(m.teacher)
    word = "accepted" if m.status == "accepted" else "declined"
    note = f": “{m.reply}”" if m.reply else ""
    STORE.notify(m.student, f"{t.name if t else m.teacher} {word} your meeting on {m.date}, "
                            f"{PERIODS[m.period][0]} ({PERIODS[m.period][1]}){note}", "/#teacher")
    return meeting_view(m)


@router.get("/now")
def now_card(on: str = "", period: int = -1, user: User = Depends(current_user)) -> dict:
    """The caller's day: what's on now, what's next, and when they are next free.
    `period` is the current period index; -1 = before the day starts, len(periods) = after it ends."""
    d = parse_date(on) if on else date.today()
    wd = d.weekday()
    who = "group" if (user.student_type or user.group) else "teacher" if user.teacher_id else None
    out = {"date": d.isoformat(), "day": DAYS[wd] if wd < len(DAYS) else "", "who": who, "period": period,
           "now": None, "next": None, "free": None, "today": [], "leave": [], "meetings": [],
           "weekend": wd >= len(DAYS)}
    if who is None or out["weekend"]:
        return out
    if who == "group":
        # a student type attends exactly its own classes (FET group numbers are re-used across electives)
        mine = [o for o in STORE.effective(d)
                if (STORE.attends(user.student_type, o) if user.student_type else user.group in o.batches)]
        off: set[int] = set()
    else:
        leave = leave_periods(user.teacher_id or "", d)
        # classes they actually take: co-taught labs count, classes during their leave don't
        mine = [o for o in STORE.effective(d) if teaches(o, user.teacher_id or "") and not set(o.slots) <= leave]
        t = STORE.college.teacher_by_id.get(user.teacher_id or "")
        off = {p for day, p in (t.unavailable if t else []) if day == wd} | leave
        out["leave"] = [period_view(p) for p in sorted(leave)]
    mine.sort(key=lambda o: o.start)
    out["today"] = [item_view(o, d) for o in mine]
    now = next((o for o in mine if period in o.slots), None)
    nxt = next((o for o in mine if o.start > period), None)
    out["now"] = item_view(now, d) if now else None
    out["next"] = item_view(nxt, d) if nxt else None
    met = {m.period for m in STORE.meetings if m.date == d.isoformat() and m.status == "accepted"
           and (m.student == user.id or m.teacher == user.teacher_id)}
    out["meetings"] = [period_view(p) for p in sorted(met)]
    busy = {p for o in mine for p in o.slots} | off | met
    first = next((p for p in range(max(period, 0), len(PERIODS)) if p not in busy), None)
    if first is not None:
        end = next((p for p in range(first, len(PERIODS)) if p in busy), len(PERIODS))
        out["free"] = {**period_view(first), "until": PERIODS[end - 1][2], "periods": end - first,
                       "now": first == period}
    return out

"""Read-only timetable assistant: Claude answers questions using tools over the live timetable.
It has no write tools at all — changes will only ever be *proposed* through the change engine (P3)."""
from __future__ import annotations

import json
from datetime import datetime

import anthropic

from app.importers.fet import OUTSIDE_ROOM
from app.importers.fet_dept import room_key
from app.models import DAYS, PERIODS
from app.store import STORE, Occupancy, to_date

MODEL = "claude-opus-5-5"
MAX_TOOL_ROUNDS = 6

WHEN = {
    "date": {"type": "string", "description": "A real date YYYY-MM-DD (includes bookings, cancellations and "
                                              "substitutions). Prefer this; work it out from today's date."},
    "day": {"type": "string", "enum": DAYS, "description": "Weekday of the regular weekly timetable (no one-off changes)."},
}
AT = {"time": {"type": "string", "description": "A clock time HH:MM (24h), e.g. 12:45, or a period label P1..P9. "
                                              "Omit for right now."}}

TOOLS = [
    {
        "name": "search",
        "description": "Find teachers, sections/groups or rooms by (partial) name. Always use this first to turn a "
                       "name the user typed into an exact id.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}},
                         "required": ["query"], "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "get_schedule",
        "description": "Schedule of a student (their student type id: exactly their classes, incl. their electives), "
                       "a section (e.g. D3-CS-A, every class of the section), a teacher (e.g. KD) or a room (e.g. G17) "
                       "for one date/weekday, or the whole week if neither is given.",
        "input_schema": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["student", "section", "teacher", "room"]},
            "id": {"type": "string"}, **WHEN},
            "required": ["kind", "id"], "additionalProperties": False},
    },
    {
        "name": "free_rooms",
        "description": "Rooms with nothing happening at a given time, grouped by building and floor, with when each "
                       "becomes busy again. By default only rooms students may sit in (labs excluded).",
        "input_schema": {"type": "object", "properties": {
            **WHEN, **AT,
            "building": {"type": "string", "description": "Building id, e.g. MBA (CSE & IT block)."},
            "floor": {"type": "string", "enum": ["Ground", "First", "Second"]},
            "sittable_only": {"type": "boolean", "description": "Default true. False includes labs and halls."},
            "min_seats": {"type": "integer"}},
            "additionalProperties": False},
    },
    {
        "name": "room_status",
        "description": "Is one room free at a given time? Returns what is happening there, until when it stays free "
                       "or busy, and the next class. Use for questions like 'will G17 be empty at 12:30 on Friday?'.",
        "input_schema": {"type": "object", "properties": {"room": {"type": "string"}, **WHEN, **AT},
                         "required": ["room"], "additionalProperties": False},
    },
    {
        "name": "teacher_free_slots",
        "description": "Periods on a date/weekday when a teacher (by id) is free: not teaching (including labs they "
                       "co-teach), not on leave and on campus.",
        "input_schema": {"type": "object", "properties": {"teacher_id": {"type": "string"}, **WHEN},
                         "required": ["teacher_id"], "additionalProperties": False},
    },
]
LABELS = [p[0] for p in PERIODS]


def _system(user=None) -> str:
    periods = ", ".join(f"{p} {s}-{e}" for p, s, e in PERIODS)
    buildings = "; ".join(f"{b.id} = {b.name}" for b in STORE.college.buildings)
    now = datetime.now()
    return (
        "You are TimeWeave's timetable assistant for GNDEC Ludhiana. Answer ONLY from tool results; never guess "
        "a room, time, teacher or class. If a name is ambiguous, list the matches and ask which one. If the "
        "tools cannot answer, say so. You cannot change anything: for changes, point people to the right screen "
        "(venue booking for halls, their HOD for timetable changes).\n"
        f"Today is {now:%A %Y-%m-%d}, time {now:%H:%M}. Resolve 'today', 'tomorrow', 'Friday' etc. to a real date "
        "and pass `date`. Weekends have no classes.\n"
        f"Periods: {periods}. Lunch is flexible: each class gets a free hour somewhere in 11:30-14:30, so 'after "
        "lunch' depends on the class; check its schedule.\n"
        f"Buildings: {buildings}. Room ids starting G are on the ground floor, F first floor, S second floor. "
        "Students may not sit in labs.\n"
        "Keep answers short and friendly for a phone screen. Use plain text with simple dash lists, no markdown."
        + _asker(user)
    )


def _asker(user) -> str:
    if user is None:
        return ""
    if user.student_type:
        t = STORE.college.type_by_id.get(user.student_type)
        detail = ", ".join(f"{k}: {v}" for k, v in (t.details if t else {}).items())
        return (f"\nThe person asking is a student: {user.name}. For 'my' timetable use get_schedule with kind "
                f"'student' and id '{user.student_type}' ({detail}).")
    if user.teacher_id:
        return f"\nThe person asking is the teacher {user.name} (teacher id {user.teacher_id})."
    return f"\nThe person asking: {user.name} ({user.role})."


def _period(time: str | None) -> int:
    """'P5' / '12:45' / None (now) -> period index."""
    if time and time.upper() in LABELS:
        return LABELS.index(time.upper())
    hm = time or datetime.now().strftime("%H:%M")
    for i, (_, s, e) in enumerate(PERIODS):
        if s <= hm < e:
            return i
    raise ValueError(f"{hm} is outside college hours ({PERIODS[0][1]}-{PERIODS[-1][2]})")


def _today_weekday() -> str:
    return DAYS[min(datetime.now().weekday(), len(DAYS) - 1)]


class Assistant:
    """Tools read the shared STORE: a real `date` gives what actually happens (bookings, cancellations,
    substitutions); a `day` gives the regular weekly timetable."""

    # --- helpers ---------------------------------------------------------
    def _occ(self, date: str | None = None, day: str | None = None) -> tuple[list[Occupancy], str, int | None]:
        """-> (occupancies, human 'when', weekday index or None for the whole week)."""
        if date:
            d = to_date(date)
            if d.weekday() >= len(DAYS):
                return [], f"{d:%A %Y-%m-%d} (weekend: no classes)", None
            return STORE.effective(d), f"{d:%A %Y-%m-%d}", d.weekday()
        if day:
            wd = next((i for i, d in enumerate(DAYS) if day.strip().lower().startswith(d.lower())), None)  # "Mon", "Monday"
            if wd is None:
                raise ValueError(f"'{day}' is not a weekday; use one of {', '.join(DAYS)}")
            day = DAYS[wd]
            return [o for o in STORE.week() if o.day == wd], f"every {day} (regular timetable)", wd
        return STORE.week(), "whole week (regular timetable)", None

    def _describe(self, o: Occupancy) -> dict:
        c = STORE.college
        l = c.lesson_by_id.get(o.lesson or "")
        names = [c.teacher_by_id[t].name for t in [o.teacher, *o.co_teachers] if t in c.teacher_by_id]
        out = {"day": DAYS[o.day], "time": f"{PERIODS[o.start][1]}-{PERIODS[o.start + o.duration - 1][2]}",
               "periods": [LABELS[p] for p in o.slots], "room": o.room}
        if l:
            out |= {"subject": f"{l.name} ({l.code})", "type": l.kind, "class": l.section, "teachers": names}
        else:
            out |= {"event": o.title, "type": "booked event"}
        if o.status != "normal":
            out["change_today"] = o.status.replace("_", " ")
        return out

    # --- tools -----------------------------------------------------------
    def search(self, query: str) -> dict:
        q = query.lower().replace("prof.", "").replace("dr.", "").replace("pf.", "").strip()
        c = STORE.college
        return {
            "teachers": [{"id": t.id, "name": t.name, "dept": t.dept} for t in c.teachers
                         if q in t.name.lower() or q == t.id.lower()][:8],
            "sections": [{"id": s.id, "name": s.name, "groups": s.groups} for s in c.sections
                         if q.replace(" ", "-") in s.id.lower() or q in s.name.lower()][:8],
            "rooms": [{"id": r.id, "kind": r.kind, "building": r.building, "floor": r.floor} for r in c.rooms
                      if r.kind != OUTSIDE_ROOM.kind and (q in r.id.lower() or q in r.kind.lower()
                                                          or room_key(query) == room_key(r.id))][:8],  # "S-213" = S213
        }

    def get_schedule(self, kind: str, id: str, date: str | None = None, day: str | None = None) -> dict:
        occ, when, _ = self._occ(date, day)

        def hit(o: Occupancy) -> bool:
            if kind == "section":
                return any(b.startswith(id + "-") for b in o.batches)
            if kind in ("student", "group"):
                return STORE.attends(id, o) if id in STORE.college.type_by_id else id in o.batches
            if kind == "teacher":
                return id == o.teacher or id in o.co_teachers
            return o.room == id
        rows = sorted((o for o in occ if hit(o)), key=lambda o: (o.day, o.start))
        return {"kind": kind, "id": id, "when": when, "classes": [self._describe(o) for o in rows]}

    def free_rooms(self, date: str | None = None, day: str | None = None, time: str | None = None,
                   building: str | None = None, floor: str | None = None, sittable_only: bool = True,
                   min_seats: int = 0) -> dict:
        p = _period(time)
        occ, when, _ = self._occ(date, day or (None if date else _today_weekday()))
        busy = STORE.busy_rooms(occ, p)
        floors: dict[str, list[dict]] = {}
        for r in STORE.college.rooms:
            if (r.id in busy or r.kind == OUTSIDE_ROOM.kind or (sittable_only and not r.sittable) or r.capacity < min_seats
                    or (building and r.building != building) or (floor and r.floor != floor)):
                continue
            nxt = min((o.start for o in occ if o.room == r.id and o.start > p), default=None)
            floors.setdefault(f"{r.building} · {r.floor} floor", []).append(
                {"room": r.id, "seats": r.capacity, "free_until": PERIODS[nxt][1] if nxt is not None else PERIODS[-1][2]})
        return {"when": when, "at": f"{LABELS[p]} {PERIODS[p][1]}-{PERIODS[p][2]}", "free_by_floor": floors,
                "note": "Labs are left out: students may not sit in them." if sittable_only else ""}

    def room_status(self, room: str, date: str | None = None, day: str | None = None, time: str | None = None) -> dict:
        r = STORE.college.room_by_id.get(room)
        if r is None:
            return {"error": f"No room '{room}'. Use search first."}
        p = _period(time)
        occ, when, _ = self._occ(date, day or (None if date else _today_weekday()))
        mine = sorted((o for o in occ if o.room == room), key=lambda o: o.start)
        now = next((o for o in mine if p in o.slots), None)
        nxt = next((o for o in mine if o.start > p), None)
        out = {"room": room, "building": r.building, "floor": r.floor, "kind": r.kind, "when": when,
               "at": f"{LABELS[p]} {PERIODS[p][1]}-{PERIODS[p][2]}", "free": now is None,
               "students_may_sit_here": r.sittable}
        if now:
            out["happening"] = self._describe(now)
            out["busy_until"] = PERIODS[now.start + now.duration - 1][2]
        else:
            out["free_until"] = PERIODS[nxt.start][1] if nxt else PERIODS[-1][2]
        if nxt:
            out["next"] = self._describe(nxt)
        return out

    def teacher_free_slots(self, teacher_id: str, date: str | None = None, day: str | None = None) -> dict:
        t = STORE.college.teacher_by_id.get(teacher_id)
        if not t:
            return {"error": f"No teacher with id {teacher_id}; use search first."}
        occ, when, wd = self._occ(date, day or (None if date else _today_weekday()))
        if wd is None:
            return {"teacher": t.name, "when": when, "free_periods": []}
        busy = {p for o in occ if teacher_id in (o.teacher, *o.co_teachers) for p in o.slots}
        off = {p for d, p in t.unavailable if d == wd}
        if date:
            off |= {p for ov in STORE.overrides if ov.kind == "leave" and ov.teacher == teacher_id
                    and ov.date == to_date(date).isoformat() for p in (ov.periods or range(len(PERIODS)))}
        free = [f"{LABELS[p]} {PERIODS[p][1]}-{PERIODS[p][2]}" for p in range(len(PERIODS)) if p not in busy | off]
        return {"teacher": t.name, "when": when, "free_periods": free,
                "note": "not on campus / on leave" if len(off) == len(PERIODS) else ""}

    def _run_tool(self, name: str, args: dict) -> str:
        try:
            return json.dumps(getattr(self, name)(**args))
        except Exception as exc:  # report tool errors to the model instead of crashing
            return json.dumps({"error": str(exc)})

    # --- conversation ----------------------------------------------------
    def _create(self, client: anthropic.Anthropic, messages: list, user=None):
        kwargs = dict(model=MODEL, max_tokens=4000, system=_system(user), tools=TOOLS, messages=messages,
                      output_config={"effort": "low"})
        try:
            return client.beta.messages.create(betas=["server-side-fallback-2026-07-01"],
                                               fallbacks="default", **kwargs)
        except anthropic.BadRequestError:
            return client.messages.create(**kwargs)

    def ask(self, history: list[dict], user=None) -> dict:
        """history: [{role, content: str}] from the UI. Returns {answer, tools_used}."""
        if not STORE.entries:
            return {"answer": "No timetable has been generated yet.", "tools_used": []}
        client = anthropic.Anthropic()
        messages: list = [{"role": m["role"], "content": m["content"]} for m in history[-10:]]
        used: list[str] = []
        for _ in range(MAX_TOOL_ROUNDS):
            resp = self._create(client, messages, user)
            if resp.stop_reason == "refusal":
                return {"answer": "Sorry, I can't help with that.", "tools_used": used}
            if resp.stop_reason != "tool_use":
                text = "".join(b.text for b in resp.content if b.type == "text").strip()
                return {"answer": text or "I couldn't find an answer.", "tools_used": used}
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for b in resp.content:
                if b.type == "tool_use":
                    used.append(b.name)
                    results.append({"type": "tool_result", "tool_use_id": b.id,
                                    "content": self._run_tool(b.name, dict(b.input))})
            messages.append({"role": "user", "content": results})
        return {"answer": "That took too many steps; please ask a narrower question.", "tools_used": used}

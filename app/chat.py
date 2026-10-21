"""Read-only timetable assistant: Claude answers questions using tools over the live timetable.
It has no write tools at all — changes will only ever be *proposed* through the change engine (P3)."""
from __future__ import annotations

import json
from datetime import datetime

import anthropic

from app.models import DAYS, PERIODS, College, Entry

MODEL = "claude-opus-5-5"
MAX_TOOL_ROUNDS = 6

TOOLS = [
    {
        "name": "search",
        "description": "Find teachers, sections or rooms by (partial) name. Always use this first to turn a "
                       "name the user typed into an exact id.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}},
                         "required": ["query"], "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "get_schedule",
        "description": "Weekly or single-day schedule of a section (e.g. CSE-3A), teacher (e.g. T07) or room "
                       "(e.g. CL-2). day is Mon..Fri, or omit for the whole week.",
        "input_schema": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["section", "teacher", "room"]},
            "id": {"type": "string"},
            "day": {"type": "string", "enum": DAYS}},
            "required": ["kind", "id"], "additionalProperties": False},
    },
    {
        "name": "free_rooms",
        "description": "Rooms with no class in a given period. kind filters by room type, e.g. Classroom, "
                       "Computer Lab, Lecture Theatre, Seminar Hall.",
        "input_schema": {"type": "object", "properties": {
            "day": {"type": "string", "enum": DAYS},
            "period": {"type": "string", "enum": [p[0] for p in PERIODS]},
            "kind": {"type": "string"}},
            "required": ["day", "period"], "additionalProperties": False},
    },
    {
        "name": "teacher_free_slots",
        "description": "Periods on a day when a teacher (by id) is free and available.",
        "input_schema": {"type": "object", "properties": {
            "teacher_id": {"type": "string"}, "day": {"type": "string", "enum": DAYS}},
            "required": ["teacher_id", "day"], "additionalProperties": False},
    },
]


def _system() -> str:
    periods = ", ".join(f"{p} {s}-{e}" for p, s, e in PERIODS)
    now = datetime.now()
    return (
        "You are TimeWeave's timetable assistant for a college. Answer ONLY from tool results; never guess "
        "a room, time, teacher or class. If a name is ambiguous, list the matches and ask which one. If the "
        "tools cannot answer, say so. You cannot change the timetable: if asked to, explain that changes go "
        "through the coordinator's editor with a preview and confirmation.\n"
        f"Week: {', '.join(DAYS)}. Periods: {periods}. Lunch is flexible: each class and teacher gets a free hour somewhere in 11:30-14:30 (P4-P6); 'after lunch' means after that class's own break, so check its schedule. "
        f"Now: {now:%A %H:%M}. Keep answers short and friendly, suitable for a phone screen. Use plain text with simple dash lists, no markdown formatting."
    )


class Assistant:
    def __init__(self, college: College, entries_fn) -> None:
        self.college = college
        self.entries_fn = entries_fn  # returns the current list[Entry]

    # --- tools -----------------------------------------------------------
    def _describe(self, e: Entry) -> dict:
        l = self.college.lesson_by_id[e.lesson]
        end = PERIODS[e.start + e.duration - 1][2]
        return {"day": DAYS[e.day], "time": f"{PERIODS[e.start][1]}-{end}",
                "periods": [PERIODS[p][0] for p in e.slots], "subject": f"{l.name} ({l.code})",
                "type": l.kind, "class": l.section, "teacher": self.college.teacher_by_id[l.teacher].name,
                "room": e.room}

    def search(self, query: str) -> dict:
        q = query.lower().replace("prof.", "").replace("dr.", "").strip()
        c = self.college
        return {
            "teachers": [{"id": t.id, "name": t.name, "dept": t.dept} for t in c.teachers if q in t.name.lower()][:8],
            "sections": [{"id": s.id, "name": s.name} for s in c.sections
                         if q in s.id.lower() or q in s.name.lower()][:8],
            "rooms": [{"id": r.id, "kind": r.kind} for r in c.rooms if q in r.id.lower() or q in r.kind.lower()][:8],
        }

    def get_schedule(self, kind: str, id: str, day: str | None = None) -> dict:
        def hit(e: Entry) -> bool:
            l = self.college.lesson_by_id[e.lesson]
            if kind == "section":
                return any(b.startswith(id + "-") for b in l.batches)
            if kind == "teacher":
                return l.teacher == id
            return e.room == id
        d = DAYS.index(day) if day else None
        rows = [e for e in self.entries_fn() if hit(e) and (d is None or e.day == d)]
        rows.sort(key=lambda e: (e.day, e.start))
        return {"kind": kind, "id": id, "day": day or "whole week", "classes": [self._describe(e) for e in rows]}

    def free_rooms(self, day: str, period: str, kind: str | None = None) -> dict:
        d, p = DAYS.index(day), [x[0] for x in PERIODS].index(period)
        busy = {e.room for e in self.entries_fn() if e.day == d and p in e.slots}
        free = [{"room": r.id, "kind": r.kind, "seats": r.capacity} for r in self.college.rooms
                if r.id not in busy and (not kind or kind.lower() in r.kind.lower())]
        return {"day": day, "period": period, "free": free}

    def teacher_free_slots(self, teacher_id: str, day: str) -> dict:
        t = self.college.teacher_by_id.get(teacher_id)
        if not t:
            return {"error": f"No teacher with id {teacher_id}; use search first."}
        d = DAYS.index(day)
        unav = {tuple(u) for u in t.unavailable}
        busy = {p for e in self.entries_fn() if e.day == d
                and self.college.lesson_by_id[e.lesson].teacher == teacher_id for p in e.slots}
        free = [f"{PERIODS[p][0]} {PERIODS[p][1]}-{PERIODS[p][2]}" for p in range(len(PERIODS))
                if p not in busy and (d, p) not in unav]
        return {"teacher": t.name, "day": day, "free_periods": free,
                "note": "not on campus this day" if all((d, p) in unav for p in range(len(PERIODS))) else ""}

    def _run_tool(self, name: str, args: dict) -> str:
        try:
            return json.dumps(getattr(self, name)(**args))
        except Exception as exc:  # report tool errors to the model instead of crashing
            return json.dumps({"error": str(exc)})

    # --- conversation ----------------------------------------------------
    def _create(self, client: anthropic.Anthropic, messages: list):
        kwargs = dict(model=MODEL, max_tokens=4000, system=_system(), tools=TOOLS, messages=messages,
                      output_config={"effort": "low"})
        try:
            return client.beta.messages.create(betas=["server-side-fallback-2026-07-01"],
                                               fallbacks="default", **kwargs)
        except anthropic.BadRequestError:
            return client.messages.create(**kwargs)

    def ask(self, history: list[dict]) -> dict:
        """history: [{role, content: str}] from the UI. Returns {answer, tools_used}."""
        if not self.entries_fn():
            return {"answer": "No timetable has been generated yet.", "tools_used": []}
        client = anthropic.Anthropic()
        messages: list = [{"role": m["role"], "content": m["content"]} for m in history[-10:]]
        used: list[str] = []
        for _ in range(MAX_TOOL_ROUNDS):
            resp = self._create(client, messages)
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

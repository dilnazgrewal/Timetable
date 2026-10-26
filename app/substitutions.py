"""Absences and substitutions (Lane A).

A teacher (or their HOD) marks leave for a date -> Override(kind="leave"). Every class that teacher
has that day is "affected". For each one we rank possible substitutes:

  must:  free for the whole class on that date (incl. labs they co-teach, bookings don't matter),
         on campus that weekday, not on leave, and under their daily limit after taking it
  score: +40 teaches the same subject   +20 same department   +15 already teaches these students
         +5  has a class right before/after (no extra trip)
         -8  per substitution already done this month (fairness)   -4 per period already taught that day

The HOD then assigns one (Override "substitute") or cancels the class (Override "cancel"); everyone
affected is notified. If someone else co-teaches the class (labs), it is covered without a substitute.
"""
from __future__ import annotations

from datetime import date

from app.models import DAYS, PERIODS, Override
from app.store import STORE, Occupancy, new_id, to_date


def _leave_periods(teacher_id: str, d: date) -> set[int]:
    return {p for ov in STORE.overrides if ov.kind == "leave" and ov.teacher == teacher_id and ov.date == d.isoformat()
            for p in (ov.periods or range(len(PERIODS)))}


def _teaches(o: Occupancy, teacher_id: str) -> bool:
    return teacher_id == o.teacher or teacher_id in o.co_teachers


def _period_text(o: Occupancy) -> str:
    return f"{PERIODS[o.start][1]}-{PERIODS[o.start + o.duration - 1][2]}"


def class_view(o: Occupancy) -> dict:
    c = STORE.college
    l = c.lesson_by_id.get(o.lesson or "")
    return {"key": o.key, "day": DAYS[o.day], "start": o.start, "duration": o.duration, "time": _period_text(o),
            "room": o.room, "code": l.code if l else "", "subject": l.name if l else o.title,
            "section": l.section if l else "", "batches": o.batches, "dept": l.dept if l else "",
            "teacher": o.teacher, "teacher_name": c.teacher_by_id[o.teacher].name if o.teacher in c.teacher_by_id else ""}


def candidates(o: Occupancy, d: date, absent: str, limit: int = 5) -> list[dict]:
    """Ranked substitutes for one class on one date, each with plain-English reasons."""
    c = STORE.college
    occ = STORE.effective(d)
    wd = d.weekday()
    lesson = c.lesson_by_id.get(o.lesson or "")
    month = d.isoformat()[:7]
    subs_this_month: dict[str, int] = {}
    for ov in STORE.overrides:
        if ov.kind == "substitute" and ov.teacher and ov.date.startswith(month):
            subs_this_month[ov.teacher] = subs_this_month.get(ov.teacher, 0) + 1
    # what each teacher teaches (main or co-teacher), from the weekly timetable
    codes: dict[str, set[str]] = {}
    groups: dict[str, set[str]] = {}
    for l in c.lessons:
        for t in (l.teacher, *l.co_teachers):
            codes.setdefault(t, set()).add(l.code)
            groups.setdefault(t, set()).update(l.batches)

    out = []
    for t in c.teachers:
        if t.id == absent or t.id.startswith("TBA-"):
            continue
        busy = {p for x in occ if _teaches(x, t.id) for p in x.slots}
        if any(p in busy for p in o.slots):
            continue
        off = {p for day, p in t.unavailable if day == wd} | _leave_periods(t.id, d)
        if any(p in off for p in o.slots):
            continue
        if len(busy) + o.duration > t.max_per_day:
            continue
        score, why = 0, []
        if lesson and lesson.code in codes.get(t.id, set()):
            score += 40
            why.append(f"teaches {lesson.code}")
        if lesson and t.dept == lesson.dept:
            score += 20
            why.append(f"{t.dept} department")
        if set(o.batches) & groups.get(t.id, set()):
            score += 15
            why.append("already teaches these students")
        if (o.start - 1) in busy or (o.start + o.duration) in busy:
            score += 5
            why.append("has a class right next to it")
        n_subs = subs_this_month.get(t.id, 0)
        if n_subs:
            score -= 8 * n_subs
            why.append(f"{n_subs} substitution{'s' if n_subs > 1 else ''} this month")
        if busy:
            score -= 4 * len(busy)
        why.append(f"{len(busy)} period{'s' if len(busy) != 1 else ''} that day")
        out.append({"teacher": t.id, "name": t.name, "dept": t.dept, "score": score, "reasons": why})
    out.sort(key=lambda x: (-x["score"], x["name"]))
    return out[:limit]


def cover_state(o: Occupancy, d: date, absent: str) -> dict:
    """How an affected class is handled: substituted / cancelled / covered by a co-teacher / open."""
    c = STORE.college
    for ov in STORE.overrides:
        if ov.date == d.isoformat() and ov.entry_key == o.key:
            if ov.kind == "cancel":
                return {"state": "cancelled"}
            if ov.kind == "substitute" and ov.teacher:
                return {"state": "substituted", "by": ov.teacher, "by_name": c.teacher_by_id[ov.teacher].name}
    others = [t for t in (o.teacher, *o.co_teachers)
              if t != absent and not set(o.slots) & _leave_periods(t, d)]
    if others:
        return {"state": "covered", "by": others[0], "by_name": c.teacher_by_id[others[0]].name}
    return {"state": "open"}


def affected(teacher_id: str, on: str | date, periods: list[int] | None = None) -> list[dict]:
    """Classes the absent teacher has on that date (base timetable, before substitutions), with cover state
    and, for open ones, ranked candidates."""
    d = to_date(on)
    wd = d.weekday()
    if wd >= len(DAYS):
        return []
    mine = [STORE._occ(e) for e in STORE.entries if e.day == wd]
    mine = [o for o in mine if _teaches(o, teacher_id) and (not periods or set(o.slots) & set(periods))]
    rows = []
    for o in sorted(mine, key=lambda o: o.start):
        row = {**class_view(o), **cover_state(o, d, teacher_id)}
        if row["state"] == "open":
            row["candidates"] = candidates(o, d, teacher_id)
        rows.append(row)
    return rows


def mark_leave(teacher_id: str, on: str, periods: list[int], reason: str, by: str) -> Override:
    d = to_date(on)
    ov = Override(new_id("leave"), d.isoformat(), "leave", periods=sorted(periods), teacher=teacher_id,
                  title=reason or "On leave", created_by=by)
    return STORE.add_override(ov)


def assign(on: str, entry_key: str, substitute: str | None, cancel: bool, by: str) -> Override:
    """Substitute (or cancel) one class on one date; replaces any earlier decision for that class."""
    d = to_date(on)
    with STORE.lock:
        STORE.overrides = [ov for ov in STORE.overrides
                           if not (ov.date == d.isoformat() and ov.entry_key == entry_key and ov.kind in ("substitute", "cancel"))]
    if cancel:
        ov = Override(new_id("cancel"), d.isoformat(), "cancel", entry_key=entry_key, title="Class cancelled", created_by=by)
    else:
        ov = Override(new_id("sub"), d.isoformat(), "substitute", entry_key=entry_key, teacher=substitute,
                      title="Substitute teacher", created_by=by)
    return STORE.add_override(ov)


def users_of_teacher(teacher_id: str) -> list[str]:
    return [u.id for u in STORE.users.values() if u.teacher_id == teacher_id]


def users_of_groups(groups: list[str]) -> list[str]:
    g = set(groups)
    return [u.id for u in STORE.users.values() if u.group in g]

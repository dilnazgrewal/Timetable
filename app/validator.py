"""Independent timetable checker. Deliberately shares NO code with the solver (no OR-Tools import):
the "0 clashes" claim comes from here, not from the solver grading itself."""
from __future__ import annotations

from collections import defaultdict

from app.models import DAYS, LUNCH_WINDOW, MAX_BATCH_PER_DAY, PERIODS, SOLVER_PERIODS, College, Entry, run_of


def _slot(d: int, p: int) -> str:
    return f"{DAYS[d]} {PERIODS[p][0]}"


# Quality notes: rules a good timetable follows (our generator guarantees them) but a hand-made or
# imported one may break. Everything else validate() reports is a hard error (a clash).
NOTE_PREFIXES = ("NO LUNCH", "LONG DAY")


def split_issues(issues: list[str]) -> tuple[list[str], list[str]]:
    """-> (clashes, quality_notes)."""
    return ([i for i in issues if not i.startswith(NOTE_PREFIXES)],
            [i for i in issues if i.startswith(NOTE_PREFIXES)])


def validate(college: College, entries: list[Entry]) -> list[str]:
    issues: list[str] = []
    placed: dict[str, int] = defaultdict(int)
    teacher_at: dict[tuple, list[str]] = defaultdict(list)
    batch_at: dict[tuple, list[str]] = defaultdict(list)
    room_at: dict[tuple, list[str]] = defaultdict(list)
    teacher_day: dict[tuple, int] = defaultdict(int)
    batch_day: dict[tuple, int] = defaultdict(int)

    for e in entries:
        l = college.lesson_by_id.get(e.lesson)
        if l is None:
            issues.append(f"Unknown lesson {e.lesson}")
            continue
        placed[l.id] += 1
        room = college.room_by_id.get(e.room)
        teacher = college.teacher_by_id[l.teacher]
        if not (0 <= e.day < len(DAYS)):
            issues.append(f"{l.id}: invalid day {e.day}")
            continue
        if e.duration != l.duration:
            issues.append(f"{l.id}: duration {e.duration} != required {l.duration}")
        run = run_of(e.start)
        if run is None or e.start + e.duration > run[1]:
            issues.append(f"{l.id}: block at {_slot(e.day, e.start)} runs past the end of the day")
        if room is None:
            issues.append(f"{l.id}: unknown room {e.room}")
        else:
            if room.kind != l.room_kind:
                issues.append(f"{l.id}: needs a {l.room_kind}, got {room.id} ({room.kind})")
            if room.capacity < l.size:
                issues.append(f"{l.id}: {room.id} holds {room.capacity}, class has {l.size}")
        for p in e.slots:
            if (e.day, p) in {tuple(u) for u in teacher.unavailable}:
                issues.append(f"{teacher.name} is unavailable at {_slot(e.day, p)} but teaches {l.id}")
            for tid in [l.teacher, *l.co_teachers]:
                teacher_at[(tid, e.day, p)].append(l.id)
            room_at[(e.room, e.day, p)].append(l.id)
            for b in l.batches:
                batch_at[(b, e.day, p)].append(l.id)
            for tid in [l.teacher, *l.co_teachers]:
                teacher_day[(tid, e.day)] += 1
            for b in l.batches:
                batch_day[(b, e.day)] += 1

    for l in college.lessons:
        if placed[l.id] != l.sessions:
            issues.append(f"{l.id}: {placed[l.id]} sessions placed, {l.sessions} required")

    for kind, table in (("Teacher", teacher_at), ("Students", batch_at), ("Room", room_at)):
        for (who, d, p), ids in table.items():
            if len(ids) > 1:
                name = college.teacher_by_id[who].name if kind == "Teacher" else who
                issues.append(f"CLASH {kind} {name} at {_slot(d, p)}: {', '.join(ids)}")

    lunch_label = f"{PERIODS[LUNCH_WINDOW[0]][1]}–{PERIODS[LUNCH_WINDOW[-1]][2]}"
    for kind, table in (("Teacher", teacher_at), ("Students", batch_at)):
        days = {(who, d) for (who, d, _p) in table}
        for who, d in days:
            if all(table.get((who, d, p)) for p in LUNCH_WINDOW):
                name = college.teacher_by_id[who].name if kind == "Teacher" else who
                issues.append(f"NO LUNCH {kind} {name} on {DAYS[d]}: busy all of {lunch_label}")

    for (t, d), n in teacher_day.items():
        if n > college.teacher_by_id[t].max_per_day:
            issues.append(f"LONG DAY Teacher {college.teacher_by_id[t].name} teaches {n} periods on {DAYS[d]}")
    for (b, d), n in batch_day.items():
        if n > MAX_BATCH_PER_DAY:
            issues.append(f"LONG DAY Students {b} has {n} periods on {DAYS[d]} (max {MAX_BATCH_PER_DAY})")
    return issues


def metrics(college: College, entries: list[Entry], fixed: bool | None = None) -> dict:
    """Quality numbers for the dashboard: student idle periods, single-lecture days, loads, room use.
    fixed=True: only imported (real) lessons; fixed=False: only generated ones; None: everything."""
    n_periods = len(PERIODS)
    occ: dict[tuple, set[int]] = defaultdict(set)
    load: dict[str, int] = defaultdict(int)
    room_used: dict[str, int] = defaultdict(int)
    t_occ: dict[tuple, set[int]] = defaultdict(set)
    late = 0
    for e in entries:
        l = college.lesson_by_id[e.lesson]
        if fixed is not None and l.fixed != fixed:
            continue
        for b in l.batches:
            occ[(b, e.day)].update(e.slots)
        for tid in [l.teacher, *l.co_teachers]:
            load[tid] += e.duration
            t_occ[(tid, e.day)].update(e.slots)
        late += e.start + e.duration > SOLVER_PERIODS
        room_used[e.room] += e.duration

    idle = lonely = active_days = no_lunch = 0
    worst = 0
    for slots in occ.values():
        if not slots:
            continue
        active_days += 1
        free_inside = set(range(min(slots), max(slots) + 1)) - slots
        # one free period in the lunch window is the lunch break, not idle time
        gap = len(free_inside) - (1 if free_inside & set(LUNCH_WINDOW) else 0)
        idle += gap
        worst = max(worst, gap)
        lonely += len(slots) == 1
        no_lunch += all(p in slots for p in LUNCH_WINDOW)
    teacher_load = sorted(
        ({"id": t.id, "name": t.name, "dept": t.dept, "hours": load.get(t.id, 0)} for t in college.teachers),
        key=lambda x: -x["hours"])
    hours = [x["hours"] for x in teacher_load]

    def util(kinds: set[str]) -> float:
        rs = [r for r in college.rooms if r.kind in kinds]
        total = len(rs) * len(DAYS) * n_periods
        return round(100 * sum(room_used.get(r.id, 0) for r in rs) / total, 1) if total else 0.0

    def longest_run(slots: set[int]) -> int:
        best = run = 0
        for p in range(n_periods):
            run = run + 1 if p in slots else 0
            best = max(best, run)
        return best

    t_idle = sum((max(v) - min(v) + 1) - len(v) - (1 if (set(range(min(v), max(v) + 1)) - v) & set(LUNCH_WINDOW) else 0)
                 for v in t_occ.values() if v)
    return {
        "teacher_streak_days": sum(longest_run(v) >= 4 for v in t_occ.values()),  # 4+ lectures in a row
        "teacher_no_lunch_days": sum(all(p in v for p in LUNCH_WINDOW) for v in t_occ.values()),
        "teacher_idle_total": t_idle,
        "teacher_days": sum(bool(v) for v in t_occ.values()),
        "late_sessions": late,  # classes running into the 16:30-17:30 slot
        "idle_per_day": round(idle / active_days, 2) if active_days else 0.0,
        "idle_total": idle,
        "worst_gap": worst,
        "lonely_days": lonely,
        "no_lunch_days": no_lunch,
        "long_days": sum(len(v) > MAX_BATCH_PER_DAY for v in occ.values()),
        "group_days": active_days,
        "teacher_load": teacher_load,
        "load_min": min(hours) if hours else 0,
        "load_max": max(hours) if hours else 0,
        "util_classrooms": util({"Classroom"}),
        "util_labs": util({"Computer Lab", "Electronics Lab", "Mechanical Lab", "Civil Lab"}),
    }

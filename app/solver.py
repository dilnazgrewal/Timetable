"""CP-SAT timetable generator.

One boolean per (session, day, start period, room). Hard constraints: every session placed once,
no teacher/batch/room overlap, teacher availability, labs as contiguous blocks that never span lunch,
at most one session of a theory lesson per day, daily caps. Soft: minimise student idle gaps,
single-lecture days, teacher gaps and long teaching streaks.
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from app.models import DAYS, LUNCH_WINDOW, MAX_BATCH_PER_DAY, RUNS, SOLVER_PERIODS, College, Entry, Lesson

W_STUDENT_GAP = 10
W_LONELY_DAY = 6
W_TEACHER_GAP = 2
W_LONG_STREAK = 5


@dataclass
class SolveResult:
    status: str
    entries: list[Entry] = field(default_factory=list)
    seconds: float = 0.0
    objective: float | None = None
    problems: list[str] = field(default_factory=list)


def prechecks(college: College, lessons: list[Lesson] | None = None) -> list[str]:
    """Fast, human-readable reasons why no timetable can exist (run before the solver)."""
    problems: list[str] = []
    lessons = movable(college) if lessons is None else lessons
    n_days, n_per = len(DAYS), SOLVER_PERIODS
    hours: dict[str, int] = defaultdict(int)
    batch_hours: dict[str, int] = defaultdict(int)
    for l in lessons:
        hours[l.teacher] += l.sessions * l.duration
        for b in l.batches:
            batch_hours[b] += l.sessions * l.duration
    for t in college.teachers:
        unav = {tuple(u) for u in t.unavailable}
        free = n_days * n_per - len(unav)
        days_free = sum(any((d, p) not in unav for p in range(n_per)) for d in range(n_days))
        cap = min(free, days_free * t.max_per_day)
        if hours[t.id] > cap:
            problems.append(f"{t.name} is assigned {hours[t.id]} hours but can teach at most {cap} "
                            f"with their availability.")
    for b, h in batch_hours.items():
        if h > n_days * MAX_BATCH_PER_DAY:
            problems.append(f"{b} needs {h} periods a week but the limit is {n_days * MAX_BATCH_PER_DAY}.")
    blocks_per_day = sum((min(b, n_per) - a) // 2 for a, b in RUNS)
    demand: dict[str, int] = defaultdict(int)
    for l in lessons:
        if l.kind == "lab":
            demand[l.room_kind] += l.sessions
    for kind, need in demand.items():
        supply = sum(r.kind == kind for r in college.rooms) * n_days * blocks_per_day
        if need > supply:
            problems.append(f"{kind}s: {need} lab blocks needed but only {supply} available per week.")
    return problems


def movable(college: College) -> list[Lesson]:
    """Lessons the generator places. Imported (fixed) lessons keep their published slots."""
    return [l for l in college.lessons if not l.fixed]


def solve(college: College, time_limit: float = 30.0, optimize: bool = True, workers: int = 8,
          log: bool = False) -> SolveResult:
    t0 = time.time()
    lessons = movable(college)
    problems = prechecks(college, lessons)
    if problems:
        return SolveResult("INFEASIBLE", problems=problems, seconds=time.time() - t0)

    n_days, n_per = len(DAYS), SOLVER_PERIODS
    m = cp_model.CpModel()
    sessions = [(l, k) for l in lessons for k in range(l.sessions)]
    x: dict[tuple, cp_model.IntVar] = {}
    by_session: dict[int, list] = defaultdict(list)
    session_day: dict[int, list] = defaultdict(list)
    lesson_day: dict[tuple, list] = defaultdict(list)
    teacher_cover: dict[tuple, list] = defaultdict(list)
    batch_cover: dict[tuple, list] = defaultdict(list)
    room_cover: dict[tuple, list] = defaultdict(list)

    for si, (l, k) in enumerate(sessions):
        unav = {tuple(u) for u in college.teacher_by_id[l.teacher].unavailable}
        for d in range(n_days):
            for a, b in RUNS:
                for p in range(a, min(b, n_per) - l.duration + 1):
                    if any((d, q) in unav for q in range(p, p + l.duration)):
                        continue
                    for r in l.rooms:
                        v = m.NewBoolVar(f"s{si}_d{d}_p{p}_{r}")
                        x[si, d, p, r] = v
                        by_session[si].append(v)
                        session_day[si].append((d, v))
                        lesson_day[l.id, d].append(v)
                        for q in range(p, p + l.duration):
                            teacher_cover[l.teacher, d, q].append(v)
                            room_cover[r, d, q].append(v)
                            for bt in l.batches:
                                batch_cover[bt, d, q].append(v)

    for si in range(len(sessions)):
        m.AddExactlyOne(by_session[si])
    for table in (teacher_cover, batch_cover, room_cover):
        for vs in table.values():
            if len(vs) > 1:
                m.AddAtMostOne(vs)

    # spread a lesson over the week; symmetry-break identical sessions by day order
    first_session: dict[str, int] = {}
    for si, (l, k) in enumerate(sessions):
        first_session.setdefault(l.id, si)
    for l in lessons:
        unav = {tuple(u) for u in college.teacher_by_id[l.teacher].unavailable}
        avail_days = sum(any((d, p) not in unav for p in range(n_per)) for d in range(n_days))
        cap = 1 if l.sessions <= avail_days else 2
        for d in range(n_days):
            if lesson_day[l.id, d]:
                m.Add(sum(lesson_day[l.id, d]) <= cap)
        if cap == 1 and l.sessions > 1:
            s0 = first_session[l.id]
            day_of = [sum(d * v for d, v in session_day[s0 + k]) for k in range(l.sessions)]
            for k in range(l.sessions - 1):
                m.Add(day_of[k] < day_of[k + 1])

    teachers = {l.teacher for l in lessons}
    batches = sorted({b for l in lessons for b in l.batches})

    def lunch_break(table: dict, who: str, d: int) -> None:
        # at least one free period inside the lunch window (cover per slot is already <= 1)
        vs = [v for q in LUNCH_WINDOW for v in table.get((who, d, q), [])]
        if vs:
            m.Add(sum(vs) <= len(LUNCH_WINDOW) - 1)

    for t in teachers:
        cap = college.teacher_by_id[t].max_per_day
        for d in range(n_days):
            vs = [v for q in range(n_per) for v in teacher_cover.get((t, d, q), [])]
            if vs:
                m.Add(sum(vs) <= cap)
            lunch_break(teacher_cover, t, d)
    for b in batches:
        for d in range(n_days):
            lunch_break(batch_cover, b, d)

    def occupancy(table: dict, who: str, d: int) -> list:
        occ = []
        for q in range(n_per):
            o = m.NewBoolVar("")
            m.Add(o == sum(table.get((who, d, q), [])))
            occ.append(o)
        return occ

    def idle_gaps(o: list) -> list:
        started = [m.NewBoolVar("") for _ in o]
        pending = [m.NewBoolVar("") for _ in o]
        for q in range(len(o)):
            m.AddMaxEquality(started[q], o[: q + 1])
            m.AddMaxEquality(pending[q], o[q:])
        gaps = {}
        for q in range(1, len(o) - 1):
            g = m.NewBoolVar("")
            m.Add(g >= started[q] + pending[q] - o[q] - 1)
            gaps[q] = g
        # one free period inside the lunch window is the lunch break, not idle time
        lunch = m.NewBoolVar("")
        m.Add(lunch <= sum(gaps[q] for q in LUNCH_WINDOW if q in gaps))
        return list(gaps.values()), lunch

    objective = []
    for b in batches:
        for d in range(n_days):
            vs = [v for q in range(n_per) for v in batch_cover.get((b, d, q), [])]
            if vs:
                m.Add(sum(vs) <= MAX_BATCH_PER_DAY)
            if optimize:
                o = occupancy(batch_cover, b, d)
                gaps, lunch = idle_gaps(o)
                objective += [W_STUDENT_GAP * g for g in gaps] + [-W_STUDENT_GAP * lunch]
                lonely = m.NewBoolVar("")
                has = m.NewBoolVar("")
                m.AddMaxEquality(has, o)
                m.Add(lonely >= 2 * has - sum(o))
                objective.append(W_LONELY_DAY * lonely)
    if optimize:
        for t in teachers:
            for d in range(n_days):
                o = occupancy(teacher_cover, t, d)
                gaps, lunch = idle_gaps(o)
                objective += [W_TEACHER_GAP * g for g in gaps] + [-W_TEACHER_GAP * lunch]
                for a, b in RUNS:
                    for q in range(a, min(b, n_per) - 3):
                        streak = m.NewBoolVar("")
                        m.Add(streak >= sum(o[q:q + 4]) - 3)
                        objective.append(W_LONG_STREAK * streak)
        m.Minimize(sum(objective))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = 7
    solver.parameters.log_search_progress = log
    if not optimize:
        solver.parameters.stop_after_first_solution = True
    status = solver.Solve(m)
    name = solver.StatusName(status)
    result = SolveResult(name, seconds=round(time.time() - t0, 1))
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for (si, d, p, r), v in x.items():
            if solver.Value(v):
                l, k = sessions[si]
                result.entries.append(Entry(l.id, k, d, p, l.duration, r))
        result.entries += list(college.fixed_entries)
        if optimize:
            result.objective = solver.ObjectiveValue()
    elif status == cp_model.INFEASIBLE:
        result.problems = ["The rules cannot all be satisfied together. Check teacher availability, "
                           "daily limits and lab room supply."]
    else:
        result.problems = [f"No timetable found within {time_limit:.0f} s; try a longer time limit."]
    return result


if __name__ == "__main__":
    import sys

    from app.seed import build_college
    from app.validator import metrics, validate

    limit = float(sys.argv[1]) if len(sys.argv) > 1 else 30
    college = build_college()
    print(f"{len(college.sections)} sections, {len(college.teachers)} teachers, "
          f"{sum(l.sessions for l in college.lessons)} sessions to place")
    base = solve(college, optimize=False)
    print(f"baseline (first feasible): {base.status} in {base.seconds}s, "
          f"idle/day={metrics(college, base.entries)['idle_per_day'] if base.entries else '-'}")
    res = solve(college, time_limit=limit)
    print(f"optimised: {res.status} in {res.seconds}s objective={res.objective}")
    for p in res.problems:
        print("  problem:", p)
    if res.entries:
        from app.validator import split_issues

        clashes, notes = split_issues(validate(college, res.entries))
        print(f"validator: {len(clashes)} clashes, {len(notes)} quality notes")
        for i in clashes[:10]:
            print("  ", i)
        for label, fx in (("real (imported)", True), ("generated", False)):
            mt = metrics(college, res.entries, fixed=fx)
            print(f"{label:16s}", {k: mt[k] for k in ("idle_per_day", "lonely_days", "no_lunch_days", "long_days", "group_days")})

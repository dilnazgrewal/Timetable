"""Re-optimise a department's REAL (imported) timetable: same lessons, better times.

Kept exactly as the college decided: every lesson's teacher(s), student groups (incl. cross-section
electives and A1/A2 lab groups), weekly hours, durations (2-hour labs) and the kind of room it needs.
Only *when* each session happens, and which room of the right kind it uses, may change. Sessions we
the college's rules keep in place (mentoring, M.Tech/PhD, classes run with other departments) or that sit in
other departments' rooms stay pinned where the college put them, and everything else must fit around them.

College rules (data/<college>/rules.json, see app/rules.py) are constraints too: a "must" rule is never broken
wherever the college's own timetable keeps it, a "prefer" rule is penalised and never broken more often than
the college does.

Rooms: the same rooms the college already uses for these classes (no borrowing of empty rooms), so the
comparison is fair.

Students are real combinations of choices ("student types" from the department's distribution lists:
section + actual group + electives + lab groups), each with the exact classes it attends, so no real
student can ever get two classes at once. Hard rules: no teacher / student type / room double-booking; at most 8 periods a day for a group (D3 groups have
36 periods a week, so the college's full 8:30-17:30 day is allowed); a theory subject at most once a day
where it fits.
Never worse than the college on any measure (its own numbers are hard ceilings): days with no free
midday hour (students and teachers), student waiting periods, teacher days with 4+ lectures in a row,
classes in the 16:30-17:30 slot, days over 6 periods, single-lecture days. Within those ceilings it minimises (weighted): days with no free hour between 11:30 and 14:30 (strongly; making it a hard rule is
infeasible for the real CSE lessons), student waiting gaps, single-lecture days, teacher gaps, teachers
teaching 4+ in a row, periods beyond 6 in a day, classes in the 16:30-17:30 slot, and use of spare rooms.
"""
from __future__ import annotations

import time
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ortools.sat.python import cp_model

from app import rules
from app.models import DAYS, LUNCH_WINDOW, PERIODS, College, Entry, Lesson

DAY_CAP = 8  # periods per group per day
SOFT_DAY = 6  # periods beyond this in a day are penalised
W_GAP, W_LONELY, W_T_GAP, W_STREAK, W_LATE, W_LONG, W_SPARE = 10, 6, 2, 5, 4, 3, 8
W_NO_LUNCH, W_T_NO_LUNCH = 100, 20  # a group / teacher day with no free hour between 11:30 and 14:30
W_PREFER = 30  # each break of a "prefer" college rule


@dataclass
class OptResult:
    status: str
    seconds: float
    entries: list[Entry] = field(default_factory=list)  # optimised placements for every fixed lesson of the dept
    moved: int = 0
    pinned: int = 0
    problems: list[str] = field(default_factory=list)
    score: tuple = ()  # (college score, optimised score, search steps); lower is better


def movable(college: College, l: Lesson, dept: str) -> bool:
    if not l.fixed or l.dept != dept:
        return False
    if any(r.type == "keep_as_published" and r.applies(l, college) for r in college.rules):
        return False  # the college's rules keep it where it is
    return all((r := college.room_by_id.get(rid)) is not None and r.kind != "Other department" for rid in l.rooms)


def optimise_department(college: College, dept: str = "CSE", time_limit: float = 120, workers: int = 8,
                        log: bool = False, spare_rooms: bool = True, relax: frozenset[str] = frozenset(),
                        check_start: bool = False) -> OptResult:
    """spare_rooms: also allow the department's classrooms the college leaves empty all week (each use is
    penalised, so they are only used when that removes waiting gaps or late classes)."""
    t0 = time.time()
    n_days, n_per = len(DAYS), len(PERIODS)
    lessons = [l for l in college.lessons if l.fixed and l.dept == dept]
    move = [l for l in lessons if movable(college, l, dept)]
    move_ids = {l.id for l in move}
    pinned = [e for e in college.fixed_entries if e.lesson not in move_ids and college.lesson_by_id[e.lesson].dept == dept]
    # other departments' classes stay put and share teachers and rooms with this one
    others = [e for e in college.fixed_entries if college.lesson_by_id[e.lesson].dept != dept]
    by_lesson: dict[str, list[Entry]] = defaultdict(list)
    for e in college.fixed_entries:
        if e.lesson in move_ids:
            by_lesson[e.lesson].append(e)
    original = {(lid, k): e for lid, es in by_lesson.items() for k, e in enumerate(sorted(es, key=lambda e: (e.day, e.start)))}
    # never stricter than what the college already does, so its own timetable is a valid starting point
    per_day = {lid: max(sum(e.day == d for e in es) for d in range(len(DAYS))) for lid, es in by_lesson.items()}
    group_day: dict[tuple, int] = defaultdict(int)
    for e in college.fixed_entries:
        if college.lesson_by_id[e.lesson].dept == dept:
            for b in college.lesson_by_id[e.lesson].batches:
                group_day[b, e.day] += e.duration
    day_cap = max([DAY_CAP, *group_day.values()])

    # students = real combinations of choices (student types), each with the exact classes it attends
    dept_ids = {l.id for l in lessons}
    units = [(n, ls) for n, ls in college.units() if ls & dept_ids]
    unit_of: dict[str, list[str]] = defaultdict(list)
    for n, ls in units:
        for lid in ls:
            unit_of[lid].append(n)

    # the rooms the college itself uses for these classes
    used = {r for l in move for r in l.rooms}
    college_rooms = sorted(r for r in used if college.room_by_id[r].kind == "Classroom")
    spare = sorted(r.id for r in college.rooms if spare_rooms and r.dept == dept and r.kind == "Classroom"
                   and r.id not in used and r.bookable)
    classrooms = college_rooms + spare
    small_rooms = sorted(r for r in used if college.room_by_id[r].kind == "Study Area")  # e.g. DEPT LIB, 15 seats
    labs = sorted(r for r in used if college.room_by_id[r].kind == "Computer Lab")

    m = cp_model.CpModel()
    sessions = [(l, k) for l in move for k in range(l.sessions)]
    x: dict[tuple, cp_model.IntVar] = {}  # (si, d, p, room or "") -> bool; theory rooms are assigned afterwards
    by_s: dict[int, list] = defaultdict(list)
    s_day: dict[int, list] = defaultdict(list)
    l_day: dict[tuple, list] = defaultdict(list)
    t_cov: dict[tuple, list] = defaultdict(list)
    g_cov: dict[tuple, list] = defaultdict(list)
    r_cov: dict[tuple, list] = defaultdict(list)
    any_cov: dict[tuple, list] = defaultdict(list)  # sessions needing a (pooled) classroom
    late: list = []
    spare_use: list = []

    # electives that may share a group's students (no lists to tell): never at the same time as its classes
    guard_at: dict[str, set[int]] = defaultdict(set)
    for e in college.fixed_entries:
        guard_at[e.lesson].update(e.day * n_per + q for q in e.slots)
    forbid: dict[str, set[int]] = defaultdict(set)
    for _, mine, guards in college.guarded():
        busy = set().union(*(guard_at[g] for g in guards if g not in move_ids))
        for lid in mine & move_ids:
            forbid[lid] |= busy

    for si, (l, k) in enumerate(sessions):
        unav = {tuple(u) for u in college.teacher_by_id[l.teacher].unavailable}
        # classrooms are pooled (assigned after solving); labs and special rooms are chosen by the model
        if l.room_kind == "Classroom":
            rooms = [""]
        elif l.room_kind == "Computer Lab":
            rooms = [r for r in labs if college.room_by_id[r].capacity >= l.size]
        else:
            rooms = sorted(r for r in used if college.room_by_id[r].kind == l.room_kind)
        for d in range(n_days):
            for p in range(n_per - l.duration + 1):
                if any((d, q) in unav or d * n_per + q in forbid[l.id] for q in range(p, p + l.duration)):
                    continue
                for r in rooms:
                    v = m.NewBoolVar("")
                    x[si, d, p, r] = v
                    by_s[si].append(v)
                    s_day[si].append((d, v))
                    l_day[l.id, d].append(v)
                    if p + l.duration > n_per - 1:
                        late.append(v)
                    for q in range(p, p + l.duration):
                        for t in (l.teacher, *l.co_teachers):
                            t_cov[t, d, q].append(v)
                        for u in unit_of[l.id]:
                            g_cov[u, d, q].append(v)
                        if r:
                            r_cov[r, d, q].append(v)
                        else:
                            any_cov[d, q].append(v)
        if (l, k) and not by_s[si]:
            return OptResult("INFEASIBLE", round(time.time() - t0, 1), problems=[f"{l.code} for {l.section} has no possible slot"])

    # pinned sessions occupy teachers, groups and rooms as constants
    pin_t: dict[tuple, int] = defaultdict(int)
    pin_g: dict[tuple, int] = defaultdict(int)
    pin_r: dict[tuple, int] = defaultdict(int)
    start: dict[tuple, int] = defaultdict(int)  # how often the college itself books each teacher/group/room
    for e in pinned + others + [e for es in by_lesson.values() for e in es]:
        l = college.lesson_by_id[e.lesson]
        fixed = e.lesson not in move_ids
        for q in e.slots:
            keys = [("t", t, e.day, q) for t in (l.teacher, *l.co_teachers)] + [("g", u, e.day, q) for u in unit_of[l.id]]
            if college.room_by_id[e.room].kind != "Other department":
                keys.append(("r", e.room, e.day, q))
            for key in keys:
                start[key] += 1
                if fixed:
                    {"t": pin_t, "g": pin_g, "r": pin_r}[key[0]][key[1:]] += 1

    for si in range(len(sessions)):
        m.AddExactlyOne(by_s[si])
    for tag, table, pins in (("t", t_cov, pin_t), ("g", g_cov, pin_g), ("r", r_cov, pin_r)):
        for key, vs in table.items():  # never double-booked (and never worse where the published data already is)
            m.Add(sum(vs) <= max(0, max(1, start.get((tag, *key), 0)) - pins.get(key, 0)))
    for d in range(n_days if "rooms" not in relax else 0):
        for q in range(n_per):
            busy_cls = sum(pin_r.get((r, d, q), 0) > 0 for r in classrooms)
            busy_own = sum(pin_r.get((r, d, q), 0) > 0 for r in college_rooms)
            if any_cov.get((d, q)):
                m.Add(sum(any_cov[d, q]) <= len(classrooms) - busy_cls)
                if spare:  # every class beyond the college's own rooms costs a little
                    over = m.NewIntVar(0, len(spare), "")
                    m.Add(over >= sum(any_cov[d, q]) - (len(college_rooms) - busy_own))
                    spare_use.append(over)

    # a theory subject at most once a day (twice if it has more sessions than days); identical sessions by day
    first: dict[str, int] = {}
    for si, (l, k) in enumerate(sessions):
        first.setdefault(l.id, si)
    for l in move:
        cap = max(1 if l.sessions <= n_days else 2, per_day.get(l.id, 1))
        if "once_a_day" in relax:
            cap = 9
        for d in range(n_days):
            if l_day[l.id, d]:
                m.Add(sum(l_day[l.id, d]) <= cap)
        if cap == 1 and l.sessions > 1:
            s0 = first[l.id]
            day_of = [sum(d * v for d, v in s_day[s0 + k]) for k in range(l.sessions)]
            for k in range(l.sessions - 1):
                m.Add(day_of[k] < day_of[k + 1])

    # the college's own rules (app/rules.py): "must" = never broken wherever the college's timetable keeps
    # it; "prefer" = penalised, and never broken more often than the college does
    L = college.lesson_by_id
    before = [e for e in college.fixed_entries if L[e.lesson].dept == dept]
    days_before: dict[str, set[int]] = defaultdict(set)
    for e in college.fixed_entries:
        days_before[e.lesson].add(e.day)
    pin_days: dict[str, set[int]] = defaultdict(set)
    for e in pinned:
        pin_days[e.lesson].add(e.day)

    def present(lid: str, d: int):
        if d in pin_days.get(lid, ()):
            return 1
        vs = l_day.get((lid, d), [])
        if not vs:
            return 0
        b = m.NewBoolVar("")
        m.AddMaxEquality(b, vs)
        return b

    count_before: dict[tuple, int] = defaultdict(int)
    count_pin: dict[tuple, int] = defaultdict(int)
    for e in before:
        count_before[e.lesson, e.day] += 1
    for e in pinned:
        count_pin[e.lesson, e.day] += 1
    rule_obj: list = []
    for rule in college.rules:
        if rule.type == "labs_apart":  # e.g. SC Lab A1 / A2: two different days
            for a, b in college.lab_pairs():
                if (rule.applies(L[a]) and rule.applies(L[b]) and (a in move_ids or b in move_ids)
                        and not days_before[a] & days_before[b]):
                    for d in range(n_days):
                        pa, pb = present(a, d), present(b, d)
                        if not (isinstance(pa, int) and isinstance(pb, int)):
                            m.Add(pa + pb <= 1)
        elif rule.type == "nothing_after":  # e.g. JPAL: nothing for its sections after it that day
            terms, fixed_after = [], 0
            for j in pinned:  # the class itself stays where the college has it
                if not rule.applies(L[j.lesson]):
                    continue
                secs, end = rules.sections(L[j.lesson]), j.start + j.duration
                fixed_after += sum(e.day == j.day and e.start >= end and e.lesson != j.lesson
                                   and bool(rules.sections(L[e.lesson]) & secs) for e in pinned)
                terms += [v for (si, d, p, _), v in x.items()
                          if d == j.day and p >= end and rules.sections(sessions[si][0]) & secs]
            if terms:
                m.Add(sum(terms) + fixed_after <= len(rules.breaks(college, rule, before)))
                if rule.strength == "prefer":
                    rule_obj.append(W_PREFER * sum(terms))
        elif rule.type == "real_class_daily":  # every weekday a real lecture or lab, where the college has one
            skip, need = tuple(rule.params.get("not_counting", [])), rule.params.get("min", 1)
            years = rule.match.get("years")
            for _, sec, ls in rules.student_units(college):
                if (years and rules.year_of(sec) not in years) or not any(lid in L and rule.applies(L[lid]) for lid in ls):
                    continue
                real = [lid for lid in ls if lid in L and L[lid].dept == dept and not L[lid].code.startswith(skip)]
                for d in range(n_days):
                    if sum(count_before[lid, d] for lid in real) >= need:
                        m.Add(sum(v for lid in real if lid in move_ids for v in l_day.get((lid, d), []))
                              + sum(count_pin[lid, d] for lid in real) >= need)
        elif rule.type == "allowed_times":  # these lessons only start in the given periods
            ok = set(rule.params.get("periods", []))
            bad = [v for (si, d, p, _), v in x.items() if p not in ok and rule.applies(sessions[si][0])]
            if bad:
                m.Add(sum(bad) <= len(rules.breaks(college, rule, before)))

    groups = sorted(n for n, ls in units if ls & move_ids)  # student types with something to move
    teachers = sorted({t for l in move for t in (l.teacher, *l.co_teachers)})

    def occupancy(table, pins, who, d):
        occ = []
        for q in range(n_per):
            o = m.NewBoolVar("")  # busy (the published data may already double-book someone: still just busy)
            vs, pin = table.get((who, d, q), []), pins.get((who, d, q), 0)
            if pin:
                m.Add(o == 1)
            else:
                m.Add(o == sum(vs))
            occ.append(o)
        return occ

    def gaps_and_lunch(o):
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
        lunch = m.NewBoolVar("")
        m.Add(lunch <= sum(gaps[q] for q in LUNCH_WINDOW if q in gaps))
        return list(gaps.values()), lunch

    obj = [W_LATE * v for v in late] + [W_SPARE * v for v in spare_use] + rule_obj
    # the college's own count of days with no free midday hour is a ceiling we may never exceed
    occ_before: dict[tuple, set[int]] = defaultdict(set)
    for e in college.fixed_entries:  # every department: a teacher's day includes classes they give elsewhere
        l = college.lesson_by_id[e.lesson]
        for who in (*unit_of[l.id], l.teacher, *l.co_teachers):
            occ_before[who, e.day].update(e.slots)
    window_full = lambda who, d: all(q in occ_before.get((who, d), ()) for q in LUNCH_WINDOW)
    g_no_lunch, t_no_lunch_all, g_idle, t_streak_days, g_long, g_lonely = [], [], [], [], [], []

    def run_len(slots: set[int]) -> int:
        best = run = 0
        for q in range(n_per):
            run = run + 1 if q in slots else 0
            best = max(best, run)
        return best

    def idle_of(slots: set[int]) -> int:
        if not slots:
            return 0
        inside = set(range(min(slots), max(slots) + 1)) - slots
        return len(inside) - (1 if inside & set(LUNCH_WINDOW) else 0)
    for g in groups:
        for d in range(n_days):
            o = occupancy(g_cov, pin_g, g, d)
            # a free hour around midday: strongly preferred (a hard rule is infeasible with 36-period weeks)
            no_lunch = m.NewBoolVar("")
            m.Add(no_lunch >= sum(o[q] for q in LUNCH_WINDOW) - (len(LUNCH_WINDOW) - 1))
            obj.append(W_NO_LUNCH * no_lunch)
            g_no_lunch.append(no_lunch)
            if "day_cap" not in relax:
                m.Add(sum(o) <= day_cap)
            gaps, lunch = gaps_and_lunch(o)
            obj += [W_GAP * v for v in gaps] + [-W_GAP * lunch]
            g_idle.append(sum(gaps) - lunch)
            has, lonely, extra = m.NewBoolVar(""), m.NewBoolVar(""), m.NewIntVar(0, n_per, "")
            m.AddMaxEquality(has, o)
            m.Add(lonely >= 2 * has - sum(o))
            m.Add(extra >= sum(o) - SOFT_DAY)
            obj += [W_LONELY * lonely, W_LONG * extra]
            g_lonely.append(lonely)
            is_long = m.NewBoolVar("")
            m.Add(sum(o) - SOFT_DAY <= n_per * is_long)
            g_long.append(is_long)
    for t in teachers:
        for d in range(n_days):
            o = occupancy(t_cov, pin_t, t, d)
            t_no_lunch = m.NewBoolVar("")
            m.Add(t_no_lunch >= sum(o[q] for q in LUNCH_WINDOW) - (len(LUNCH_WINDOW) - 1))
            obj.append(W_T_NO_LUNCH * t_no_lunch)
            t_no_lunch_all.append(t_no_lunch)
            gaps, lunch = gaps_and_lunch(o)
            obj += [W_T_GAP * v for v in gaps] + [-W_T_GAP * lunch]
            day_streak = m.NewBoolVar("")
            for q in range(n_per - 3):
                streak = m.NewBoolVar("")
                m.Add(streak >= sum(o[q:q + 4]) - 3)
                m.Add(day_streak >= streak)
                obj.append(W_STREAK * streak)
            t_streak_days.append(day_streak)
    ceilings: list = []  # never worse than the college (its own numbers)
    ceilings.append(sum(g_no_lunch) <= sum(window_full(g, d) for g in groups for d in range(n_days)))
    ceilings.append(sum(t_no_lunch_all) <= sum(window_full(t, d) for t in teachers for d in range(n_days)))
    ceilings.append(sum(g_idle) <= sum(idle_of(occ_before.get((g, d), set())) for g in groups for d in range(n_days)))
    ceilings.append(sum(t_streak_days) <= sum(run_len(occ_before.get((t, d), set())) >= 4 for t in teachers for d in range(n_days)))
    ceilings.append(sum(late) <= sum(e.start + e.duration > n_per - 1 for e in original.values()))
    ceilings.append(sum(g_long) <= sum(len(occ_before.get((g, d), ())) > SOFT_DAY for g in groups for d in range(n_days)))
    ceilings.append(sum(g_lonely) <= sum(len(occ_before.get((g, d), ())) == 1 for g in groups for d in range(n_days)))
    for i, ceiling in enumerate(ceilings):
        if f"ceiling{i}" not in relax:
            m.Add(ceiling)
    m.Minimize(sum(obj))

    # Large-neighbourhood search from the college's own timetable (it meets every rule and ceiling):
    # free one slice (a year, a few teachers, or two days), re-solve that slice exactly, keep it if better.
    key_of = {v.Index(): key for key, v in x.items()}
    vars_of: dict[int, list] = defaultdict(list)
    for key, v in x.items():
        vars_of[key[0]].append(v)
    choice: dict[int, cp_model.IntVar] = {}
    for (si, d, p, r), v in x.items():
        l, k = sessions[si]
        e = original[(l.id, k)]
        if (e.day, e.start) == (d, p) and (not r or r == e.room):
            choice[si] = v
    res = OptResult("NO_CHANGE", 0.0, pinned=len(pinned))
    if len(choice) != len(sessions):
        res.status, res.problems = "INVALID_START", ["The college's timetable doesn't fit the model."]
        return res

    def solve_with(free: set[int], seconds: float):
        sub = m.clone()
        for si, v in choice.items():
            sv = sub.get_bool_var_from_proto_index(v.Index())
            if si in free:
                sub.AddHint(sv, 1)
            else:
                sub.Add(sv == 1)
        sol = cp_model.CpSolver()
        sol.parameters.num_workers = workers
        sol.parameters.random_seed = 7
        sol.parameters.log_search_progress = log
        sol.parameters.max_time_in_seconds = seconds
        return sol.Solve(sub), sol, sub

    st, sol, _ = solve_with(set(), 30)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        res.status, res.problems = "INVALID_START", ["The college's timetable doesn't meet the model's rules."]
        return res
    best = start_obj = sol.ObjectiveValue()
    if check_start:
        print(f"college timetable: valid, score {start_obj:.0f}", flush=True)
    year_of = {si: sessions[si][0].batches[0].split("-", 1)[0] for si in range(len(sessions))}
    rng = __import__("random").Random(7)
    it = improved = 0
    while time.time() - t0 < time_limit - 5:
        mode = it % 3
        if mode == 0:  # one year group (D1..D4)
            yr = ["D1", "D2", "D3", "D4"][(it // 3) % 4]
            free = {si for si in range(len(sessions)) if year_of[si] == yr}
        elif mode == 1:  # a handful of teachers and everything they teach
            pick = set(rng.sample(teachers, min(8, len(teachers))))
            free = {si for si, (l, _) in enumerate(sessions) if pick & {l.teacher, *l.co_teachers}}
        else:  # everything currently on two days
            days = set(rng.sample(range(n_days), 2))
            free = {si for si, v in choice.items() if key_of[v.Index()][1] in days}
        st, sol, sub = solve_with(free, min(25.0, time_limit - (time.time() - t0)))
        it += 1
        if st in (cp_model.OPTIMAL, cp_model.FEASIBLE) and sol.ObjectiveValue() < best - 0.5:
            best = sol.ObjectiveValue()
            improved += 1
            for si in free:
                choice[si] = next(v for v in vars_of[si] if sol.Value(sub.get_bool_var_from_proto_index(v.Index())))
            if log or check_start:
                print(f"  step {it}: score {best:.0f}", flush=True)
    res.status = "IMPROVED" if improved else "NO_CHANGE"
    res.seconds = round(time.time() - t0, 1)
    res.problems = [] if improved else ["No better timetable found in the time given."]
    res.score = (start_obj, best, it)
    placed: list[tuple[Lesson, int, int, int, str]] = []
    for si, v in choice.items():
        _, d, p, r = key_of[v.Index()]
        l, k = sessions[si]
        placed.append((l, k, d, p, r))
    # rooms: labs come from the model; theory rooms are assigned per day with a small exact model
    # (prefer the room the class had before), using only rooms the college uses and small rooms only
    # for classes the college itself puts there
    blocked = {(e.room, e.day, q) for e in pinned + others for q in e.slots}
    theory_rooms: dict[tuple, str] = {}
    for d in range(n_days):
        today = [(i, t) for i, t in enumerate(placed) if t[2] == d and not t[4]]
        if not today:
            continue
        rm = cp_model.CpModel()
        z: dict[tuple, cp_model.IntVar] = {}
        cover: dict[tuple, list] = defaultdict(list)
        keep = []
        for i, (l, k, _, p, _) in today:
            allowed = classrooms
            opts = [r for r in allowed if all((r, d, q) not in blocked for q in range(p, p + l.duration))]
            for r in opts:
                z[i, r] = rm.NewBoolVar("")
                for q in range(p, p + l.duration):
                    cover[r, q].append(z[i, r])
                if r == original[(l.id, k)].room:
                    keep.append(3 * z[i, r])
                elif r not in spare:
                    keep.append(z[i, r])
            rm.AddExactlyOne([z[i, r] for r in opts])
        for vs in cover.values():
            rm.AddAtMostOne(vs)
        rm.Maximize(sum(keep))
        rs = cp_model.CpSolver()
        rs.parameters.max_time_in_seconds = 10
        if rs.Solve(rm) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            res.status, res.problems = "ROOM_ASSIGNMENT_FAILED", [f"Rooms could not be assigned on {DAYS[d]}"]
            return res
        for (i, r), v in z.items():
            if rs.Value(v):
                theory_rooms[i] = r
    for i, (l, k, d, p, r) in enumerate(placed):
        res.entries.append(Entry(l.id, k, d, p, l.duration, r or theory_rooms[i]))
        e = original[(l.id, k)]
        res.moved += (e.day, e.start) != (d, p)
    res.entries += pinned
    return res


def department_college(college: College, dept: str = "CSE") -> College:
    """Just one department's imported lessons (for validating / measuring one timetable on its own)."""
    sub = College(college.departments, college.rooms, college.teachers,
                  [x for x in college.sections if x.dept == dept],
                  [l for l in college.lessons if l.fixed and l.dept == dept], college.buildings)
    sub.set_student_types([t for t in college.student_types if t.section in sub.section_by_id])
    sub.rules = college.rules
    return sub


OUT = Path(__file__).resolve().parent.parent / "data" / "gndec" / "cse_optimised.json"


def out_path(dept: str) -> Path:
    return OUT.with_name(f"{dept.lower()}_optimised.json")


def refresh_pins(college: College, dept: str = "CSE", path: Path | None = None) -> dict | None:
    """After a re-import changed only classes nobody may move (e.g. a duplicate first-year class removed): keep the
    saved optimised times of every movable class, take the fixed ones from the college as it is now, and
    measure again. Returns None (re-run needed) if a movable class changed."""
    path = path or out_path(dept)
    if not path.exists():
        return None
    saved = json.loads(path.read_text(encoding="utf-8"))
    L = college.lesson_by_id
    moving = [Entry(**e) for e in saved["entries"] if e["lesson"] in L and movable(college, L[e["lesson"]], dept)]
    if Counter(e.lesson for e in moving) != Counter(e.lesson for e in college.fixed_entries
                                                     if e.lesson in L and movable(college, L[e.lesson], dept)):
        return None
    pinned = [e for e in college.fixed_entries if L[e.lesson].dept == dept and not movable(college, L[e.lesson], dept)]
    res = OptResult(saved["status"], saved["seconds"], moving + pinned, saved["moved"], len(pinned),
                    score=tuple(saved.get("score", ())))
    return save(college, res, dept, path)


def add_new_pins(college: College, dept: str = "CSE", path: Path | None = None) -> dict | None:
    """After a re-import found more classes nobody may move (e.g. open electives taught in another department),
    put them into the saved optimised timetable as published and measure it again. No re-solve: the independent
    validator says whether the saved timetable still fits around them."""
    path = path or out_path(dept)
    if not path.exists():
        return None
    saved = json.loads(path.read_text(encoding="utf-8"))
    entries = [Entry(**e) for e in saved["entries"] if e["lesson"] in college.lesson_by_id]
    have = {e.lesson for e in entries}
    new = [e for e in college.fixed_entries if e.lesson not in have and college.lesson_by_id[e.lesson].dept == dept]
    res = OptResult(saved["status"], saved["seconds"], entries + new, saved["moved"], saved["pinned"] + len(new),
                    score=tuple(saved.get("score", ())))
    return save(college, res, dept, path)


def save(college: College, res: OptResult, dept: str = "CSE", path: Path | None = None) -> dict:
    """Store the optimised timetable next to the imported one, with before/after numbers."""
    from app.validator import metrics, split_issues, validate

    sub = department_college(college, dept)
    before = [e for e in college.fixed_entries if college.lesson_by_id[e.lesson].dept == dept]
    out = {"dept": dept, "status": res.status, "seconds": res.seconds, "moved": res.moved, "pinned": res.pinned,
           "score": list(res.score), "entries": [asdict(e) for e in res.entries], "metrics": {}, "clashes": {}}
    for label, entries in (("college", before), ("optimised", res.entries)):
        mt = metrics(sub, entries)
        mt.pop("teacher_load", None)
        out["metrics"][label] = mt
        out["clashes"][label] = len(split_issues(validate(sub, entries))[0])
    out["rules"] = {r["id"]: {"college": r["college"], "optimised": r["optimised"]}
                    for r in rules.report(college, before, res.entries)}
    (path or out_path(dept)).write_text(json.dumps(out), encoding="utf-8")
    return out


if __name__ == "__main__":
    import sys

    from app.seed import build_college
    from app.validator import metrics, split_issues, validate

    limit = float(sys.argv[1]) if len(sys.argv) > 1 else 120
    which = [a.upper() for a in sys.argv[2:]] or ["CSE"]
    c = build_college()
    if which == ["ALL"]:
        which = sorted({l.dept for l in c.lessons if l.fixed})
    for dept in which:
        print(f"===== {dept}", flush=True)
        res = optimise_department(c, dept, limit, check_start=True)
        print(res.status, res.seconds, "s ·", len(res.entries), "entries ·", res.moved, "moved ·", res.pinned, "pinned", res.problems)
        if res.entries:
            sub = department_college(c, dept)
            before = [e for e in c.fixed_entries if c.lesson_by_id[e.lesson].dept == dept]
            for label, entries in (("college", before), ("optimised", res.entries)):
                clashes, notes = split_issues(validate(sub, entries))
                mt = metrics(sub, entries)
                print(f"{label:10s} clashes={len(clashes)} notes={len(notes)}",
                      {k: mt[k] for k in ("idle_total", "worst_gap", "lonely_days", "no_lunch_days", "long_days",
                                          "teacher_streak_days", "teacher_no_lunch_days", "teacher_idle_total", "late_sessions")})
                for cl in clashes[:5]:
                    print("   ", cl)
            if res.status == "IMPROVED":
                save(c, res, dept)
                print("saved ->", out_path(dept), flush=True)

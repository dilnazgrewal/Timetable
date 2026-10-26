"""Proves the "0 clashes" claim: the solver output passes the independent validator, and the
validator itself catches every kind of injected clash (testing the tester)."""
from dataclasses import replace

import pytest

from app.models import LUNCH_WINDOW, PERIODS, Entry
from app.seed import SEED_DEPTS, _build_seed
from app.solver import prechecks, solve
from app.validator import split_issues, validate


@pytest.fixture(scope="module")
def college():
    return _build_seed(SEED_DEPTS)  # every department generated (the real ones are imported, see test_core_*)


@pytest.fixture(scope="module")
def entries(college):
    res = solve(college, optimize=False, time_limit=30)
    assert res.entries, res.problems
    return res.entries


def generated_units(college):
    """Student types whose classes we generate (not imported)."""
    return {name for name, lessons in college.units() if lessons and not any(college.lesson_by_id[l].fixed for l in lessons)}


def mentions(issue, names):
    return any(f" {n} on " in issue or f" {n} has " in issue or f" {n} at " in issue for n in names)


def test_solver_output_has_no_clashes(college, entries):
    clashes, notes = split_issues(validate(college, entries))
    assert clashes == []
    # quality notes may only come from imported (real) data, never from what we generated
    mine = generated_units(college)
    assert not [n for n in notes if mentions(n, mine)]


def test_every_session_placed_once(college, entries):
    assert len(entries) == sum(l.sessions for l in college.lessons)


def _first(entries, college, kind):
    return next(e for e in entries if college.lesson_by_id[e.lesson].kind == kind)


def test_detects_student_and_teacher_clash(college, entries):
    # two classes the same real students attend (same student type)
    lessons_of = [ls for _, ls in college.units()]
    a = _first(entries, college, "theory")
    b = next(e for e in entries if e is not a and e.duration == 1 and e.lesson != a.lesson
             and any(a.lesson in ls and e.lesson in ls for ls in lessons_of))
    mutated = [replace(a, day=b.day, start=b.start) if e is a else e for e in entries]
    assert any(i.startswith("CLASH Students") for i in validate(college, mutated))


def test_detects_room_clash(college, entries):
    labs = [e for e in entries if college.lesson_by_id[e.lesson].kind == "lab"]
    a, b = labs[0], next(e for e in labs[1:] if college.lesson_by_id[e.lesson].room_kind
                         == college.lesson_by_id[labs[0].lesson].room_kind and e.room != labs[0].room)
    mutated = [replace(b, room=a.room, day=a.day, start=a.start) if e is b else e for e in entries]
    assert any(i.startswith("CLASH Room") for i in validate(college, mutated))


def test_detects_block_past_end_of_day(college, entries):
    lab = _first(entries, college, "lab")
    mutated = [replace(lab, start=len(PERIODS) - 1) if e is lab else e for e in entries]
    assert any("past the end of the day" in i for i in validate(college, mutated))


def test_every_generated_group_gets_lunch(college, entries):
    mine = generated_units(college)
    assert not [i for i in validate(college, entries) if i.startswith("NO LUNCH") and mentions(i, mine)]


def test_detects_missing_lunch(college):
    sec = next(s for s in college.sections if any(not l.fixed and l.batches == s.batches for l in college.lessons))
    theory = [l for l in college.lessons if l.batches == sec.batches and l.kind == "theory"][:3]
    packed = [Entry(l.id, 0, 0, p, 1, l.rooms[0]) for l, p in zip(theory, LUNCH_WINDOW)]
    assert any(i.startswith("NO LUNCH Students") for i in validate(college, packed))


def test_detects_unavailable_teacher(college, entries):
    visiting = next(t for t in college.teachers if t.kind == "Visiting")
    e0 = next(e for e in entries if college.lesson_by_id[e.lesson].teacher == visiting.id)
    mutated = [replace(e0, day=0) if e is e0 else e for e in entries]  # Monday: unavailable
    assert any("unavailable" in i for i in validate(college, mutated))


def test_detects_missing_session(college, entries):
    assert any("sessions placed" in i for i in validate(college, entries[1:]))


def test_detects_wrong_room_type(college, entries):
    lab = _first(entries, college, "lab")
    mutated = [replace(lab, room="LT-1") if e is lab else e for e in entries]
    assert any("needs a" in i for i in validate(college, mutated))


def test_precheck_explains_overloaded_teacher():
    c = _build_seed(SEED_DEPTS)
    t = next(t for t in c.teachers if t.kind == "Visiting")
    t.unavailable = [(d, p) for d in range(5) for p in range(len(PERIODS)) if d != 1]  # only Tuesday left
    t.max_per_day = 3  # 4 hours assigned, at most 3 possible
    msgs = prechecks(c)
    assert any(t.name in m and "assigned" in m for m in msgs)


def test_unknown_lesson_flagged(college):
    assert validate(college, [Entry("nope", 0, 0, 0, 1, "LT-1")])

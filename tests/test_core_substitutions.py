"""Absences and substitutions: candidates are really free, assigning changes only that date, permissions."""
import pytest

import app.store as store_mod
import app.substitutions as subs
from app.auth import authorize, demo_people
from app.seed import build_college
from app.solver import solve
from app.store import Store

DAY = "2026-10-30"  # a Friday
NEXT = "2026-11-06"  # the Friday after


@pytest.fixture(scope="module")
def solved():
    college = build_college()
    res = solve(college, optimize=False, time_limit=30)
    assert res.entries
    return college, res.entries


@pytest.fixture
def store(solved, tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "STATE", tmp_path / "state.json")
    college, entries = solved
    s = Store(college)
    s.users, s.clubs = demo_people(college)
    s.publish({"status": "TEST", "seconds": 0, "entries": [e.__dict__ for e in entries]})
    monkeypatch.setattr(store_mod, "STORE", s)
    monkeypatch.setattr(subs, "STORE", s)
    return s


def busiest_teacher(store, weekday=4):
    counts = {}
    for o in store.week():
        if o.day == weekday and not o.co_teachers:
            counts[o.teacher] = counts.get(o.teacher, 0) + 1
    return max(counts, key=counts.get)


def test_leave_lists_classes_with_free_candidates(store):
    t = busiest_teacher(store)
    subs.mark_leave(t, DAY, [], "Sick", "admin")
    rows = subs.affected(t, DAY)
    assert rows and all(r["state"] in ("open", "covered") for r in rows)
    occ = store.effective(DAY)
    for r in [r for r in rows if r["state"] == "open"]:
        assert r["candidates"], "someone should be free"
        slots = range(r["start"], r["start"] + r["duration"])
        for c in r["candidates"]:
            assert c["teacher"] != t
            busy = {p for o in occ if c["teacher"] in (o.teacher, *o.co_teachers) for p in o.slots}
            assert not busy & set(slots)
        scores = [c["score"] for c in r["candidates"]]
        assert scores == sorted(scores, reverse=True)


def test_assign_substitute_only_changes_that_date(store):
    t = busiest_teacher(store)
    subs.mark_leave(t, DAY, [], "", "admin")
    row = next(r for r in subs.affected(t, DAY) if r["state"] == "open")
    sub = row["candidates"][0]["teacher"]
    subs.assign(DAY, row["key"], sub, False, "admin")
    o = next(o for o in store.effective(DAY) if o.key == row["key"])
    assert (o.teacher, o.status) == (sub, "substituted")
    assert next(o for o in store.effective(NEXT) if o.key == row["key"]).teacher == t
    after = next(r for r in subs.affected(t, DAY) if r["key"] == row["key"])
    assert after["state"] == "substituted" and after["by"] == sub
    # re-deciding replaces the earlier decision: cancel it instead
    subs.assign(DAY, row["key"], None, True, "admin")
    assert all(o.key != row["key"] for o in store.effective(DAY))
    assert sum(ov.entry_key == row["key"] for ov in store.overrides) == 1


def test_substitute_is_not_offered_twice_at_the_same_time(store):
    t = busiest_teacher(store)
    rows = subs.affected(t, DAY)
    row = next(r for r in rows if r["state"] == "open")
    sub = row["candidates"][0]["teacher"]
    subs.assign(DAY, row["key"], sub, False, "admin")
    o = next(o for o in store.week() if o.key == row["key"])
    assert sub not in {c["teacher"] for c in subs.candidates(o, subs.to_date(DAY), t, limit=10_000)}


def test_permissions(store):
    c = store.college
    u = store.users
    t = next(t for t in c.teachers if t.dept == "CSE" and f"t-{t.id}" in u)
    other = next(x for x in c.teachers if x.dept == "CSE" and x.id != t.id and f"t-{x.id}" in u)
    assert authorize(u[f"t-{t.id}"], "leave.mark", t)  # yourself
    assert not authorize(u[f"t-{other.id}"], "leave.mark", t)  # not a colleague
    assert authorize(u["hod-CSE"], "leave.mark", t)
    assert not authorize(u["hod-ME"], "leave.mark", t)
    assert authorize(u["hod-CSE"], "override.create", "CSE")
    assert not authorize(u["hod-ME"], "override.create", "CSE")
    student = next(x for x in u.values() if x.role == "student")
    assert not authorize(student, "override.create", "CSE")

"""Store: effective(date) = base timetable ⊕ that date's overrides, and permission rules."""
import pytest

import app.store as store_mod
from app.auth import authorize, demo_people
from app.models import BookingRequest, Entry, Override
from app.seed import build_college
from app.solver import solve
from app.store import Store, entry_key

FRIDAY = "2026-10-23"
SATURDAY = "2026-10-24"


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
    return s


def test_effective_matches_weekday_and_weekend(store):
    friday = [e for e in store.entries if e.day == 4]
    assert len(store.effective(FRIDAY)) == len(friday)
    assert store.effective(SATURDAY) == []


def test_cancel_substitute_and_room_change(store):
    e = next(e for e in store.entries if e.day == 4)
    k = entry_key(e)
    store.add_override(Override("o1", FRIDAY, "substitute", entry_key=k, teacher="T99"))
    assert next(o for o in store.effective(FRIDAY) if o.key == k).status == "substituted"
    store.add_override(Override("o2", FRIDAY, "room_change", entry_key=k, room="LT-1"))
    assert next(o for o in store.effective(FRIDAY) if o.key == k).room == "LT-1"
    store.add_override(Override("o3", FRIDAY, "cancel", entry_key=k))
    assert all(o.key != k for o in store.effective(FRIDAY))
    # the base weekly timetable is untouched, and other Fridays are unaffected
    assert any(entry_key(x) == k for x in store.entries)
    assert any(o.key == k for o in store.effective("2026-10-30"))


def test_booking_occupies_room_only_on_that_date(store):
    store.add_override(Override("b1", FRIDAY, "booking", periods=[5, 6], room="WS SEMINAR HALL", title="DMC talk"))
    busy = store.busy_rooms(store.effective(FRIDAY), 5)
    assert busy["WS SEMINAR HALL"].kind == "booking"
    assert "WS SEMINAR HALL" not in store.busy_rooms(store.effective("2026-10-30"), 5)


def test_permissions(store, monkeypatch):
    monkeypatch.setattr(store_mod, "STORE", store)
    u = store.users
    student = next(x for x in u.values() if x.role == "student")
    assert not authorize(student, "timetable.generate")
    assert not authorize(u["hod-CSE"], "timetable.generate")  # regenerating: timetable office only
    assert authorize(u["admin"], "timetable.generate")
    req = BookingRequest("r1", "Talk", "club-DMC", "DMC", 100, ["projector"], FRIDAY, [5], "MBA Seminar Hall")
    advisor = store.clubs["DMC"].advisor
    assert authorize(u[advisor], "booking.endorse", req)
    assert not authorize(u["club-DMC"], "booking.endorse", req)
    assert authorize(u["hod-CSE"], "booking.approve", req)  # MBA Seminar Hall belongs to CSE
    assert not authorize(u["hod-ME"], "booking.approve", req)
    central = BookingRequest("r2", "Fest", "club-DMC", "DMC", 500, ["sound"], FRIDAY, [5], "Auditorium")
    assert not authorize(u["hod-CSE"], "booking.approve", central)  # central halls: admin only
    assert authorize(u["admin"], "booking.approve", central)

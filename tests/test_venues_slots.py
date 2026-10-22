"""Event slot finder: never a slot where any chosen group has a class; venues attached; lunch protected."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import app.store as store_mod
from app.main import app
from app.models import LUNCH_WINDOW, Entry, Override
from app.store import STORE


def next_weekday(weekday: int = 0) -> str:
    d = date.today() + timedelta(days=1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d.isoformat()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "STATE", tmp_path / "state.json")
    for name in ("overrides", "bookings", "meetings", "notifications"):
        monkeypatch.setattr(STORE, name, [])
    return TestClient(app)


@pytest.fixture
def section_and_lesson():
    """A section plus a lesson that involves at least one of its groups."""
    for sec in STORE.college.sections:
        lesson = next((l for l in STORE.college.lessons if set(l.batches) & set(sec.batches)), None)
        if lesson:
            return sec, lesson
    pytest.skip("no lessons in the current college data")


def find(client, user="org-TNP", **body):
    return client.post("/api/venues/slot-finder", json=body, headers={"X-User": user})


def assert_no_clash(result):
    aud = set(result["audience"]["groups"]) | set(result["audience"]["sections"])
    for slot in result["slots"]:
        for o in STORE.effective(slot["date"]):
            if set(o.batches) & aud:
                assert not set(o.slots) & set(slot["periods"]), f"{slot['when']} clashes with {o.title}"


def test_never_returns_a_slot_where_a_group_has_class(client, monkeypatch, section_and_lesson):
    sec, lesson = section_and_lesson
    monday = next_weekday(0)
    monkeypatch.setattr(STORE, "entries", [Entry(lesson.id, 0, 0, 0, 2, "ANY"), Entry(lesson.id, 1, 0, 6, 1, "ANY")])
    res = find(client, sections=[sec.id], duration=1, **{"from": monday}, to=monday)
    assert res.status_code == 200, res.text
    body = res.json()
    taken = {p for s in body["slots"] for p in s["periods"]}
    assert not taken & {0, 1, 6}
    assert taken, "the rest of the day is free"
    assert_no_clash(body)
    # a class for just one of the groups still blocks the whole audience
    one = next(g for g in sec.batches if g in lesson.batches)
    body = find(client, groups=[one], duration=2, **{"from": monday}, to=monday).json()
    assert all(not {0, 1, 6} & set(s["periods"]) for s in body["slots"])
    assert_no_clash(body)


def test_cancelled_class_frees_the_slot(client, monkeypatch, section_and_lesson):
    sec, lesson = section_and_lesson
    monday = next_weekday(0)
    monkeypatch.setattr(STORE, "entries", [Entry(lesson.id, 0, 0, 0, 2, "ANY")])
    before = find(client, sections=[sec.id], duration=2, **{"from": monday}, to=monday).json()
    assert [0, 1] not in [s["periods"] for s in before["slots"]]
    STORE.add_override(Override("c1", monday, "cancel", entry_key=f"{lesson.id}#0"))
    after = find(client, sections=[sec.id], duration=2, **{"from": monday}, to=monday).json()
    assert [0, 1] in [s["periods"] for s in after["slots"]]


def test_slots_come_with_venues_and_lunch_warning(client, monkeypatch, section_and_lesson):
    sec, lesson = section_and_lesson
    monday = next_weekday(0)
    a, b, last = LUNCH_WINDOW[0], LUNCH_WINDOW[1], LUNCH_WINDOW[-1]
    monkeypatch.setattr(STORE, "entries", [Entry(lesson.id, 0, 0, a, b - a + 1, "ANY")])  # all but the last lunch period
    body = find(client, sections=[sec.id], duration=1, attendees=50, needs=["projector"],
                **{"from": monday}, to=monday).json()
    lunch = next(s for s in body["slots"] if s["periods"] == [last])
    assert any("lunch" in w for w in lunch["warnings"])
    other = next(s for s in body["slots"] if last not in s["periods"])
    assert not any("lunch" in w for w in other["warnings"])
    for s in body["slots"]:
        for v in s["venues"]:
            assert v["capacity"] >= 50 and "projector" in v["features"]
    # earliest first within the day, except lunch-eating slots go after the others
    assert body["slots"].index(lunch) > body["slots"].index(other)


def test_real_timetable_dept_year(client):
    sec, monday = STORE.college.sections[0], next_weekday(0)
    friday = (date.fromisoformat(monday) + timedelta(days=4)).isoformat()
    res = find(client, dept=sec.dept, year=sec.year, duration=2, **{"from": monday}, to=friday)
    assert res.status_code == 200
    assert set(sec.batches) <= set(res.json()["audience"]["groups"])
    assert_no_clash(res.json())


def test_permissions_and_bad_input(client):
    sec = STORE.college.sections[0]
    assert find(client, "club-DMC", dept=sec.dept, year=sec.year).status_code == 403
    student = next(u for u in STORE.users.values() if u.role == "student")
    assert find(client, student.id, dept=sec.dept, year=sec.year).status_code == 403
    assert find(client, duration=2).status_code == 400  # no audience
    assert find(client, groups=["nope"]).status_code == 400
    assert find(client, dept=sec.dept, year=sec.year, duration=99).status_code == 400

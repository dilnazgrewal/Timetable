"""Venue ranking: only free bookable rooms, best fit first, near-misses explained."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import app.store as store_mod
from app.main import app
from app.models import Entry, Override
from app.store import STORE


def next_weekday(weekday: int = 4) -> str:
    d = date.today() + timedelta(days=1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d.isoformat()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "STATE", tmp_path / "state.json")
    for name in ("overrides", "bookings", "meetings", "notifications"):
        monkeypatch.setattr(STORE, name, [])
    return TestClient(app, headers={"X-User": "admin"})  # every call below names its own account


def rank(client, **body):
    return client.post("/api/venues/rank", json=body, headers={"X-User": "club-DMC"})


def test_fits_are_free_big_enough_and_closest_first(client):
    on = next_weekday()
    res = rank(client, date=on, periods=[4, 5], attendees=100, needs=["projector", "sound"])
    assert res.status_code == 200
    venues = res.json()["venues"]
    assert venues, "some bookable room should fit 100 people with projector and sound"
    occ = STORE.effective(on)
    for v in venues:
        assert v["capacity"] >= 100 and {"projector", "sound"} <= set(v["features"])
        assert all(v["id"] not in STORE.busy_rooms(occ, p) for p in (4, 5))
        assert v["reason"].startswith(f"Seats {v['capacity']} for 100 people · has projector and sound")
    assert venues[0]["capacity"] == min(v["capacity"] for v in venues)
    assert all(not m["fits"] and m["reason"] for m in res.json()["near_misses"])


def test_room_with_a_class_is_not_offered(client, monkeypatch):
    on = next_weekday(0)
    room = next(r for r in STORE.college.rooms if r.bookable)
    lesson = STORE.college.lessons[0]
    monkeypatch.setattr(STORE, "entries", [Entry(lesson.id, 0, 0, 2, 2, room.id)])  # a Monday class, P3-P4
    res = rank(client, date=on, periods=[3, 4], attendees=1, needs=[]).json()
    assert room.id not in [v["id"] for v in res["venues"]]
    assert "Busy in P3–P4: class" in next(m for m in res["near_misses"] if m["id"] == room.id)["reason"]
    assert room.id in [v["id"] for v in rank(client, date=on, periods=[5], attendees=1, needs=[]).json()["venues"]]


def test_booking_override_takes_room_out(client):
    on = next_weekday()
    first = rank(client, date=on, periods=[6], attendees=100, needs=[]).json()["venues"][0]["id"]
    STORE.add_override(Override("ov-test", on, "booking", periods=[6], room=first, title="Test event"))
    res = rank(client, date=on, periods=[6], attendees=100, needs=[]).json()
    assert first not in [v["id"] for v in res["venues"]]
    miss = next(m for m in res["near_misses"] if m["id"] == first)
    assert "booked for Test event" in miss["reason"]


def test_too_small_and_missing_features_are_explained(client):
    res = rank(client, date=next_weekday(), periods=[1], attendees=5000, needs=["stage"]).json()
    assert res["venues"] == []
    assert any("Too small" in m["reason"] for m in res["near_misses"])


@pytest.mark.parametrize("body, msg", [
    ({"date": "2026-10-24", "periods": [1], "attendees": 10}, "weekend"),
    ({"date": next_weekday(), "periods": [1, 3], "attendees": 10}, "back to back"),
    ({"date": next_weekday(), "periods": [1], "attendees": 10, "needs": ["jacuzzi"]}, "Unknown requirement"),
    ({"date": "2020-01-06", "periods": [1], "attendees": 10}, "past"),
])
def test_bad_input_gets_plain_400(client, body, msg):
    res = rank(client, **body)
    assert res.status_code == 400 and msg in res.json()["detail"]

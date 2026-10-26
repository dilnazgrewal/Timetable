"""Booking requests: club → faculty advisor → HOD, wrong approvers get 403, approved rooms leave Free rooms."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import app.store as store_mod
from app.main import app
from app.store import STORE

PERIODS = [4, 5]


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
    return TestClient(app)


@pytest.fixture
def hall():
    """A department-owned bookable hall (MBA Seminar Hall in the demo data)."""
    rooms = [r for r in STORE.college.rooms if r.bookable and r.dept]
    return next((r for r in rooms if r.id == "MBA Seminar Hall"), max(rooms, key=lambda r: r.capacity))


def call(client, user, method, path, **kw):
    return client.request(method, path, headers={"X-User": user}, **kw)


def ask(client, user, room, on=None, periods=PERIODS, attendees=100):
    return call(client, user, "POST", "/api/venues/requests", json={
        "title": "Digital Marketing Workshop", "purpose": "Hands-on SEO session", "attendees": attendees,
        "needs": ["projector"], "date": on or next_weekday(), "periods": periods, "room": room})


def decide(client, user, req_id, decision="approved", note=""):
    return call(client, user, "POST", f"/api/venues/requests/{req_id}/decide",
                json={"decision": decision, "note": note})


def free_room_ids(client, on, period):
    return {r["id"] for r in client.get(f"/api/free-rooms?on={on}&period={period}").json()["free"]}


def notes(user):
    return [n.text for n in STORE.notifications if n.user == user]


def test_club_request_advisor_then_hod_then_room_leaves_free_rooms(client, hall):
    on, advisor, hod = next_weekday(), STORE.clubs["DMC"].advisor, f"hod-{hall.dept}"
    assert hall.id in free_room_ids(client, on, PERIODS[0])

    res = ask(client, "club-DMC", hall.id, on)
    assert res.status_code == 200, res.text
    req = res.json()["request"]
    assert req["status"] == "pending" and req["club"] == "DMC"
    assert [s["role"] for s in req["steps"]] == ["advisor", "hod"]
    assert any("Please endorse" in t for t in notes(advisor))
    assert [r["id"] for r in call(client, advisor, "GET", "/api/venues/requests?inbox=1").json()["items"]] == [req["id"]]
    assert call(client, hod, "GET", "/api/venues/requests?inbox=1").json()["items"] == []

    # the HOD can't skip the advisor, and the club can't approve itself
    assert decide(client, hod, req["id"]).status_code == 403
    assert decide(client, "club-DMC", req["id"]).status_code == 403

    req = decide(client, advisor, req["id"], note="Good idea").json()["request"]
    assert req["status"] == "endorsed" and req["step_role"] == "hod"
    assert any("Please approve" in t for t in notes(hod))
    assert any("Endorsed" in t for t in notes("club-DMC"))
    assert decide(client, advisor, req["id"]).status_code == 403  # advisor can't give final approval
    other_hod = next(u.id for u in STORE.users.values() if u.role == "hod" and u.dept != hall.dept)
    assert decide(client, other_hod, req["id"]).status_code == 403

    req = decide(client, hod, req["id"]).json()["request"]
    assert req["status"] == "approved"
    assert any("Approved" in t for t in notes("club-DMC"))
    for p in PERIODS:
        assert hall.id not in free_room_ids(client, on, p)
    mine = call(client, "club-DMC", "GET", "/api/venues/requests").json()["items"]
    assert mine[0]["id"] == req["id"] and mine[0]["timeline"][-1]["label"].startswith("Booked")

    # cancelling gives the room back
    assert call(client, advisor, "POST", f"/api/venues/requests/{req['id']}/cancel").status_code == 403
    res = call(client, "club-DMC", "POST", f"/api/venues/requests/{req['id']}/cancel")
    assert res.json()["request"]["status"] == "cancelled"
    assert hall.id in free_room_ids(client, on, PERIODS[0])


def test_rejection_needs_a_reason_and_tells_the_club(client, hall):
    req = ask(client, "club-DMC", hall.id).json()["request"]
    advisor = STORE.clubs["DMC"].advisor
    assert decide(client, advisor, req["id"], "rejected").status_code == 400
    res = decide(client, advisor, req["id"], "rejected", "Clashes with mid-sems")
    assert res.json()["request"]["status"] == "rejected"
    assert any("Clashes with mid-sems" in t for t in notes("club-DMC"))
    assert decide(client, f"hod-{hall.dept}", req["id"]).status_code == 409


def test_central_room_goes_to_admin_and_teacher_skips_advisor(client):
    central = next(r for r in STORE.college.rooms if r.bookable and r.dept is None)
    req = ask(client, "club-DMC", central.id).json()["request"]
    assert [s["role"] for s in req["steps"]] == ["advisor", "admin"]
    teacher = next(u for u in STORE.users.values() if u.role == "teacher")
    req = ask(client, teacher.id, central.id, periods=[1]).json()["request"]
    assert [(s["role"], s["approver"]) for s in req["steps"]] == [("admin", "admin")]
    assert [r["id"] for r in call(client, "admin", "GET", "/api/venues/requests?inbox=1").json()["items"]] == [req["id"]]
    any_hod = next(u.id for u in STORE.users.values() if u.role == "hod")
    assert decide(client, any_hod, req["id"]).status_code == 403  # central rooms: admin only
    assert decide(client, "admin", req["id"]).json()["request"]["status"] == "approved"


def test_final_approval_refused_if_room_was_taken_meanwhile(client, hall):
    on, hod = next_weekday(), f"hod-{hall.dept}"
    first = ask(client, "org-TNP", hall.id, on).json()
    second = ask(client, "org-visitor", hall.id, on).json()
    assert second["warnings"], "a double request for the same slot should warn"
    assert decide(client, hod, first["request"]["id"]).json()["request"]["status"] == "approved"
    res = decide(client, hod, second["request"]["id"])
    assert res.status_code == 409 and "no longer free" in res.json()["detail"]
    # and a fresh request for the now-booked slot is refused up front
    assert ask(client, "club-DMC", hall.id, on).status_code == 409


def test_who_may_request(client, hall):
    student = next(u for u in STORE.users.values() if u.role == "student")
    assert ask(client, student.id, hall.id).status_code == 403
    assert ask(client, "club-DMC", "no-such-room").status_code == 400


def test_event_audience_hears_about_approval_and_cancellation(client, hall):
    sec = next(s for s in STORE.college.sections if s.batches)
    students = [u.id for u in STORE.users.values() if u.role == "student" and u.group in sec.batches]
    outsider = next(u.id for u in STORE.users.values() if u.role == "student" and u.group not in sec.batches)
    body = {"title": "Placement talk", "attendees": 60, "needs": [], "date": next_weekday(),
            "periods": PERIODS, "room": hall.id}
    bad = call(client, "org-TNP", "POST", "/api/venues/requests", json={**body, "audience": ["no-such-group"]})
    assert bad.status_code == 400
    req = call(client, "org-TNP", "POST", "/api/venues/requests", json={**body, "audience": sec.batches}).json()["request"]
    assert req["audience"] == sec.batches and req["audience_label"] == sec.name
    assert not any(notes(s) for s in students)  # nothing until it's approved
    decide(client, f"hod-{hall.dept}", req["id"])
    assert students and all(any("Event for your batch" in t for t in notes(s)) for s in students)
    assert not notes(outsider)
    call(client, "org-TNP", "POST", f"/api/venues/requests/{req['id']}/cancel")
    assert all(any("Cancelled" in t for t in notes(s)) for s in students)

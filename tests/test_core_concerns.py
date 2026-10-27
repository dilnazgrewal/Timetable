"""Students' timetable concerns: only real ones (a class the student actually has), one record per class problem with
classmates' votes, counted per class for staff without names, answered by the right department, students notified."""
import pytest
from fastapi.testclient import TestClient

import app.store as store_mod
from app.main import app
from app.store import STORE

ME, MATE = "s-D4-CS-A:A2:CV:SCA1:TA3", "s-D4-CS-A:A1:CV:SCA1:TA2"  # D4 CS A: both have the Monday 8:30 open elective
OTHER_SECTION = next(u for u in STORE.users if u.startswith("s-D4-CS-B"))


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "STATE", tmp_path / "state.json")
    saved, notes = list(STORE.concerns), list(STORE.notifications)
    STORE.concerns.clear()
    yield
    STORE.concerns[:], STORE.notifications[:] = saved, notes


def as_(uid):
    return TestClient(app, headers={"X-User": uid})


def raise_(uid, **body):
    return as_(uid).post("/api/concerns", json=body)


def test_a_concern_is_about_a_class_the_student_really_has():
    r = raise_(ME, reason="early", day=0, period=0, text="My bus from Khanna reaches at 9:10")
    assert r.status_code == 200 and "Open elective" in r.json()["concern"]["class"]
    assert raise_(ME, reason="early", day=1, period=0).status_code == 400  # no class on Tuesday at 8:30
    assert raise_(ME, reason="early").status_code == 400  # which class?
    assert raise_(ME, reason="no_break").status_code == 400  # which day?
    assert raise_(ME, reason="nonsense").status_code == 400
    assert raise_("t-KC", reason="other").status_code == 403  # students only
    assert raise_("hod-CSE", reason="other").status_code == 403
    assert raise_("admin", reason="other").status_code == 403  # the timetable office sees and answers, never raises
    assert raise_("dean", reason="other").status_code == 403
    can = as_("admin").get("/api/me").json()["can"]
    assert not can["raise_concerns"] and can["view_concerns"] and can["answer_concerns"]


def test_classmates_add_votes_instead_of_duplicates():
    raise_(ME, reason="early", day=0, period=0)
    r = raise_(MATE, reason="early", day=0, period=0)
    assert r.json()["merged"] and r.json()["concern"]["votes"] == 2 and len(STORE.concerns) == 1
    raise_(MATE, reason="early", day=0, period=0)  # voting twice changes nothing
    assert len(STORE.concerns[0].voters) == 2
    cid = STORE.concerns[0].id
    assert as_(MATE).post(f"/api/concerns/{cid}/vote?agree=false").json()["concern"]["votes"] == 1  # take it back
    assert as_(OTHER_SECTION).post(f"/api/concerns/{cid}/vote").status_code == 404  # another section's concern


def test_staff_see_counts_per_class_never_names():
    raise_(ME, reason="early", day=0, period=0, text="traffic")
    raise_(MATE, reason="early", day=0, period=0)
    items = as_("hod-CSE").get("/api/concerns").json()["items"]
    assert len(items) == 1 and items[0]["votes"] == 2 and 0 < items[0]["share"] <= 1
    assert not any(k in items[0] for k in ("voters", "created_by", "agreed"))  # nobody's identity
    assert as_("hod-IT").get("/api/concerns").json()["items"] == []  # another department's concerns
    assert len(as_("admin").get("/api/concerns").json()["items"]) == 1
    assert len(as_("dean").get("/api/concerns").json()["items"]) == 1
    assert as_(ME).get("/api/concerns").status_code == 403


def test_the_department_answers_and_everyone_who_agreed_hears_back():
    raise_(ME, reason="early", day=0, period=0)
    raise_(MATE, reason="early", day=0, period=0)
    cid = STORE.concerns[0].id
    assert as_("hod-IT").post(f"/api/concerns/{cid}/answer", json={"status": "planned"}).status_code == 403
    assert as_("dean").post(f"/api/concerns/{cid}/answer", json={"status": "planned"}).status_code == 403  # read-only
    r = as_("coord-CSE").post(f"/api/concerns/{cid}/answer", json={"status": "planned", "reply": "From next week"})
    assert r.status_code == 200 and r.json()["concern"]["status"] == "planned"
    for uid in (ME, MATE):
        assert any("From next week" in n["text"] for n in as_(uid).get("/api/notifications").json()["items"])
    assert as_(ME).get("/api/concerns/mine").json()["items"][0]["reply"] == "From next week"


def test_a_student_can_have_at_most_five_open_concerns():
    week = [o for o in STORE.week() if o.kind == "class" and STORE.attends(ME[2:], o)]
    slots = sorted({(o.day, o.start) for o in week})
    for reason, (d, p) in zip(["early", "late", "gap", "streak", "early"], slots[:5]):
        assert raise_(ME, reason=reason, day=d, period=p).status_code == 200
    d, p = slots[5]
    assert raise_(ME, reason="gap", day=d, period=p).status_code == 429

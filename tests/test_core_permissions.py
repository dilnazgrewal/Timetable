"""Role-based access: sign-in, the permission table, capabilities and the endpoints that enforce them."""
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import app.store as store_mod
from app.auth import PERMISSIONS, authorize, capabilities, current_user
from app.main import app
from app.models import BookingRequest
from app.store import STORE


@pytest.fixture(autouse=True)
def temp_state(tmp_path, monkeypatch):
    """Never write data/state.json; undo anything a test publishes or logs."""
    monkeypatch.setattr(store_mod, "STATE", tmp_path / "state.json")
    published, audit, notes = dict(STORE.published), list(STORE.audit), list(STORE.notifications)
    yield
    if STORE.published != published:
        STORE.set_published("CSE", published.get("CSE"))
    STORE.audit[:], STORE.notifications[:] = audit, notes


def u(uid):
    return STORE.users[uid]


def first(role, dept=None):
    return next(x for x in STORE.users.values() if x.role == role and (dept is None or x.dept == dept))


def as_(uid):
    return TestClient(app, headers={"X-User": uid})


# --- sign-in -----------------------------------------------------------------------------------------
def test_every_api_route_needs_sign_in_except_auth():
    open_routes = []
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path.startswith("/api") and not r.path.startswith("/api/auth/"):
            deps = {d.call for d in r.dependant.dependencies}
            deps |= {sub.call for d in r.dependant.dependencies for sub in d.dependencies}
            if current_user not in deps:
                open_routes.append(r.path)
    assert open_routes == []


@pytest.mark.parametrize("path", ["/api/meta", "/api/me", "/api/timetable", "/api/free-rooms", "/api/notifications"])
def test_no_sign_in_is_401(path):
    assert TestClient(app).get(path).status_code == 401


def test_session_sign_in_and_out():
    c = TestClient(app)
    assert c.get("/api/auth/demo-accounts").status_code == 200
    assert c.post("/api/auth/demo-login", json={"user": "nobody"}).status_code == 404
    assert c.post("/api/auth/demo-login", json={"user": "dean"}).status_code == 200
    me = c.get("/api/me").json()
    assert me["id"] == "dean" and me["can"]["audit"] and not me["can"]["publish"]
    c.post("/api/auth/logout")
    assert c.get("/api/me").status_code == 401


# --- the permission table ------------------------------------------------------------------------------
def test_admin_may_do_everything_and_unknown_actions_are_refused():
    assert all(authorize(u("admin"), a) for a in PERMISSIONS)
    assert not authorize(u("admin"), "no.such.action")


def test_college_wide_actions_are_admin_only():
    for uid in ["dean", "hod-CSE", "coord-CSE", first("teacher").id, first("student").id, "club-DMC", "org-TNP"]:
        for action in ["timetable.generate", "timetable.publish", "accounts.view", "demo.reset"]:
            assert not authorize(u(uid), action), (uid, action)


def test_department_staff_only_manage_their_own_department():
    for uid in ["hod-CSE", "coord-CSE"]:
        for action in ["optimise.view", "optimise.run", "optimise.propose", "override.create"]:
            assert authorize(u(uid), action, "CSE")
            assert not authorize(u(uid), action, "ME")
    assert not authorize(u("hod-ME"), "optimise.view", "CSE")
    student, teacher = first("student", "CSE"), first("teacher", "CSE")
    for x in (student, teacher):
        assert not authorize(x, "optimise.view", "CSE") and not authorize(x, "override.create", "CSE")


def test_dean_reads_but_never_changes():
    dean = u("dean")
    for action in ["optimise.view", "insights.view", "audit.view", "timetable.view"]:
        assert authorize(dean, action, "CSE")
    for action in ["optimise.run", "optimise.propose", "override.create", "timetable.publish", "meeting.request"]:
        assert not authorize(dean, action, "CSE")


def test_leave_rules():
    t = STORE.college.teacher_by_id[u("hod-CSE").teacher_id]
    other = next(x for x in STORE.college.teachers if x.dept == "CSE" and x.id != t.id)
    me = u(f"t-{other.id}")
    assert authorize(me, "leave.mark", other) and not authorize(me, "leave.mark", t)
    assert authorize(u("hod-CSE"), "leave.mark", other) and authorize(u("coord-CSE"), "leave.mark", other)
    assert not authorize(u("hod-ME"), "leave.mark", other)
    assert authorize(u("dean"), "leave.view", other) and not authorize(u("dean"), "leave.mark", other)


def test_venue_approval_goes_to_the_rooms_hod():
    room = next(r for r in STORE.college.rooms if r.dept == "CSE")
    req = BookingRequest(id="t1", title="Talk", requester="club-DMC", club="DMC", attendees=40, needs=[],
                         date="2026-10-28", periods=[2], room=room.id)
    assert authorize(u("hod-CSE"), "booking.approve", req)
    assert not authorize(u("hod-ME"), "booking.approve", req)
    assert not authorize(u("coord-CSE"), "booking.approve", req)
    advisor = STORE.clubs["DMC"].advisor
    assert authorize(u(advisor), "booking.endorse", req) and not authorize(u("club-DMC"), "booking.endorse", req)
    assert authorize(u("club-DMC"), "booking.cancel", req) and not authorize(u("club-CODE"), "booking.cancel", req)


def test_capabilities_follow_the_table():
    student, admin = capabilities(first("student", "CSE")), capabilities(u("admin"))
    assert student["request_meeting"] and student["my_timetable"] and student["free_rooms"]
    assert not any(student[k] for k in ["optimised_view", "publish", "generate", "audit", "substitutions", "approve_venues"])
    assert all(v for k, v in admin.items() if k not in ("my_timetable", "reply_meetings", "mark_own_leave"))  # not a teacher
    hod = capabilities(u("hod-CSE"))
    assert hod["optimised_propose"] and hod["substitutions"] and not hod["publish"]
    assert capabilities(u("hod-ME"))["optimised_view"]  # ME's own optimised timetable, never CSE's
    assert authorize(u("hod-ME"), "optimise.view", "ME") and not authorize(u("hod-ME"), "optimise.view", "CSE")


# --- endpoints enforce it ------------------------------------------------------------------------------
def test_endpoint_refusals():
    student = first("student", "CSE").id
    assert as_(student).get("/api/compare/cse").status_code == 403
    assert as_(student).get("/api/users").status_code == 403
    assert as_(student).get("/api/audit").status_code == 403
    assert as_(student).post("/api/demo/reset").status_code == 403
    assert as_("hod-ME").get("/api/compare/cse").status_code == 403
    assert as_("hod-CSE").post("/api/compare/cse/publish").status_code == 403
    assert as_("dean").post("/api/compare/cse/propose").status_code == 403
    assert as_("dean").get("/api/compare/cse").status_code == 200
    assert as_(student).get(f"/api/students/{u(student).student_type}/timetable").status_code == 200


def test_refusals_are_audited():
    student = first("student", "CSE").id
    as_(student).post("/api/demo/reset")
    last = STORE.audit[-1]
    assert last["user"] == student and last["action"] == "demo.reset" and last["allowed"] is False
    assert as_("dean").get("/api/audit").json()["items"][0] == last


def _clashes():
    """The validator's clashes for the whole college, order-free (published data already has a few)."""
    out = set()
    for c in STORE.result["issues"]:
        if c.startswith("CLASH"):
            head, ids = c.split(": ", 1)
            out.add((head, frozenset(ids.split(", "))))
    return out


def test_propose_publish_unpublish_adds_no_clash():
    data = as_("hod-CSE").get("/api/compare/cse").json()
    if not data.get("available"):
        pytest.skip("no optimised CSE timetable saved")
    before = _clashes()
    assert as_("coord-CSE").post("/api/compare/cse/propose").json()["publication"]["status"] == "proposed"
    assert any("proposed" in n.text for n in STORE.notifications if n.user == "admin")
    r = as_("admin").post("/api/compare/cse/publish")
    assert r.status_code == 200 and r.json()["publication"]["status"] == "published"
    assert _clashes() <= before  # the independent validator agrees: nothing new anywhere in the college
    assert as_("admin").post("/api/compare/cse/unpublish").json()["publication"]["status"] == "draft"
    assert _clashes() == before


def test_timetable_route_reports_published_clashes_apart():
    """The dashboards read this: clashes TimeWeave causes (none) apart from those already in the college's data."""
    r = as_("hod-CSE").get("/api/timetable")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] and body["issues"] == [] and body["entries"]
    assert all(c.startswith("CLASH Teacher") for c in body["published_issues"])

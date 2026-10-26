"""Lane B: /api/dash views, teacher free slots, meeting requests and their permissions.

Runs against a freshly solved seed college (not data/solution.json), with state saved to a temp file.
"""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import app.api.dashboards as dash
import app.store as store_mod
from app.auth import demo_people
from app.main import app
from app.models import Override
from app.seed import build_college
from app.solver import solve
from app.store import Store


def next_weekday(wd: int) -> str:
    d = date.today() + timedelta(days=1)
    while d.weekday() != wd:
        d += timedelta(days=1)
    return d.isoformat()


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
    monkeypatch.setattr(store_mod, "STORE", s)  # auth looks STORE up here
    monkeypatch.setattr(dash, "STORE", s)  # the dashboards router imported it by name
    return s


@pytest.fixture
def client(store):
    # signed in as the timetable office by default; tests pass their own X-User (accepted in demo mode)
    return TestClient(app, headers={"X-User": "admin"})


def as_(user: str) -> dict:
    return {"X-User": user}


def a_student(store):
    """A student (one student type) with both whole-section classes and single-group classes on Mondays."""
    def ok(t):
        mine = [o for o in store.week() if o.day == 0 and store.attends(t, o)]
        return any(len(o.batches) > 1 for o in mine) and any(len(o.batches) == 1 for o in mine)
    return next(u for u in store.users.values() if u.role == "student" and ok(u.student_type))


def busy_teacher(store):
    """A teacher with a 't-' account who teaches on Mondays, and that teacher's Monday."""
    t = next(t for t in store.college.teachers if any(o.teacher == t.id and o.day == 0 for o in store.week()))
    return t, next_weekday(0)


def test_student_view_shows_exactly_their_classes(client, store):
    s = a_student(store)
    items = client.get(f"/api/dash/views?student={s.student_type}", headers=as_(s.id)).json()["items"]
    expected = {o.key for o in store.week() if store.attends(s.student_type, o)}
    assert items and {i["key"] for i in items} == expected
    # whole-section classes and their own lab / elective groups are in
    assert any(len(i["batches"]) > 1 for i in items)
    assert any(len(i["batches"]) == 1 for i in items)
    assert client.get("/api/dash/views?student=NOPE").status_code == 404


def test_types_sharing_a_group_number_can_differ(client, store):
    """FET group numbers are re-used across electives: two types in one section see different weeks."""
    by_section: dict[str, list[str]] = {}
    for t in store.college.student_types:
        by_section.setdefault(t.section, []).append(t.id)
    weeks = [{i["key"] for i in client.get(f"/api/dash/views?student={t}").json()["items"]}
             for ts in by_section.values() if len(ts) > 1 for t in ts[:2]]
    if not weeks:
        pytest.skip("no section with more than one student type in this data")
    assert weeks[0] != weeks[1]


def test_section_year_and_dept_views_nest(client, store):
    sec = store.college.sections[0]
    get = lambda q: client.get("/api/dash/views?" + q).json()["items"]
    student = next(t.id for t in store.college.student_types if t.section == sec.id)
    group = {i["key"] for i in get(f"student={student}")}
    section = {i["key"] for i in get(f"section={sec.id}")}
    year = {i["key"] for i in get(f"dept={sec.dept}&year={sec.year}")}
    dept = {i["key"] for i in get(f"dept={sec.dept}")}
    assert group < section <= year <= dept
    assert len(dept) < len(store.week())


def test_every_department_has_a_view(client, store):
    for d in store.college.departments:
        assert client.get(f"/api/dash/views?dept={d.code}").json()["items"], d.code


def test_teacher_and_room_views(client, store):
    t, _ = busy_teacher(store)
    items = client.get(f"/api/dash/views?teacher={t.id}").json()["items"]
    assert items and all(i["teacher"] == t.id for i in items)
    room = items[0]["room"]
    assert all(i["room"] == room for i in client.get(f"/api/dash/views?room={room}").json()["items"])


def test_week_of_returns_monday_to_friday(client, store):
    r = client.get("/api/dash/views?week_of=2026-10-24").json()  # a Saturday -> the next week
    assert r["mode"] == "week_of" and r["dates"][0] == "2026-10-26" and len(r["dates"]) == 5
    assert len(r["items"]) == len(store.week())


def test_free_slots_exclude_teaching_and_unavailable(client, store):
    t, monday = busy_teacher(store)
    day = client.get(f"/api/dash/teacher/{t.id}/free?on={monday}").json()
    teaching = {p for o in store.effective(monday) if o.teacher == t.id for p in o.slots}
    off = {p for d, p in t.unavailable if d == 0}
    free = {p["period"] for p in day["free"]}
    assert free and not free & (teaching | off)
    assert free | teaching | off == set(range(len(day["periods"])))
    assert client.get(f"/api/dash/teacher/{t.id}/free?on=2026-10-24").json()["weekend"]
    assert client.get("/api/dash/teacher/NOPE/free").status_code == 404


def test_meeting_round_trip_and_permissions(client, store):
    s = a_student(store)
    t, monday = busy_teacher(store)
    teacher_user = f"t-{t.id}"
    day = client.get(f"/api/dash/teacher/{t.id}/free?on={monday}").json()
    free, busy = day["free"][0]["period"], next(p["period"] for p in day["periods"] if p["state"] == "teaching")

    # only free periods can be asked for, and only by students
    assert client.post("/api/dash/meetings", json={"teacher": t.id, "date": monday, "period": busy},
                       headers=as_(s.id)).status_code == 409
    body = {"teacher": t.id, "date": monday, "period": free, "note": "doubt"}
    assert client.post("/api/dash/meetings", json=body, headers=as_(teacher_user)).status_code == 403
    r = client.post("/api/dash/meetings", json=body, headers=as_(s.id))
    assert r.status_code == 200
    mid = r.json()["id"]
    assert client.post("/api/dash/meetings", json=body, headers=as_(s.id)).status_code == 409  # no duplicates

    # the teacher is notified and sees it in their inbox
    assert any(n.user == teacher_user for n in store.notifications)
    assert client.get("/api/dash/meetings", headers=as_(teacher_user)).json()["pending"] == 1
    assert client.get("/api/dash/meetings", headers=as_(s.id)).json()["sent"][0]["id"] == mid

    # a student (even the one who asked) cannot reply; another teacher cannot either
    reply = {"status": "accepted", "reply": "staff room"}
    assert client.post(f"/api/dash/meetings/{mid}/reply", json=reply, headers=as_(s.id)).status_code == 403
    other = next(u for u in store.users.values() if u.role == "teacher" and u.teacher_id != t.id)
    assert client.post(f"/api/dash/meetings/{mid}/reply", json=reply, headers=as_(other.id)).status_code == 403

    r = client.post(f"/api/dash/meetings/{mid}/reply", json=reply, headers=as_(teacher_user))
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert any(n.user == s.id and "accepted" in n.text for n in store.notifications)
    # an accepted meeting takes that slot off the teacher's free list
    day = client.get(f"/api/dash/teacher/{t.id}/free?on={monday}").json()
    assert day["periods"][free]["state"] == "meeting"
    assert store_mod.STATE.exists()  # saved to the temp file, not data/


def test_now_card(client, store):
    s = a_student(store)
    monday = next_weekday(0)
    mine = sorted((o for o in store.effective(monday) if store.attends(s.student_type, o)), key=lambda o: o.start)
    first = mine[0]
    r = client.get(f"/api/dash/now?on={monday}&period={first.start}", headers=as_(s.id)).json()
    assert r["now"]["key"] == first.key
    assert r["next"] is None or r["next"]["start"] > first.start
    before = client.get(f"/api/dash/now?on={monday}&period=-1", headers=as_(s.id)).json()
    assert before["now"] is None and before["next"]["key"] == first.key
    assert client.get("/api/dash/now", headers=as_("admin")).json()["who"] is None


def co_taught(store):
    """A co-teacher, one class they co-teach (not as the main teacher), and a date it happens on."""
    o = next(o for o in store.week() if o.co_teachers)
    return o.co_teachers[0], o, next_weekday(o.day)


def test_co_taught_labs_count_as_busy(client, store):
    co, o, on = co_taught(store)
    assert any(i["key"] == o.key for i in client.get(f"/api/dash/views?teacher={co}").json()["items"])
    day = client.get(f"/api/dash/teacher/{co}/free?on={on}").json()
    assert all(day["periods"][p]["state"] == "teaching" for p in o.slots)


def test_leave_blocks_free_slots_and_now_card(client, store):
    co, o, on = co_taught(store)
    store.add_override(Override("lv1", on, "leave", teacher=co))  # no periods = the whole day
    day = client.get(f"/api/dash/teacher/{co}/free?on={on}").json()
    assert {p["state"] for p in day["periods"]} == {"leave"} and day["free"] == []
    user = next(u for u in store.users.values() if u.teacher_id == co)
    card = client.get(f"/api/dash/now?on={on}&period={o.start}", headers=as_(user.id)).json()
    assert len(card["leave"]) == len(day["periods"]) and card["now"] is None and card["free"] is None


def test_substituted_class_names_both_teachers(client, store):
    s = a_student(store)
    on = next_weekday(0)
    o = next(o for o in store.effective(on) if store.attends(s.student_type, o) and o.teacher)
    sub = next(t.id for t in store.college.teachers if t.id != o.teacher)
    store.add_override(Override("sub1", on, "substitute", entry_key=o.key, teacher=sub))
    item = next(i for i in client.get(f"/api/dash/views?student={s.student_type}&on={on}").json()["items"] if i["key"] == o.key)
    assert item["status"] == "substituted" and item["teacher"] == sub
    assert item["regular_teacher_name"] == store.college.teacher_by_id[o.teacher].name


def test_dashboards_need_sign_in(store):
    assert TestClient(app).get("/api/dash/views").status_code == 401


def test_dean_is_read_only(client, store):
    t, monday = busy_teacher(store)
    assert client.get(f"/api/dash/views?teacher={t.id}", headers=as_("dean")).json()["items"]
    free = client.get(f"/api/dash/teacher/{t.id}/free?on={monday}", headers=as_("dean")).json()["free"][0]["period"]
    body = {"teacher": t.id, "date": monday, "period": free}
    assert client.post("/api/dash/meetings", json=body, headers=as_("dean")).status_code == 403

"""FET importer: GNDEC's real CSE timetable round-trips faithfully and validates clash-free."""
from pathlib import Path

import pytest

from app.importers.fet import OUTSIDE_ROOM, _parse_groups, _parse_teachers, _subject, add_groups_html, parse_rooms_html
from app.models import College, Entry, Lesson, Room, Section, Teacher
from app.validator import split_issues, validate

RAW = Path(__file__).resolve().parent.parent / "data" / "gndec" / "raw" / "rooms.html"


@pytest.fixture(scope="module")
def data():
    return parse_rooms_html(RAW.read_text(encoding="utf-8-sig"))


def as_college(d):
    return College([], [Room(**r) for r in d["rooms"]],
                   [Teacher(**{**t, "unavailable": []}) for t in d["teachers"]],
                   [Section(**s) for s in d["sections"]], [Lesson(**l) for l in d["lessons"]])


def test_matches_published_room_page(data):
    # cse.gndec.ac.in rooms timetable (Jul-Dec 2026, w.e.f. 19/08/2026): G17 is busy in 30 of 45 slots
    g17 = {(e["day"], p) for e in data["entries"] if e["room"] == "G17"
           for p in range(e["start"], e["start"] + e["duration"])}
    assert len(g17) == 30
    assert {"G17", "S218", "SL-I LAB", "WS SEMINAR HALL"} <= {r["id"] for r in data["rooms"]}


def test_sections_groups_and_labs(data):
    secs = {s["id"]: s for s in data["sections"]}
    assert secs["D2-CS-A"]["groups"] == ["D2-CS-A-A1", "D2-CS-A-A2"]
    assert len(secs["D3-CS-A"]["groups"]) == 6  # elective sub-groups 1-6
    labs = [l for l in data["lessons"] if l["kind"] == "lab"]
    assert labs and all(l["duration"] == 2 for l in labs)
    assert any(l["co_teachers"] for l in data["lessons"])  # labs with 2-3 teachers


def test_real_timetable_has_no_clashes(data):
    college = as_college(data)
    clashes, notes = split_issues(validate(college, [Entry(**e) for e in data["entries"]]))
    assert clashes == []
    assert all(n.startswith(("NO LUNCH", "LONG DAY")) for n in notes)


def test_cell_parsers():
    assert _parse_groups("D3 CS A1, D3 CS B1") == [("D3-CS-A", "A1", "D3 CS A1"), ("D3-CS-B", "B1", "D3 CS B1")]
    assert _parse_groups("D2 CS D") == [("D2-CS-D", "", "D2 CS D")]
    t = _parse_teachers("Dr. Daljit Singh (DS), Pf. Pragya (App. Sci.), Pf. Jashandeep Singh (JDS-CE)")
    assert [(i, d) for i, _, d in t] == [("DS", "CSE"), ("AS-Pragya", "AS"), ("CE-JDS", "CE")]
    assert _subject("DS Lab P") == ("DS Lab", "Data Structures Lab", "lab")
    assert _subject("TOC L")[:2] == ("TOC", "Theory of Computation")
    assert _subject("CV E(T)")[1] == "Computer Vision (elective)"


def test_groups_page_adds_open_elective_and_two_room_class():
    d = parse_rooms_html(RAW.read_text(encoding="utf-8-sig"))
    assert not any(l["code"] == "OE-II" for l in d["lessons"])  # the rooms page can't show it
    added = add_groups_html(d, RAW.with_name("groups.html").read_text(encoding="utf-8-sig"))
    assert len(added) == 4 and not any("Self Study" in a for a in added)
    oe = next(l for l in d["lessons"] if l["code"] == "OE-II")
    d4 = [g for s in d["sections"] if s["id"].startswith("D4-CS-") for g in s["groups"]]
    assert oe["batches"] == sorted(d4) and oe["sessions"] == 3 and oe["fixed"]
    when = sorted((e["day"], e["start"], e["room"]) for e in d["entries"] if e["lesson"] == oe["id"])
    assert when == [(0, 0, OUTSIDE_ROOM.id), (2, 0, OUTSIDE_ROOM.id), (4, 0, OUTSIDE_ROOM.id)]  # Mon, Wed, Fri 8:30
    mc = [e for e in d["entries"] if e["day"] == 3 and e["start"] == 2 and e["room"] == "S202"]
    assert len(mc) == 1  # D1 CS C mentoring, held in S202 + S203
    assert split_issues(validate(as_college(d), [Entry(**e) for e in d["entries"]]))[0] == []


def test_open_elective_is_pinned_and_in_d4_timetables():
    from app.optimise import movable
    from app.store import STORE

    c = STORE.college
    oe = next(l for l in c.lessons if l.code == "OE-II")
    assert not movable(c, oe, "CSE")
    d4 = [t for t in c.student_types if t.section.startswith("D4-CS-")]
    assert d4 and all(oe.id in t.lessons for t in d4)
    assert OUTSIDE_ROOM.id in c.room_by_id


def test_outside_room_is_never_a_free_room():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app, headers={"X-User": "admin"})
    for p in (0, 4):
        free = client.get(f"/api/free-rooms?day=1&period={p}").json()["free"]
        assert free and OUTSIDE_ROOM.id not in {r["id"] for r in free}

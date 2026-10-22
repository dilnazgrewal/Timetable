"""FET importer: GNDEC's real CSE timetable round-trips faithfully and validates clash-free."""
from pathlib import Path

import pytest

from app.importers.fet import _parse_groups, _parse_teachers, _subject, parse_rooms_html
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
    assert [(i, d) for i, _, d in t] == [("DS", "CSE"), ("AS-Pragya", "AS"), ("JDS", "CE")]
    assert _subject("DS Lab P") == ("DS Lab", "Data Structures Lab", "lab")
    assert _subject("TOC L")[:2] == ("TOC", "Theory of Computation")
    assert _subject("CV E(T)")[1] == "Computer Vision (elective)"

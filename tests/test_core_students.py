"""Student types: real combinations of section + actual group + electives + lab groups (GNDEC lists)."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from app.importers.gndec_students import OUT
from app.main import app
from app.models import DAYS, Entry
from app.seed import build_college
from app.validator import split_issues, validate

MY_TYPE = "D4-CS-A:A2:CV:SCA1:TA3"  # D4 CS A, actual group A2, Computer Vision, Soft Computing (A1 lab group), TA A3


@pytest.fixture(scope="module")
def college():
    return build_college()


def test_saved_combinations_hold_no_personal_data():
    raw = OUT.read_text(encoding="utf-8")
    assert not re.search(r"\b\d{7}\b", raw), "no CRN / URN numbers"
    data = json.loads(raw)
    for year in ("D3", "D4"):
        for c in data[year]:
            assert set(c) <= {"section", "actual", "elective_iii", "elective_iv", "elective_iv_lab", "ta_lab",
                              "elective", "elective_section", "elective_lab", "count"}
    assert sum(c["count"] for c in data["D4"]) == 150
    assert sum(c["count"] for c in data["D3"]) == 340


def test_every_class_has_its_students(college):
    for year in ("D3", "D4"):  # CSE: from the distribution lists
        attended = {lid for t in college.student_types if t.section.startswith(year) for lid in t.lessons}
        real = {l.id for l in college.lessons if l.fixed and l.dept == "CSE" and any(b.startswith(year + "-") for b in l.batches)}
        assert real <= attended
    # other departments: every class of a regular section (not an elective audience) has a student type
    attended = {lid for t in college.student_types for lid in t.lessons}
    regular = {l.id for l in college.lessons if l.fixed and l.dept != "CSE"
               and all(college.section_by_id[b.rsplit("-", 1)[0]].kind == "section" for b in l.batches)}
    assert regular <= attended


def test_a_real_student_sees_only_their_electives(college):
    t = college.type_by_id[MY_TYPE]
    codes = {college.lesson_by_id[l].code for l in t.lessons}
    assert {"CV", "SC", "SC Lab A1", "TA Lab"} <= codes
    assert not codes & {"DWDM", "DAAA", "SDN", "ACC", "WT", "SC Lab A2"}  # other options / the other lab group


def test_college_timetable_has_no_clash_for_any_real_student(college):
    clashes, _ = split_issues(validate(college, college.fixed_entries + _generated(college)))
    assert not [c for c in clashes if c.startswith("CLASH Students")]


def test_validator_catches_a_clash_between_two_electives_one_student_takes(college):
    # put a Soft Computing class on top of a Computer Vision class: a real clash for CV + SC students
    entries = list(college.fixed_entries)
    cv = next(e for e in entries if college.lesson_by_id[e.lesson].code == "CV")
    sc = next(e for e in entries if college.lesson_by_id[e.lesson].code == "SC")
    entries[entries.index(sc)] = Entry(sc.lesson, sc.session, cv.day, cv.start, sc.duration, sc.room)
    clashes, _ = split_issues(validate(college, entries + _generated(college)))
    assert any(c.startswith("CLASH Students") and "CV" in c and "SC" in c for c in clashes)


def test_student_timetable_api():
    client = TestClient(app, headers={"X-User": f"s-{MY_TYPE}"})
    assert TestClient(app).get(f"/api/students/{MY_TYPE}/timetable").status_code == 401  # signed-in users only
    r = client.get(f"/api/students/{MY_TYPE}/timetable")
    assert r.status_code == 200
    codes = {i["code"] for i in r.json()["items"]}
    assert "CV" in codes and "SC" in codes and "DWDM" not in codes
    assert all(0 <= i["day"] < len(DAYS) for i in r.json()["items"])
    me = client.get("/api/me", headers={"X-User": f"s-{MY_TYPE}"}).json()
    assert me["student_type"] == MY_TYPE and me["section"] == "D4-CS-A"


def _generated(college):
    from app.solver import solve

    if not hasattr(_generated, "cache"):
        res = solve(college, optimize=False, time_limit=30)
        _generated.cache = [e for e in res.entries if not college.lesson_by_id[e.lesson].fixed]
    return _generated.cache

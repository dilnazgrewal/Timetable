"""Every department's real timetable (IT, ME, CE, ECE, EE next to CSE), imported from its published FET pages,
fits together as one college; each department's optimised version is never worse and keeps the rules."""
import json
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from app import rules
from app.importers import fet_dept
from app.models import Entry
from app.optimise import department_college, movable, out_path
from app.store import STORE
from app.validator import metrics, split_issues, validate

DEPTS = ["IT", "ME", "CE", "ECE", "EE"]
NEVER_WORSE = ["idle_total", "no_lunch_days", "teacher_no_lunch_days", "teacher_streak_days", "late_sessions",
               "long_days", "lonely_days", "lab_same_day"]


@pytest.fixture(scope="module")
def college():
    return STORE.college


def test_every_department_is_imported(college):
    counts = Counter(l.dept for l in college.lessons if l.fixed)
    assert set(DEPTS) | {"CSE"} <= set(counts) and all(counts[d] > 200 for d in DEPTS)


def test_reader_handles_every_fet_flavour():
    assert fet_dept.slot_of("08:30-09:30") == 0 and fet_dept.slot_of("8:30") == 0
    assert fet_dept.slot_of("8.30 AM (1ST)") == 0 and fet_dept.slot_of("01:30-02:30") == 5  # 12-hour afternoon
    assert fet_dept.room_key("S-213") == "S213" and fet_dept.room_key("G10 (MPE Dept.)") == "G10"
    g = fet_dept.Groups("IT", "IT")
    assert g.parse("D2IT_C1") == ("D2-IT-C", "C1") and g.parse("D2IT_C") == ("D2-IT-C", None)
    assert g.parse("D4E.1")[0].startswith("D4-IT-X")  # an elective audience, not section E
    assert fet_dept.Groups("EE", "").parse("D2A") == ("D2-EE-A", None)
    assert fet_dept.Groups("EE", "").parse("D2MC")[0] == "D2-EE-XD2MC"  # minor course
    assert fet_dept._teacher("Dr. Randeep Kaur-RDK", "IT")[:2] == ("IT-RDK", "Dr. Randeep Kaur")
    assert fet_dept._teacher("SWJ (AppSc)", "EE")[0] == "AS-SWJ"
    assert fet_dept._teacher("Dr. Narwant Singh Grewal (NSG)", "ECE")[0] == "ECE-NSG"


def test_the_whole_college_fits_together(college):
    """All six published timetables together: no student group or room is ever double-booked. The only clashes
    are teachers listed by two departments at the same time (mostly one combined class written in both
    departments' timetables, in rooms with different names) and one teacher CE's own export double-books."""
    clashes, _ = split_issues(validate(college, college.fixed_entries))
    assert clashes and all(c.startswith("CLASH Teacher") for c in clashes) and len(clashes) <= 32


def test_shared_rooms_are_one_room_labs_are_not(college):
    rooms = college.room_by_id
    assert "S213" in rooms and "S-213" not in rooms  # IT's and CE's "S-213" is CSE's S213
    assert "DBMS LAB" in rooms and "DBMSLAB" in rooms  # CSE's DBMS lab and IT's are different labs
    assert rooms["OTHER DEPARTMENT"].kind == "Other department" and not rooms["OTHER DEPARTMENT"].bookable


def test_a_class_taught_across_departments_is_not_counted_twice(college):
    # CSE's ERP is taught by an ME teacher and appears in both exports; it is kept once, in CSE
    seen = Counter((e.room, e.day, e.start) for e in college.fixed_entries
                   if college.room_by_id[e.room].kind != "Other department")
    assert max(seen.values()) == 1


def test_what_may_move(college):
    for d in DEPTS + ["CSE"]:
        ls = [l for l in college.lessons if l.fixed and l.dept == d]
        mv = [l for l in ls if movable(college, l, d)]
        assert mv, d
        assert not any(rules.year_of(l.batches[0]) == "D1" for l in mv)  # first year: shared by departments
        if d != "CSE":  # no elective lists: electives and 3rd/4th-year group classes stay
            assert all(rules.audience(college, l) != "mixed" for l in mv)
            assert all(rules.audience(college, l) == "whole" for l in mv if rules.year_of(l.batches[0]) in ("D3", "D4"))


@pytest.mark.parametrize("dept", DEPTS)
def test_optimised_department_is_never_worse(college, dept):
    path = out_path(dept)
    if not path.exists():
        pytest.skip(f"no optimised {dept} timetable saved")
    saved = json.loads(path.read_text(encoding="utf-8"))
    sub = department_college(college, dept)
    before = [e for e in college.fixed_entries if college.lesson_by_id[e.lesson].dept == dept]
    after = [Entry(**e) for e in saved["entries"]]
    assert Counter((e.lesson, e.duration) for e in after) == Counter((e.lesson, e.duration) for e in before)
    cb, ca = split_issues(validate(sub, before))[0], split_issues(validate(sub, after))[0]
    assert len(ca) <= len(cb)
    mb, ma = metrics(sub, before), metrics(sub, after)
    for k in NEVER_WORSE:
        assert ma[k] <= mb[k], f"{dept} {k}: optimised {ma[k]} > college {mb[k]}"
    for r in rules.report(college, before, after):
        assert r["optimised"] <= r["college"], (dept, r["id"], r["examples"]["optimised"])
    # pinned classes are exactly where the college put them
    fixed = {(e.lesson, e.day, e.start) for e in before if not movable(college, college.lesson_by_id[e.lesson], dept)}
    assert fixed <= {(e.lesson, e.day, e.start) for e in after}


@pytest.mark.parametrize("dept", DEPTS + ["CSE"])
def test_optimised_department_adds_no_clash_anywhere_in_the_college(college, dept):
    """Teachers and rooms are shared across departments: an optimised department dropped into the whole college
    may not create a clash that the published timetables don't already have."""
    path = out_path(dept)
    if not path.exists():
        pytest.skip(f"no optimised {dept} timetable saved")
    new = [Entry(**e) for e in json.loads(path.read_text(encoding="utf-8"))["entries"]]
    whole = [e for e in college.fixed_entries if college.lesson_by_id[e.lesson].dept != dept] + new

    def found(entries):  # "CLASH Teacher X at Mon P3: a, b" -> (who and when, the classes), order-free
        out = set()
        for c in split_issues(validate(college, entries))[0]:
            head, ids = c.split(": ", 1)
            out.add((head, frozenset(ids.split(", "))))
        return out
    assert found(whole) <= found(college.fixed_entries)


def test_each_hod_compares_their_own_department():
    client = lambda uid: TestClient(__import__("app.main", fromlist=["app"]).app, headers={"X-User": uid})
    assert [x["code"] for x in client("hod-IT").get("/api/compare").json()["departments"]] == ["IT"]
    assert set(x["code"] for x in client("dean").get("/api/compare").json()["departments"]) >= set(DEPTS) | {"CSE"}
    assert client("hod-IT").get("/api/compare/it").status_code == 200
    assert client("hod-IT").get("/api/compare/cse").status_code == 403
    assert client("hod-IT").get("/api/compare/xyz").status_code == 404
    assert client("hod-IT").post("/api/compare/it/publish").status_code == 403  # the timetable office publishes

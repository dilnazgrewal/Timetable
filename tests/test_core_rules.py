"""College rules (data/gndec/rules.json): the checker finds every break, the optimised timetable obeys them,
and publishing refuses a timetable that breaks them more often than the college does."""
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.store as store_mod
from app import rules
from app.models import Entry
from app.optimise import OUT, movable
from app.store import STORE


@pytest.fixture(scope="module")
def college():
    return STORE.college


@pytest.fixture(scope="module")
def before(college):
    return [e for e in college.fixed_entries if college.lesson_by_id[e.lesson].dept == "CSE"]


def rule(college, rid):
    return next(r for r in college.rules if r.id == rid)


def code(college, e):
    return college.lesson_by_id[e.lesson].code


def test_rules_load_and_match(college):
    assert {r.id for r in college.rules} >= {"labs-on-different-days", "nothing-after-jpal", "real-class-every-day",
                                             "keep-mentoring", "keep-postgraduate", "keep-other-departments"}
    assert all(r.type in rules.TYPES and r.text for r in college.rules)
    L = college.lessons
    jpal = next(l for l in L if l.code.startswith("JPAL"))
    assert rule(college, "nothing-after-jpal").applies(jpal)
    assert rule(college, "keep-other-departments").applies(jpal)  # no CSE teacher: run with another department
    mtech = next(l for l in L if l.fixed and l.batches[0].startswith("M1"))
    assert rule(college, "keep-postgraduate").applies(mtech)
    assert not rule(college, "keep-postgraduate").applies(next(l for l in L if l.code == "CV"))


def test_what_stays_where_the_college_put_it(college):
    L = college.lessons
    for l in L:
        if l.fixed and l.dept == "CSE" and (l.code.startswith("MC") or l.teacher.startswith("TBA-")
                                            or l.batches[0].startswith(("M1", "M3", "PHD"))):
            assert not movable(college, l, "CSE"), l.code
    assert movable(college, next(l for l in L if l.code == "CV"), "CSE")


def test_college_timetable_against_its_rules(college, before):
    assert rules.breaks(college, rule(college, "real-class-every-day"), before) == []  # 2nd-4th year: always
    after_jpal = rules.breaks(college, rule(college, "nothing-after-jpal"), before)
    assert len(after_jpal) == 1 and after_jpal[0].startswith("MC at Wed 15:30")  # D4 CS C mentoring
    assert len(rules.breaks(college, rule(college, "labs-on-different-days"), before)) == 12


def test_a_day_with_only_open_elective_and_project_is_caught(college, before):
    """The rule the student described: OE + major project and nothing else is not a working day."""
    skip = ("OE-", "MJP", "MC", "JPAL")
    sec = {"D4-CS-A"}
    friday_light = [e for e in before if not (e.day == 4 and not code(college, e).startswith(skip)
                                              and rules.sections(college.lesson_by_id[e.lesson]) & sec)]
    found = rules.breaks(college, rule(college, "real-class-every-day"), friday_light)
    # (electives shared with other sections went too, so their students show up as well)
    assert any(f.startswith("D4 CS A") for f in found) and all(f.endswith("no real class on Fri") for f in found)


def test_a_class_after_jpal_is_caught(college, before):
    jpal = next(e for e in before if code(college, e).startswith("JPAL") and e.day == 3)  # Thursday 13:30-15:30
    cv = next(e for e in before if code(college, e) == "CV")
    moved = [replace(e, day=3, start=jpal.start + jpal.duration) if e is cv else e for e in before]
    found = rules.breaks(college, rule(college, "nothing-after-jpal"), moved)
    assert len(found) == 2 and any(f.startswith("CV at Thu 15:30") for f in found)


def test_optimised_timetable_obeys_the_rules(college, before):
    if not OUT.exists():
        pytest.skip("no optimised timetable saved yet")
    saved = json.loads(OUT.read_text(encoding="utf-8"))
    after = [Entry(**e) for e in saved["entries"]]
    for r in rules.report(college, before, after):
        assert r["optimised"] <= r["college"], (r["id"], r["examples"]["optimised"])
        if r["strength"] == "must" and r["college"] == 0:
            assert r["optimised"] == 0
        assert saved["rules"][r["id"]] == {"college": r["college"], "optimised": r["optimised"]}  # honest numbers


def test_publish_refuses_a_timetable_that_breaks_the_rules(college, before, tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "STATE", tmp_path / "state.json")
    from app.api import core

    jpal = next(e for e in before if code(college, e).startswith("JPAL") and e.day == 3)
    cv = next(e for e in before if code(college, e) == "CV")
    bad = [replace(e, day=3, start=jpal.start + jpal.duration) if e is cv else e for e in before]
    monkeypatch.setattr(core, "_optimised", lambda: {"clashes": {"optimised": 0}, "entries": [e.__dict__ for e in bad]})
    r = TestClient(core_app(), headers={"X-User": "admin"}).post("/api/compare/cse/publish")
    assert r.status_code == 409 and "JPAL" in r.json()["detail"]
    assert STORE.published.get("CSE", {}).get("status") != "published"


def core_app():
    from app.main import app

    return app

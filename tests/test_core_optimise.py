"""The optimised CSE timetable the app shows: same lessons, 0 clashes, never worse than the college."""
import json
from collections import Counter

import pytest

from app.models import Entry
from app.optimise import OUT, department_college, movable
from app.seed import build_college
from app.validator import metrics, split_issues, validate

NEVER_WORSE = ["idle_total", "no_lunch_days", "teacher_no_lunch_days", "teacher_streak_days", "late_sessions", "long_days",
               "lonely_days"]


@pytest.fixture(scope="module")
def college():
    return build_college()


@pytest.fixture(scope="module")
def result():
    if not OUT.exists():
        pytest.skip("no optimised timetable saved yet (python -m app.optimise)")
    return json.loads(OUT.read_text(encoding="utf-8"))


def test_same_lessons_only_times_change(college, result):
    before = [e for e in college.fixed_entries if college.lesson_by_id[e.lesson].dept == "CSE"]
    after = [Entry(**e) for e in result["entries"]]
    # every lesson keeps its number of sessions and their length; lessons themselves (teachers, groups,
    # subject) are the very same objects, looked up by id
    assert Counter((e.lesson, e.duration) for e in after) == Counter((e.lesson, e.duration) for e in before)
    # rooms stay of the kind the lesson needs
    for e in after:
        assert college.room_by_id[e.room].kind == college.lesson_by_id[e.lesson].room_kind
    # pinned sessions (M.Tech, PhD, mentoring) are exactly where the college put them
    pinned_before = {(e.lesson, e.day, e.start, e.room) for e in before
                     if not movable(college, college.lesson_by_id[e.lesson], "CSE")}
    assert pinned_before <= {(e.lesson, e.day, e.start, e.room) for e in after}


def test_no_clashes_and_never_worse(college, result):
    """Checked per real student type (department distribution lists), so no real student gets two classes."""
    sub = department_college(college, "CSE")
    after = [Entry(**e) for e in result["entries"]]
    clashes, _ = split_issues(validate(sub, after))
    assert clashes == []
    before = [e for e in college.fixed_entries if college.lesson_by_id[e.lesson].dept == "CSE"]
    mb, ma = metrics(sub, before), metrics(sub, after)
    for k in NEVER_WORSE:
        assert ma[k] <= mb[k], f"{k}: optimised {ma[k]} > college {mb[k]}"
    assert ma["idle_total"] < mb["idle_total"]  # and it really is better where it matters most
    assert ma == {**result["metrics"]["optimised"], "teacher_load": ma["teacher_load"]}  # saved numbers are honest

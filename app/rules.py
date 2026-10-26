"""College-specific timetable rules: what a college decides, written down so the optimiser obeys it and the
independent checker counts every break.

Each college has a list (data/<college>/rules.json). A rule is one of a few types, applied to the lessons its
`match` selects (by department, subject code, year or teacher):

  keep_as_published  these lessons never move (mentoring, M.Tech/PhD, classes run with other departments)
  labs_apart         a teacher's lab for two groups of one class goes on two different days
  nothing_after      no class for the whole section after this one on its day (e.g. JPAL, an optional class)
  real_class_daily   every weekday has at least `min` real classes (not counting e.g. open elective, project)
  allowed_times      these lessons only start in `periods`

strength "must": never broken wherever the college's own timetable keeps it; "prefer": avoided, and never more
often than the college does. This module only reads timetables (no solver code), so the validator and the API
can use it; app/optimise.py turns the same rules into constraints.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from app.models import DAYS, PERIODS, College, Entry, Lesson

TYPES = ("keep_as_published", "labs_apart", "nothing_after", "real_class_daily", "allowed_times")


@dataclass
class Rule:
    id: str
    type: str
    text: str  # the rule in plain words
    why: str = ""
    strength: str = "must"  # must | prefer
    match: dict = field(default_factory=dict)  # dept, code_prefix [..], years [..], teacher_prefix [..]
    params: dict = field(default_factory=dict)

    def applies(self, l: Lesson) -> bool:
        m = self.match
        if m.get("dept") and l.dept != m["dept"]:
            return False
        if m.get("code_prefix") and not l.code.startswith(tuple(m["code_prefix"])):
            return False
        if m.get("teacher_prefix") and not l.teacher.startswith(tuple(m["teacher_prefix"])):
            return False
        if m.get("years") and not any(year_of(b) in m["years"] for b in l.batches):
            return False
        return True


def load(path: Path) -> list[Rule]:
    if not path.exists():
        return []
    rules = [Rule(**r) for r in json.loads(path.read_text(encoding="utf-8"))["rules"]]
    for r in rules:
        assert r.type in TYPES, f"rule {r.id}: unknown type {r.type}"
        assert r.strength in ("must", "prefer"), f"rule {r.id}: strength must be 'must' or 'prefer'"
    return rules


def year_of(batch: str) -> str:
    return batch.split("-", 1)[0]  # "D4-CS-A-A1" -> "D4", "PHD-CS-ALL" -> "PHD"


def section_of(batch: str) -> str:
    return batch.rsplit("-", 1)[0]  # "D4-CS-A-A1" -> "D4-CS-A"


def sections(l: Lesson) -> set[str]:
    return {section_of(b) for b in l.batches}


def student_units(college: College) -> list[tuple[str, str, set[str]]]:
    """(name, section, lessons) for every student type (or group, where there are no types)."""
    if college.student_types:
        return [(t.name, t.section, set(t.lessons)) for t in college.student_types]
    return [(g, section_of(g), ls) for g, ls in college.units()]


def _where(e: Entry) -> str:
    return f"{DAYS[e.day]} {PERIODS[e.start][1]}"


def breaks(college: College, rule: Rule, entries: list[Entry]) -> list[str]:
    """Every place `entries` break `rule`, in plain words (compared with the college's published timetable
    where the rule needs it)."""
    L = college.lesson_by_id
    entries = [e for e in entries if e.lesson in L]
    out: list[str] = []
    if rule.type == "keep_as_published":
        published = {(e.lesson, e.day, e.start) for e in college.fixed_entries}
        out = [f"{L[e.lesson].code} ({L[e.lesson].section}) moved to {_where(e)}" for e in entries
               if rule.applies(L[e.lesson]) and L[e.lesson].fixed and (e.lesson, e.day, e.start) not in published]
    elif rule.type == "labs_apart":
        days: dict[str, set[int]] = defaultdict(set)
        for e in entries:
            days[e.lesson].add(e.day)
        for a, b in college.lab_pairs():
            if rule.applies(L[a]) and rule.applies(L[b]):
                for d in sorted(days[a] & days[b]):
                    out.append(f"{L[a].code} and {L[b].code} ({L[a].section}, {L[a].teacher}) both on {DAYS[d]}")
    elif rule.type == "nothing_after":
        for j in entries:
            if not rule.applies(L[j.lesson]):
                continue
            secs, end = sections(L[j.lesson]), j.start + j.duration
            for e in entries:
                if e.day == j.day and e.start >= end and e.lesson != j.lesson and sections(L[e.lesson]) & secs:
                    out.append(f"{L[e.lesson].code} at {_where(e)} after {L[j.lesson].code} ({L[e.lesson].section})")
    elif rule.type == "real_class_daily":
        skip = tuple(rule.params.get("not_counting", []))
        need = rule.params.get("min", 1)
        real: dict[tuple, int] = defaultdict(int)
        for e in entries:
            if not L[e.lesson].code.startswith(skip):
                real[e.lesson, e.day] += 1
        years = rule.match.get("years")
        for name, sec, ls in student_units(college):
            if (years and year_of(sec) not in years) or not any(x in L and rule.applies(L[x]) for x in ls):
                continue
            for d in range(len(DAYS)):
                if sum(real.get((x, d), 0) for x in ls) < need:
                    out.append(f"{name}: no real class on {DAYS[d]}")
    elif rule.type == "allowed_times":
        ok = set(rule.params.get("periods", []))
        out = [f"{L[e.lesson].code} ({L[e.lesson].section}) at {_where(e)}" for e in entries
               if rule.applies(L[e.lesson]) and e.start not in ok]
    return out


def report(college: College, before: list[Entry], after: list[Entry]) -> list[dict]:
    """Each rule with how often the college's timetable and the optimised one break it (and a few examples)."""
    out = []
    for r in college.rules:
        b, a = breaks(college, r, before), breaks(college, r, after)
        out.append({"id": r.id, "type": r.type, "strength": r.strength, "text": r.text, "why": r.why,
                    "college": len(b), "optimised": len(a), "examples": {"college": b[:5], "optimised": a[:5]}})
    return out

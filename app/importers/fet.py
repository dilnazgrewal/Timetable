"""Import a timetable published by FET (the free desktop timetabling program GNDEC uses).

FET exports one HTML table per room ("*_rooms_days_horizontal.html"): rows are time slots, columns
are days, and each cell holds three lines: groups, teacher(s), activity. Labs span two rows
(rowspan="2"). "---" is a free slot and "-x-" is a slot the room is not available.

`parse_rooms_html()` turns that page into rooms, teachers, sections (with their lab groups),
lessons and placed entries. All of them use the shared domain model, so the validator, free rooms,
dashboards and venue booking work on the real timetable unchanged. Imported lessons are marked
`fixed=True`: the generator never moves them.

Usage (writes data/gndec/cse.json, which build_college() picks up):
    python -m app.importers.fet data/gndec/raw/rooms.html
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict
from html.parser import HTMLParser
from pathlib import Path

from app.models import DAYS, PERIODS, Entry, Lesson, Room, Section, Teacher

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "data" / "gndec" / "cse.json"
DEPT = "CSE"  # the department whose timetable this is

# Lab capacities from GNDEC CSE "Laboratories 2025" (systems per lab); others default to 30.
LAB_SEATS = {"SL-I LAB": 35, "SL-II LAB": 34, "SL-III LAB": 35, "SL-IV LAB": 30, "PL LAB": 35,
             "OS LAB": 25, "R LAB": 28}
# Classrooms listed in GNDEC CSE "Class Rooms 2025" that the timetable never uses (they are free all week).
EXTRA_CLASSROOMS = ["S215", "S216", "S217", "S219"]
SUBJECTS = {
    "TOC": "Theory of Computation", "DS": "Data Structures", "OOP": "Object Oriented Programming",
    "DAA": "Design & Analysis of Algorithms", "CA": "Computer Architecture", "DE": "Digital Electronics",
    "SE": "Software Engineering", "CN": "Computer Networks", "OS": "Operating Systems",
    "DBMS": "Database Management Systems", "CS": "Cyber Security", "CNS": "Cryptography & Network Security",
    "GAI": "Generative AI", "DWBI": "Data Warehousing & Business Intelligence",
    "OOAD": "Object Oriented Analysis & Design", "SC": "Soft Computing", "CV": "Computer Vision",
    "WT": "Web Technologies", "ERP": "Entrepreneurship Practices", "APP. MATH": "Applied Mathematics",
    "Ind. Con.": "Indian Constitution", "Ind. KS": "Indian Knowledge System",
    "Dis. Mgmt.": "Disaster Management", "MC": "Mentoring", "DWDM": "Data Warehousing & Data Mining",
    "SDN": "Software Defined Networks", "Desg. Think.": "Design Thinking", "ACC": "Accounting",
}
DEPT_TAGS = {"App. Sci.": "AS", "MPE": "ME"}  # teacher tags that name a department, not a person


class _Tables(HTMLParser):
    """Collects every <table id="table_N">: its header title and rows of (rowspan, [lines]) cells."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[dict] = []
        self._t: dict | None = None
        self._row: list | None = None
        self._cell: list[str] | None = None
        self._buf = ""
        self._in_th = False
        self._rowspan = 1

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table" and (a.get("id") or "").startswith("table_"):
            self._t = {"title": "", "rows": []}
        elif self._t is None:
            return
        elif tag == "tr":
            self._row = []
        elif tag == "th":
            self._in_th, self._buf = True, ""
        elif tag == "td" and self._row is not None:
            self._cell, self._buf, self._rowspan = [], "", int(a.get("rowspan", 1))
        elif tag == "br" and self._cell is not None:
            self._cell.append(self._buf.strip())
            self._buf = ""

    def handle_endtag(self, tag):
        if self._t is None:
            return
        if tag == "th":
            text = self._buf.strip()
            if not self._t["title"] and text and "Monday" not in text:
                self._t["title"] = text
            elif self._row is not None and re.fullmatch(r"\d\d:\d\d-\d\d:\d\d", text):
                self._row.append(("slot", text))
            self._in_th = False
        elif tag == "td" and self._cell is not None:
            if self._buf.strip():
                self._cell.append(self._buf.strip())
            self._row.append((self._rowspan, [x for x in self._cell if x]))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row and self._row[0][0] == "slot":
                self._t["rows"].append(self._row)
            self._row = None
        elif tag == "table":
            self.tables.append(self._t)
            self._t = None

    def handle_data(self, data):
        if self._cell is not None or self._in_th:
            self._buf += data


def _grid(table: dict) -> list[tuple[int, int, int, list[str]]]:
    """Resolve rowspans: -> (day, start_slot, duration, lines) for every non-empty cell."""
    slot_of = {f"{s}-{e}": i for i, (_, s, e) in enumerate(PERIODS)}
    taken: set[tuple[int, int]] = set()
    out = []
    for r, row in enumerate(table["rows"]):
        slot = slot_of.get(row[0][1])
        if slot is None:
            continue
        day = 0
        for span, lines in row[1:]:
            while (r, day) in taken:
                day += 1
            for k in range(span):
                taken.add((r + k, day))
            if lines and lines[0] not in ("---", "-x-") and day < len(DAYS):
                out.append((day, slot, span, lines))
            day += 1
    return out


GROUP_RE = re.compile(r"^(D\d)\s+(\w+)\s+([A-Z])(\d*)$")


def _parse_groups(text: str) -> list[tuple[str, str, str]]:
    """'D3 CS A1, D3 CS B1' -> [(section_id, group_suffix or '', display)], e.g. ('D3-CS-A', 'A1', ...)."""
    out = []
    for tok in (t.strip() for t in text.split(",")):
        m = GROUP_RE.match(tok)
        if m:
            year, prog, letter, num = m.groups()
            out.append((f"{year}-{prog}-{letter}", f"{letter}{num}" if num else "", tok))
        elif tok:  # M.Tech / PhD groups such as "M1", "M3", "PHD"
            sid = f"{re.sub(r'[^A-Za-z0-9]', '', tok).upper()}-CS"
            out.append((sid, "", tok))
    return out


def _parse_teachers(text: str) -> list[tuple[str, str, str]]:
    """'Dr. Daljit Singh (DS), Pf. Pragya (App. Sci.)' -> [(id, name, dept)]."""
    out = []
    for part in re.split(r",\s*(?=(?:Dr|Pf|Er|Prof|Mr|Ms|TA\d*)[\.\-\s])", text):
        part = part.strip()
        m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", part)
        name, tag = (m.group(1), m.group(2)) if m else (re.sub(r"^TA\d+-", "", part), "")
        slug = re.sub(r"[^A-Za-z]", "", re.sub(r"^(Dr|Pf|Er|Prof)\.?\s*", "", name))[:16]
        if tag in DEPT_TAGS:
            out.append((f"{DEPT_TAGS[tag]}-{slug}", name, DEPT_TAGS[tag]))
        elif "-" in tag:  # "JDS-CE": a teacher from another department
            abbr, dept = tag.split("-", 1)
            out.append((abbr, name, dept))
        elif tag:
            out.append((tag, name, DEPT))
        else:
            out.append((f"X-{slug}", name, DEPT))
    return out


def _subject(activity: str) -> tuple[str, str, str]:
    """'DS Lab P' -> ('DS Lab', 'Data Structures Lab', 'lab'); 'CV E(T)' -> ('CV', 'Computer Vision (elective)', 'theory')."""
    kind = "lab" if re.search(r"\bLab\b", activity) else "theory"
    code = re.sub(r"\s*(\(L\)|E\(L\)|E\(T\)|E\(P\)|\bL|\bT|\bP|MTECH L)$", "", activity).strip()
    code = re.sub(r"\s+MC(\(FY\))?$", "", code) or activity
    base = re.sub(r"\s+(Lab\b.*|Group\s+\w+)$", "", code)
    name = SUBJECTS.get(base, base)
    if kind == "lab":
        name += " Lab"
    if "Group" in code:
        name += f" (group {code.split('Group', 1)[1].strip()})"
    if "E(" in activity:
        name += " (elective)"
    return code, name, kind


def _room(name: str) -> Room:
    up = name.upper()
    floor = {"G": "Ground", "F": "First", "S": "Second"}.get(name[:1], "First")
    if "SEMINAR" in up:
        return Room(name, "Seminar Hall", 150, None, "WS", "Ground", ["projector", "sound", "ac", "stage"],
                    sittable=False, bookable=True)
    if "LIB" in up:
        return Room(name, "Study Area", 15, DEPT, "MBA", "Second", ["projector"])
    if "(IT DEPT" in up:
        return Room(name, "Computer Lab", 30, "IT", "MBA", "First", ["projector", "computers"], sittable=False)
    if "(MPE DEPT" in up:
        return Room(name, "Classroom", 60, "ME", "MECH", "Ground", ["projector"], bookable=True)
    if "LAB" in up:
        return Room(name, "Computer Lab", LAB_SEATS.get(name, 30), DEPT, "MBA", "First",
                    ["projector", "ac", "computers"], sittable=False, bookable=True)
    return Room(name, "Classroom", 75, DEPT, "MBA", floor, ["projector"], bookable=True)


def parse_rooms_html(html: str) -> dict:
    parser = _Tables()
    parser.feed(html)
    rooms: dict[str, Room] = {}
    teachers: dict[str, Teacher] = {}
    section_groups: dict[str, set[str]] = defaultdict(set)
    cells = []  # (room, day, slot, span, group_tokens, teacher_ids, activity)
    for t in parser.tables:
        name = t["title"]
        if not name or "," in name:  # skip FET's combined-room tables, e.g. "S202, S203"
            continue
        rooms[name] = _room(name)
        for day, slot, span, lines in _grid(t):
            groups = _parse_groups(lines[0])
            if len(lines) >= 3:
                tlist, activity = _parse_teachers(lines[1]), lines[2]
            else:  # no teacher given (e.g. "JPAL")
                tlist, activity = [], lines[-1]
            for tid, tname, tdept in tlist:
                teachers.setdefault(tid, Teacher(tid, tname, tdept, max_per_day=len(PERIODS)))
            for sid, suffix, _ in groups:
                if suffix:
                    section_groups[sid].add(suffix)
                else:
                    section_groups.setdefault(sid, set())
            cells.append((name, day, slot, span, groups, [t[0] for t in tlist], activity))
    for extra in EXTRA_CLASSROOMS:
        rooms.setdefault(extra, _room(extra))

    # sections and their atomic groups (a section never split in the data gets one "ALL" group)
    sections: dict[str, Section] = {}
    for sid, suffixes in sorted(section_groups.items()):
        groups = [f"{sid}-{s}" for s in sorted(suffixes, key=lambda x: (x[0], int(x[1:] or 0)))] or [f"{sid}-ALL"]
        year = int(sid[1]) if re.match(r"D\d-", sid) else (6 if sid.startswith("PHD") else 5)
        name = sid.replace("-", " ")
        sections[sid] = Section(sid, DEPT, year, name, 75 if year <= 4 else 30, "", groups)

    def batches_of(groups: list[tuple[str, str, str]]) -> list[str]:
        out = []
        for sid, suffix, _ in groups:
            out += [f"{sid}-{suffix}"] if suffix else sections[sid].groups
        return sorted(set(out))

    # one lesson per (activity, teachers, audience, room kind, duration); every cell is one session
    lessons: dict[tuple, Lesson] = {}
    entries: list[Entry] = []
    for room, day, slot, span, groups, tids, activity in cells:
        batches = batches_of(groups)
        teacher = tids[0] if tids else f"TBA-{re.sub(r'[^A-Za-z]', '', activity)[:10]}"
        if teacher not in teachers:
            teachers[teacher] = Teacher(teacher, f"{activity} (staff)", DEPT, max_per_day=len(PERIODS))
        r = rooms[room]
        key = (activity, teacher, tuple(tids[1:]), tuple(batches), r.kind, span)
        if key not in lessons:
            code, name, kind = _subject(activity)
            label = ", ".join(g[2] for g in groups) if len(groups) <= 2 else f"{groups[0][2].split()[0]} CS · {len(groups)} groups"
            lessons[key] = Lesson(f"CSE:{len(lessons) + 1:04d}", code, name, kind, DEPT, teacher, label, batches,
                                  0, span, r.kind, [], r.capacity, co_teachers=list(tids[1:]), fixed=True)
        l = lessons[key]
        if room not in l.rooms:
            l.rooms.append(room)
        l.size = min(l.size, r.capacity)
        entries.append(Entry(l.id, l.sessions, day, slot, span, room))
        l.sessions += 1

    return {"source": "FET rooms export", "dept": DEPT,
            "rooms": [asdict(r) for r in rooms.values()], "teachers": [asdict(t) for t in teachers.values()],
            "sections": [asdict(s) for s in sections.values()], "lessons": [asdict(l) for l in lessons.values()],
            "entries": [asdict(e) for e in entries]}


def load(path: Path = OUT) -> dict | None:
    """The imported data as domain objects, or None if nothing has been imported."""
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {"rooms": [Room(**r) for r in raw["rooms"]],
            "teachers": [Teacher(**{**t, "unavailable": [tuple(u) for u in t["unavailable"]]}) for t in raw["teachers"]],
            "sections": [Section(**s) for s in raw["sections"]],
            "lessons": [Lesson(**l) for l in raw["lessons"]],
            "entries": [Entry(**e) for e in raw["entries"]]}


if __name__ == "__main__":
    src = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "data" / "gndec" / "raw" / "rooms.html")
    data = parse_rooms_html(src.read_text(encoding="utf-8-sig"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"{len(data['rooms'])} rooms, {len(data['teachers'])} teachers, {len(data['sections'])} sections, "
          f"{len(data['lessons'])} lessons, {len(data['entries'])} placed sessions -> {OUT.relative_to(ROOT)}")

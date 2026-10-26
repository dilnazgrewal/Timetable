"""Import any GNDEC department's published FET timetable (IT, ME, CE, ECE, EE), as app/importers/fet.py does for CSE.

Departments export with different FET versions and settings, so this reader is tolerant:
- room / group name in the table caption (<span class="name">) or the first header cell
- times as "08:30-09:30", "8:30", "8.30 AM (1ST)" or 12-hour "01:30-02:30"; days as "Monday" or "M/T/W/TH/F"
- cells as <br>-separated lines (older FET: groups, teacher, activity) or labelled spans/divs (newer FET:
  studentsset, teacher, subject + activity tag)
- 2-hour labs as one tall cell (rowspan) or the same lab written in two rows

The rooms page is the source of classes (one class per room cell). The groups page adds every hour a group
is busy that the rooms page doesn't show (taught in another department's rooms), as fixed placeholders,
so nothing is ever moved onto them.

Group names become sections and lab groups when they follow the department's pattern ("D2IT_C1" = 2nd year
IT, section C, lab group 1; "D2A" in EE = 2nd year, section A). Anything else (electives such as "D4E.1",
minor courses, other departments' first years) becomes its own "elective" audience.

Usage: python -m app.importers.fet_dept IT   (or ALL) -> data/gndec/<dept>.json
"""
from __future__ import annotations

import html as htmllib
import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict
from html.parser import HTMLParser
from pathlib import Path

from app.models import DAYS, PERIODS, Entry, Lesson, Room, Section, Teacher

ROOT = Path(__file__).resolve().parent.parent.parent
RAW = ROOT / "data" / "gndec" / "raw"
OUT_DIR = ROOT / "data" / "gndec"
# department -> (raw folder, code in its group names, building)
DEPARTMENTS = {"IT": ("it", "IT", "MBA"), "ME": ("me", "ME", "MECH"), "CE": ("ce", "CE", "CIVIL"),
               "ECE": ("ece", "EC", "ECE"), "EE": ("ee", "", "EE")}
APPLIED = ("APPSC", "APS", "APPLIEDSCI", "APPSCI", "AS")  # teacher tags meaning Applied Sciences
# written where a teacher's name should be: a department, or nobody in particular
NOT_A_PERSON = {"MPE", "ME", "CE", "IT", "ECE", "EC", "EE", "CSE", "CS", "AS", "APS", "APPSC", "FACULTY", "NEWFACULTY",
                "TBA", "SELFSTUDY", "GUESTFACULTY", "VISITINGFACULTY", "NA", "X"}
NOT_CLASSES = ("SELF STUDY", "SELFSTUDY", "LIBRARY")
# a department written after a teacher's initials: 'RKS (MPE)' = RKS of Mechanical & Production
DEPT_TAG = {"MPE": "ME", "ME": "ME", "CE": "CE", "ECE": "ECE", "EC": "ECE", "IT": "IT", "EE": "EE", "CSE": "CSE", "CS": "CSE"}
OTHER_TAGS = {"TA1", "TA2", "TA3", "WS", "CA", "AC", "OE"}  # duties, not departments
OTHER_ROOM = Room("OTHER DEPARTMENT", "Other department", 999, None, "", "", [], sittable=False)
DAY_NAMES = {"MONDAY": 0, "M": 0, "TUESDAY": 1, "T": 1, "TU": 1, "WEDNESDAY": 2, "W": 2, "THURSDAY": 3, "TH": 3,
             "FRIDAY": 4, "F": 4}
START_OF = {s: i for i, (_, s, _) in enumerate(PERIODS)}  # "08:30" -> 0


def norm(s: str) -> str:
    return re.sub(r"[\s_.\-]", "", s).upper()


def room_key(name: str) -> str:
    """'S-213', 'S213', 'G10 (MPE Dept.)' -> 'S213', 'G10' (the same physical room across departments)."""
    name = re.sub(r"\((?:[^)]*DEP[^)]*|other\s*Dept+)\)", "", name, flags=re.I)
    return norm(name)


def slot_of(label: str) -> int | None:
    m = re.search(r"(\d{1,2})[:.](\d{2})", label)
    if not m:
        return None
    h, mi = int(m.group(1)), m.group(2)
    if h < 8:
        h += 12  # 01:30 -> 13:30
    return START_OF.get(f"{h:02d}:{mi}")


# --- reading the tables -----------------------------------------------------------------------------
FIELD_OF = (("studentsset", "groups"), ("ss_", "groups"), ("teacher", "teachers"), ("t_", "teachers"),
            ("activitytag", "tag"), ("at_", "tag"), ("subject", "subject"), ("s_", "subject"), ("room", "rooms"),
            ("r_", "rooms"))


def _field(classes: list[str]) -> str | None:
    for cls in reversed(classes):  # innermost labelled element wins
        for c in cls.split():
            for prefix, f in FIELD_OF:
                if c == prefix or (prefix.endswith("_") and c.startswith(prefix)):
                    return f
    return None


class _Reader(HTMLParser):
    """Tables with id="table_N" -> {"title", "days": [day index per column], "rows": [(label, [(rowspan, [activity])])]}.
    An activity is {"lines": [...], "groups": [...], "teachers": [...], "subject": str, "tag": str, "rooms": [...]}."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[dict] = []
        self.t = None
        self.row = None
        self.cell = None  # list of activities in the current top-level cell
        self.rowspan = 1
        self.stack: list[str] = []  # classes of open elements inside the cell
        self.depth = 0  # nested tables inside the cell
        self.col = 0  # activity column inside a nested ("detailed") table
        self.buf = ""
        self.th = None
        self.in_name = False

    def _act(self) -> dict:
        while len(self.cell) <= self.col:
            self.cell.append({"lines": [], "groups": [], "teachers": [], "subject": "", "tag": "", "rooms": []})
        return self.cell[self.col]

    def _flush(self) -> None:
        text = " ".join(self.buf.split())
        self.buf = ""
        if not text or self.cell is None:
            return
        a = self._act()
        f = _field(self.stack)
        if f in ("groups", "teachers", "rooms"):
            a[f].append(text)
        elif f in ("subject", "tag"):
            a[f] = (a[f] + " " + text).strip()
        a["lines"].append(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.cell is not None:
            if tag == "table":
                self.depth += 1
            elif tag == "tr" and self.depth:
                self._flush()
                self.col = 0
            elif tag == "td" and self.depth:
                self._flush()
            elif tag in ("br", "div"):
                self._flush()
            if tag in ("span", "div", "td", "tr"):
                self.stack.append(a.get("class") or "")
            return
        if tag == "table" and (a.get("id") or "").startswith("table_"):
            self.t = {"title": "", "days": [], "rows": []}
        elif self.t is None:
            return
        elif tag == "span" and a.get("class") == "name":
            self.in_name, self.buf = True, ""
        elif tag == "tr":
            self.row = []
        elif tag == "th":
            self.th, self.buf = (a.get("class") or ""), ""
        elif tag == "td" and self.row is not None:
            self.cell, self.rowspan, self.buf, self.stack, self.col, self.depth = [], int(a.get("rowspan", 1)), "", [], 0, 0

    def handle_endtag(self, tag):
        if self.cell is not None:
            if tag == "td" and self.depth:
                self._flush()
                self.col += 1
                if self.stack:
                    self.stack.pop()
                return
            if tag == "table" and self.depth:
                self.depth -= 1
                return
            if tag == "td":  # end of the top-level cell
                self._flush()
                acts = [x for x in self.cell if x["lines"]]
                self.row.append((self.rowspan, acts))
                self.cell = None
                return
            if tag in ("span", "div", "tr"):
                if tag in ("div", "tr"):
                    self._flush()
                if self.stack:
                    self.stack.pop()
            return
        if self.t is None:
            return
        if tag == "span" and self.in_name:
            self.t["title"], self.in_name = " ".join(self.buf.split()), False
        elif tag == "th" and self.th is not None:
            text = " ".join(self.buf.split())
            if "xAxis" in self.th and text.upper() in DAY_NAMES:
                self.t["days"].append(DAY_NAMES[text.upper()])
            elif self.row is not None and slot_of(text) is not None and "yAxis" in self.th:
                self.row.append(("slot", text))
            elif not self.t["title"] and text and text.upper() not in DAY_NAMES:
                self.t["title"] = text
            self.th = None
        elif tag == "tr" and self.row is not None:
            if self.row and self.row[0][0] == "slot":
                self.t["rows"].append(self.row)
            self.row = None
        elif tag == "table":
            self.tables.append(self.t)
            self.t = None

    def handle_data(self, data):
        if self.cell is not None or self.th is not None or self.in_name:
            self.buf += data


def read(html: str) -> list[dict]:
    r = _Reader()
    r.feed(html)
    return r.tables


def grid(table: dict) -> list[tuple[int, int, int, list[dict]]]:
    """(day, slot, periods, activities) for every busy cell, rowspans resolved."""
    days = table["days"] or list(range(len(DAYS)))
    taken: set[tuple[int, int]] = set()
    out = []
    for r, row in enumerate(table["rows"]):
        slot = slot_of(row[0][1])
        col = 0
        for span, acts in row[1:]:
            while (r, col) in taken:
                col += 1
            for k in range(span):
                taken.add((r + k, col))
            day = days[col] if col < len(days) else None
            acts = [a for a in acts if a["lines"] and a["lines"][0] not in ("---", "-x-")]
            if slot is not None and day is not None and day < len(DAYS) and acts:
                out.append((day, slot, span, acts))
            col += 1
    return out


# --- what a cell says -----------------------------------------------------------------------------------
def _split_old(lines: list[str]) -> dict:
    """Older FET rooms page: groups, teacher(s), activity (like CSE's)."""
    if len(lines) >= 3:
        return {"groups": [g.strip() for g in lines[0].split(",")], "teachers": [lines[1]], "activity": lines[2]}
    if len(lines) == 2:
        return {"groups": [g.strip() for g in lines[0].split(",")], "teachers": [], "activity": lines[1]}
    return {"groups": [], "teachers": [], "activity": lines[0]}


def _class_of(a: dict) -> dict:
    if a["groups"] or a["subject"]:  # newer FET: labelled parts
        groups = [g.strip() for x in a["groups"] for g in x.split(",") if g.strip()]
        teachers = [t.strip() for x in a["teachers"] for t in re.split(r",\s*(?![^()]*\))", x) if t.strip()]
        return {"groups": groups, "teachers": teachers, "activity": f"{a['subject']} {a['tag']}".strip() or a["lines"][-1]}
    out = _split_old(a["lines"])
    out["teachers"] = [t.strip() for x in out["teachers"] for t in re.split(r",\s*(?![^()]*\))", x) if t.strip()]
    return out


def _teacher(text: str, dept: str) -> tuple[str, str, str]:
    """-> (id, name, home dept). 'Dr. Randeep Kaur-RDK', 'KSK', 'SWJ (AppSc)', 'NK(APS)', 'MK_APS',
    'Dr. Narwant Singh Grewal (NSG)', 'HPS (Dr. Harpuneet Singh)'."""
    t = " ".join(text.split())
    home = dept
    m = re.search(r"\(([^)]*)\)\s*$", t)
    tag = norm(m.group(1)) if m else ""
    if tag.startswith(APPLIED) or re.search(r"_APS?$", t) or "APPLIED" in t.upper():
        home = "AS"
        t = re.sub(r"_APS?$", "", t)
    elif tag in DEPT_TAG or tag in OTHER_TAGS:  # 'RKS (MPE)': RKS of Mechanical; 'SB (TA1)': a teaching assistant
        home = DEPT_TAG.get(tag, dept)
        t = t[:m.start()].strip()
    elif re.search(r"_[A-Z]{2,3}$", t):  # 'RKS_AC', 'HPS_OE': initials with a duty suffix
        t = t.rsplit("_", 1)[0]
    m1 = re.match(r"^(.*?)-([A-Za-z]{2,6})$", t)  # 'Dr. Randeep Kaur-RDK'
    m2 = re.match(r"^([A-Z][A-Za-z]{1,5})\s*\((.+)\)$", t)  # 'HPS (Dr. Harpuneet Singh)' / 'SWJ (AppSc)'
    m3 = re.match(r"^(.+?)\s*\(([A-Za-z]{2,6})\)$", t)  # 'Dr. Narwant Singh Grewal (NSG)'
    if m1:
        name, abbr = m1.group(1), m1.group(2)
    elif m2 and home == dept and not re.search(r"[a-z]", m2.group(1)[1:] if len(m2.group(1)) > 1 else ""):
        abbr, name = m2.group(1), m2.group(2)
    elif m3 and home == dept:
        name, abbr = m3.group(1), m3.group(2)
    else:
        abbr = re.sub(r"\s*\(.*\)|_APS$", "", t).strip()
        name = abbr
    abbr = norm(abbr)[:8] or "X"
    return f"{home}-{abbr}", name.strip(), home


def _subject(activity: str) -> tuple[str, str, str]:
    """'DCCN_LAB P' -> ('DCCN LAB', 'DCCN LAB', 'lab'); 'PEI.4(ACN) E(L)' -> ('PEI.4(ACN)', ..., 'theory')."""
    a = activity.replace("_", " ").strip()
    kind = "lab" if re.search(r"\bLAB\b|\bP$|\(P\)$|\bPR\b", a, re.I) else "theory"
    code = re.sub(r"\s+(E\([LTP]\)|[LTP]|MC|MC\(FY\))$", "", a).strip() or a
    return code, code, kind


class Groups:
    """The department's group names -> sections and lab groups ("D2IT_C1" -> section D2-IT-C, group D2-IT-C-C1)."""

    def __init__(self, dept: str, code: str) -> None:
        self.dept = dept
        self.pat = re.compile(rf"^D(\d){code}([A-H])?(\d?)$" if code else r"^D(\d)([A-H])(\d?)$")
        self.sections: dict[str, dict] = {}  # id -> {"year", "name", "subs": set, "kind"}

    def parse(self, token: str) -> tuple[str, str | None]:
        """token -> (section id, sub-group suffix or None for the whole section)."""
        n = norm(token)
        m = self.pat.match(n)
        if m:
            year, letter, sub = f"D{m.group(1)}", m.group(2) or "", m.group(3)
            sid = f"{year}-{self.dept}-{letter or 'ALL'}"
            s = self.sections.setdefault(sid, {"year": year, "name": token if not sub else token[:-len(sub)].strip(" _.-"),
                                               "subs": set(), "kind": "section"})
            if sub:
                s["subs"].add(f"{letter}{sub}")
                return sid, f"{letter}{sub}"
            return sid, None
        y = re.match(r"^D(\d)", n)
        year = f"D{y.group(1)}" if y else ("PHD" if n.startswith("PHD") else "M" if n.startswith(("M", "MTECH")) else "X")
        sid = f"{year}-{self.dept}-X{re.sub(r'[^A-Z0-9]', '', n)[:16]}"
        self.sections.setdefault(sid, {"year": year, "name": token, "subs": set(), "kind": "elective"})
        return sid, None

    def batches(self, tokens: list[str]) -> list[str]:
        out = set()
        for t in tokens:
            sid, sub = self.parse(t)
            out |= {f"{sid}-{sub}"} if sub else set(self.groups(sid))
        return sorted(out)

    def groups(self, sid: str) -> list[str]:
        subs = self.sections[sid]["subs"]
        return [f"{sid}-{s}" for s in sorted(subs)] or [f"{sid}-ALL"]


def import_department(dept: str) -> dict:
    folder, code, building = DEPARTMENTS[dept]
    rooms_tables = read((RAW / folder / "rooms.html").read_text(encoding="utf-8-sig", errors="replace"))
    groups_tables = read((RAW / folder / "groups.html").read_text(encoding="utf-8-sig", errors="replace"))
    G = Groups(dept, code)
    for t in groups_tables:  # learn every group name (and lab groups) first
        G.parse(t["title"])
        for _, _, _, acts in grid(t):
            for a in acts:
                for g in _class_of(a)["groups"]:
                    G.parse(g)
    rooms: dict[str, Room] = {}
    teachers: dict[str, Teacher] = {}
    cells = []  # (room, day, slot, span, class)
    for t in rooms_tables:
        name = t["title"]
        if not name or "," in name:
            continue
        key = room_key(name)
        rooms.setdefault(key, _room(key, name, dept, building))
        for day, slot, span, acts in grid(t):
            for a in acts:
                c = _class_of(a)
                for tok in c["groups"]:
                    G.parse(tok)
                cells.append((key, day, slot, span, c))
    # the same lab written in two rows -> one 2-hour lab
    cells.sort(key=lambda x: (x[0], x[1], x[2]))
    merged = []
    for cell in cells:
        room, day, slot, span, c = cell
        prev = merged[-1] if merged else None
        if (prev and prev[0] == room and prev[1] == day and prev[2] + prev[3] == slot and prev[4] == c
                and _subject(c["activity"])[2] == "lab" and prev[3] + span <= 3):
            merged[-1] = (room, day, prev[2], prev[3] + span, c)
        else:
            merged.append(cell)

    lessons: dict[tuple, Lesson] = {}
    entries: list[Entry] = []
    for room, day, slot, span, c in merged:
        batches = G.batches(c["groups"])
        if not batches:
            continue
        if c["activity"].upper().startswith(NOT_CLASSES):
            continue
        tids = []
        for t in c["teachers"]:
            if norm(re.sub(r"\(.*\)", "", t)) in NOT_A_PERSON:
                continue
            tid, tname, home = _teacher(t, dept)
            teachers.setdefault(tid, Teacher(tid, tname, home, max_per_day=len(PERIODS)))
            tids.append(tid)
        code_, name, kind = _subject(c["activity"])
        teacher = tids[0] if tids else f"TBA-{dept}-{norm(code_)[:10]}-{len(lessons) + 1}"  # nobody named
        if teacher not in teachers:
            teachers[teacher] = Teacher(teacher, f"{code_} (staff)", dept, max_per_day=len(PERIODS))
        key = (code_, teacher, tuple(tids[1:]), tuple(batches), rooms[room].kind, span)
        if key not in lessons:
            label = ", ".join(c["groups"][:2]) + (f" +{len(c['groups']) - 2}" if len(c["groups"]) > 2 else "")
            lessons[key] = Lesson(f"{dept}:{len(lessons) + 1:04d}", code_, name, kind, dept, teacher, label, batches,
                                  0, span, rooms[room].kind, [], rooms[room].capacity, co_teachers=tids[1:], fixed=True)
        l = lessons[key]
        if room not in l.rooms:
            l.rooms.append(room)
        entries.append(Entry(l.id, l.sessions, day, slot, span, room))
        l.sessions += 1

    # hours the groups page shows a group busy but no room of this department does: fixed placeholders
    busy = defaultdict(set)
    for e in entries:
        lesson = next(x for x in lessons.values() if x.id == e.lesson)
        for b in lesson.batches:
            for q in range(e.start, e.start + e.duration):
                busy[b, e.day].add(q)
    outside = 0
    seen = set()
    parallel: dict[tuple, int] = {}
    for t in groups_tables:
        own = G.batches([t["title"]])
        for day, slot, span, acts in grid(t):
            for q in range(slot, slot + span):
                free = [b for b in own if q not in busy[b, day]]
                if not free or (t["title"], day, q) in seen:
                    continue
                seen.add((t["title"], day, q))
                what = _class_of(acts[0])["activity"] if acts else "Class"
                code_ = f"Outside: {_subject(what)[0]}"[:40]
                k = parallel[day, q] = parallel.get((day, q), 0) + 1  # placeholder "teachers" never overlap
                teacher = f"TBA-{dept}-OUT{k}"
                teachers.setdefault(teacher, Teacher(teacher, "Taught in another department", "AS", max_per_day=len(PERIODS)))
                l = Lesson(f"{dept}:O{outside + 1:04d}", code_, f"{_subject(what)[0]} (in another department's room)",
                           "theory", dept, teacher, t["title"], free, 1, 1, OTHER_ROOM.kind,
                           [OTHER_ROOM.id], OTHER_ROOM.capacity, fixed=True)
                lessons[("outside", outside)] = l
                entries.append(Entry(l.id, 0, day, q, 1, OTHER_ROOM.id))
                for b in free:
                    busy[b, day].add(q)
                outside += 1
    if outside:
        rooms[OTHER_ROOM.id] = OTHER_ROOM

    sections = []
    for sid, s in sorted(G.sections.items()):
        groups = G.groups(sid)
        year = s["year"]
        yr = int(year[1]) if re.match(r"D\d$", year) else 5
        sections.append(Section(sid, dept, yr, s["name"], 60 if s["kind"] == "section" else 30, "", groups, kind=s["kind"]))
    used = {b for l in lessons.values() for b in l.batches}
    sections = [s for s in sections if set(s.groups) & used]
    return {"source": f"FET export of the {dept} department (rooms + groups pages)", "dept": dept,
            "rooms": [asdict(r) for r in rooms.values()], "teachers": [asdict(t) for t in teachers.values()],
            "sections": [asdict(s) for s in sections], "lessons": [asdict(l) for l in lessons.values()],
            "entries": [asdict(e) for e in entries], "outside_placeholders": outside}


def _room(key: str, name: str, dept: str, building: str) -> Room:
    up = name.upper()
    floor = {"G": "Ground", "F": "First", "S": "Second"}.get(key[:1], "First")
    if "SEMINAR" in up:
        return Room(key, "Seminar Hall", 120, dept, building, floor, ["projector", "sound"], sittable=False, bookable=True)
    if "LIB" in up:
        return Room(key, "Study Area", 20, dept, building, floor, [])
    if re.search(r"LAB|/L\b|/L\(|W/S|WORKSHOP", up):
        return Room(key, "Lab", 30, dept, building, floor, ["projector"], sittable=False)
    return Room(key, "Classroom", 60, dept, building, floor, ["projector"], bookable=True)


def teacher_names() -> dict[str, str]:
    """Full names from each department's teachers page (class cells often show only initials):
    'Dr. Randeep Kaur-RDK' (IT), 'HPS (Dr. Harpuneet Singh)' (ME), 'Dr. Narwant Singh Grewal (NSG)' (ECE, EE),
    'Dr. Raman Kumar Sehgal (RKS MPE)' (a Mechanical teacher on EE's page). CE lists initials only."""
    out: dict[str, str] = {}
    for dept, (folder, _, _) in DEPARTMENTS.items():
        path = RAW / folder / "teachers.html"
        if not path.exists():
            continue
        page = path.read_text(encoding="utf-8-sig", errors="replace")
        for item in (htmllib.unescape(x) for x in re.findall(r'<li><a href="#table_\d+">(.*?)</a></li>', page)):
            item = " ".join(item.split())
            home = dept
            m1 = re.match(r"^(.*[a-z].*?)-([A-Za-z]{2,6})$", item)  # 'Dr. Randeep Kaur-RDK'
            m2 = re.match(r"^([A-Z]{2,6})\s*\((.*[a-z].*)\)$", item)  # 'HPS (Dr. Harpuneet Singh)'
            m3 = re.match(r"^(.*[a-z].*?)\s*\(([A-Za-z_]{2,8})(?:\s+(MPE|APS|AS|ME|CE|IT|ECE|EE|CSE))?\)$", item)
            if m1:
                name, abbr = m1.group(1), m1.group(2)
            elif m2:
                abbr, name = m2.group(1), m2.group(2)
            elif m3:
                name, abbr = m3.group(1), m3.group(2)
                tag = m3.group(3) or ""
                home = {"MPE": "ME", "APS": "AS"}.get(tag, tag or dept)
            else:
                continue
            out.setdefault(f"{home}-{norm(abbr)[:8]}", name.strip())
    return out


def load(dept: str) -> dict | None:
    path = OUT_DIR / f"{dept.lower()}.json"
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {"rooms": [Room(**r) for r in raw["rooms"]],
            "teachers": [Teacher(**{**t, "unavailable": [tuple(u) for u in t["unavailable"]]}) for t in raw["teachers"]],
            "sections": [Section(**s) for s in raw["sections"]], "lessons": [Lesson(**l) for l in raw["lessons"]],
            "entries": [Entry(**e) for e in raw["entries"]]}


if __name__ == "__main__":
    which = list(DEPARTMENTS) if (sys.argv[1:] or ["ALL"])[0].upper() == "ALL" else [a.upper() for a in sys.argv[1:]]
    for d in which:
        data = import_department(d)
        (OUT_DIR / f"{d.lower()}.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        print(f"{d}: {len(data['rooms'])} rooms, {len(data['teachers'])} teachers, {len(data['sections'])} sections, "
              f"{len(data['lessons'])} lessons, {len(data['entries'])} sessions, {data['outside_placeholders']} hours elsewhere")

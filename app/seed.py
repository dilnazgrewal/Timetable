"""Synthetic GNDEC-like college: 5 departments x 4 sections (2nd & 3rd year, A/B), shared labs,
an Applied Sciences department teaching Maths to every 2nd-year section, teachers shared across
departments, and a visiting teacher available only Tue/Thu."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import replace

from app import rules
from app.importers import fet, fet_dept, gndec_students
from app.importers.fet import ROOT
from app.models import PERIODS, Building, College, Department, Lesson, Room, Section, Teacher

DEPTS = [
    Department("CSE", "Computer Science & Engineering"),
    Department("IT", "Information Technology"),
    Department("ECE", "Electronics & Communication"),
    Department("ME", "Mechanical Engineering"),
    Department("CE", "Civil Engineering"),
    Department("EE", "Electrical Engineering"),
    Department("AS", "Applied Sciences"),
]

LAB_KIND = {"CSE": "Computer Lab", "IT": "Computer Lab", "ECE": "Electronics Lab",
            "ME": "Mechanical Lab", "CE": "Civil Lab"}

# dept -> year -> (theory subjects [(name, code, hours)], labs [(name, code)])
CURRICULUM = {
    "CSE": {
        2: ([("Data Structures", "DS", 4), ("Digital Electronics", "DE", 3),
             ("Discrete Mathematics", "DM", 3), ("Object Oriented Programming", "OOP", 4)],
            [("Data Structures Lab", "DSL"), ("Java Lab", "JL")]),
        3: ([("Operating Systems", "OS", 4), ("Database Systems", "DBMS", 4),
             ("Computer Networks", "CN", 3), ("Design & Analysis of Algorithms", "DAA", 3)],
            [("DBMS Lab", "DBL"), ("OS Lab", "OSL")]),
    },
    "IT": {
        2: ([("Data Structures", "DS", 4), ("Computer Architecture", "CA", 3),
             ("Web Technologies", "WT", 3), ("Python Programming", "PY", 4)],
            [("Web Lab", "WL"), ("Python Lab", "PYL")]),
        3: ([("Computer Networks", "CN", 4), ("Cloud Computing", "CC", 3),
             ("Machine Learning", "ML", 4), ("Information Security", "IS", 3)],
            [("ML Lab", "MLL"), ("Networks Lab", "NWL")]),
    },
    "ECE": {
        2: ([("Signals & Systems", "SS", 4), ("Network Analysis", "NA", 3),
             ("Analog Electronics", "AE", 4), ("Electromagnetic Theory", "EMT", 3)],
            [("Analog Lab", "AL"), ("Circuits Lab", "CRL")]),
        3: ([("Digital Signal Processing", "DSP", 4), ("Microprocessors", "MP", 4),
             ("Communication Systems", "COM", 3), ("VLSI Design", "VLSI", 3)],
            [("DSP Lab", "DSPL"), ("Microprocessor Lab", "MPL")]),
    },
    "ME": {
        2: ([("Thermodynamics", "TD", 4), ("Strength of Materials", "SOM", 4),
             ("Manufacturing Processes", "MFG", 3), ("Engineering Mechanics", "EM", 3)],
            [("SOM Lab", "SOML"), ("Workshop Practice", "WS")]),
        3: ([("Heat Transfer", "HT", 4), ("Machine Design", "MD", 4),
             ("Fluid Mechanics", "FM", 3), ("Dynamics of Machines", "DOM", 3)],
            [("Fluid Lab", "FML"), ("Heat Transfer Lab", "HTL")]),
    },
    "CE": {
        2: ([("Surveying", "SUR", 4), ("Building Materials", "BM", 3),
             ("Fluid Mechanics", "FM", 3), ("Structural Analysis I", "SA1", 4)],
            [("Surveying Lab", "SURL"), ("Materials Lab", "BML")]),
        3: ([("Structural Analysis II", "SA2", 4), ("Geotechnical Engg", "GT", 4),
             ("Transportation Engg", "TE", 3), ("Environmental Engg", "ENV", 3)],
            [("Geotech Lab", "GTL"), ("Concrete Lab", "CTL")]),
    },
}

FIRST = ["Harpreet", "Gurpreet", "Amandeep", "Manpreet", "Jaspreet", "Navneet", "Simran", "Rajveer",
         "Kiranjit", "Parminder", "Sukhwinder", "Ramandeep", "Arvinder", "Baljit", "Inderjit",
         "Kuldeep", "Lovepreet", "Mandeep", "Neha", "Priya", "Rohit", "Sandeep", "Tanvir", "Vikram",
         "Anjali", "Deepak", "Gagan", "Hardeep", "Ishaan", "Jasleen", "Kamal", "Meenakshi", "Nitin",
         "Pooja", "Rupinder", "Sahil", "Taranjit", "Upinder", "Varun", "Yashpal", "Akashdeep", "Bhavna"]
LAST = ["Kaur", "Singh", "Sharma", "Gill", "Sidhu", "Grewal", "Sandhu", "Dhillon", "Arora", "Bedi",
        "Brar", "Chahal", "Malhotra", "Bansal", "Kapoor", "Verma", "Bhatia", "Saini", "Mann", "Walia"]
TITLES = ["Dr.", "Prof.", "Er."]

TEACHERS_PER_DEPT = 7
SEED_DEPTS = ["CSE", "IT", "ECE", "ME", "CE"]

FLOORS = ["Ground", "First", "Second"]
BUILDINGS = [
    Building("MBA", "MBA Block (CSE & IT)", FLOORS),
    Building("ECE", "ECE Block", FLOORS),
    Building("MECH", "Mechanical Block", FLOORS),
    Building("CIVIL", "Civil Block", FLOORS),
    Building("MAIN", "Main Block", FLOORS),
    Building("WS", "Workshop Block", ["Ground"]),
]
DEPT_BUILDING = {"CSE": "MBA", "IT": "MBA", "ECE": "ECE", "ME": "MECH", "CE": "CIVIL", "EE": "EE"}


def _place_rooms(rooms: list[Room]) -> None:
    """Give seed rooms a building, floor, features and sitting/booking flags (GNDEC-like layout)."""
    for r in rooms:
        if r.building:
            continue
        if r.kind == "Classroom":
            dept, num = r.id.split("-")
            r.building = DEPT_BUILDING[dept]
            # CSE: 201-202 on the ground floor, 203-204 upstairs; IT on the first floor
            r.floor = "First" if dept == "IT" else ("Ground" if num in ("201", "202") else "Second")
            r.features, r.bookable = ["projector"], True
        elif r.kind.endswith("Lab"):
            r.building = "MBA" if r.kind == "Computer Lab" else DEPT_BUILDING[r.dept]
            r.floor = "Second" if r.kind == "Computer Lab" else "First"
            r.features = ["projector", "ac", "computers"] if r.kind == "Computer Lab" else ["projector"]
            r.sittable, r.bookable = False, r.kind == "Computer Lab"
        elif r.kind == "Lecture Theatre":
            r.building, r.floor, r.features, r.bookable = "MAIN", "First", ["projector", "sound"], True
        else:  # library reading room
            r.building, r.floor = "MAIN", "Ground"


def build_college() -> College:
    """GNDEC: the real timetables of every department that publishes one (imported from FET: CSE, IT, ME, CE,
    ECE, EE) + a GNDEC-shaped seed for any department without an import. Central halls come from the seed."""
    imported = fet.load()
    if not imported:
        return _build_seed(SEED_DEPTS)
    others = {d: x for d in fet_dept.DEPARTMENTS if (x := fet_dept.load(d))}
    seeded = [d for d in SEED_DEPTS if d != "CSE" and d not in others]
    seed = _build_seed(seeded) if seeded else _central()
    rooms = {r.id: r for r in seed.rooms}
    rooms.update({r.id: r for r in imported["rooms"]})  # real rooms win (e.g. "WS SEMINAR HALL")
    teachers = {t.id: t for t in seed.teachers}
    teachers.update({t.id: t for t in imported["teachers"]})
    sections, lessons, entries = imported["sections"] + seed.sections, imported["lessons"] + seed.lessons, list(imported["entries"])
    # a numbered classroom ("S-213" in IT's export is CSE's S213) is the same room in every department's
    # export; labs and halls with the same name ("DBMS LAB") are each department's own
    numbered = re.compile(r"^[GFS]\d{1,3}[A-Z]?$")
    same_room = {fet_dept.room_key(r): r for r in rooms if numbered.match(fet_dept.room_key(r))}
    for d, x in others.items():
        rename = {}
        for r in x["rooms"]:
            if numbered.match(r.id) and r.id in same_room:
                rename[r.id] = same_room[r.id]
            elif r.id in rooms and r.kind != "Other department":
                rename[r.id] = f"{r.id} ({d})"
                rooms[rename[r.id]] = replace(r, id=rename[r.id])
            else:
                rename[r.id] = r.id
                rooms.setdefault(r.id, r)
                if numbered.match(r.id):
                    same_room[r.id] = r.id
        for t in x["teachers"]:
            if t.id not in teachers or teachers[t.id].name == teachers[t.id].id:  # keep the fullest name
                teachers[t.id] = t
        for l in x["lessons"]:
            l.rooms = [rename.get(r, r) for r in l.rooms]
            l.room_kind = rooms[l.rooms[0]].kind if l.rooms else l.room_kind
        # a class taught by one department to another's students is in both exports (same room, same time):
        # keep the copy already imported (the students' own department; CSE first)
        taken = {(e.room, e.day, q) for e in entries if rooms[e.room].kind != "Other department" for q in e.slots}
        mine = [replace(e, room=rename.get(e.room, e.room)) for e in x["entries"]]
        mine = [e for e in mine if rooms[e.room].kind == "Other department"
                or not any((e.room, e.day, q) in taken for q in e.slots)]
        count: dict[str, int] = {}
        for i, e in enumerate(mine):
            mine[i] = replace(e, session=count.get(e.lesson, 0))
            count[e.lesson] = count.get(e.lesson, 0) + 1
        kept = [l for l in x["lessons"] if count.get(l.id)]
        for l in kept:
            l.sessions = count[l.id]
        sections += x["sections"]
        lessons += kept
        entries += mine
    sections, lessons, entries = _link_first_year(sections, lessons, entries, rooms)
    # full names: cells often show only initials; each department's teachers page has the names
    names = fet_dept.teacher_names()
    for t in teachers.values():
        if not re.search(r"[a-z]{2}", t.name) and not t.id.startswith("TBA-"):
            t.name = names.get(t.id) or f"{t.dept} teacher ({t.name})"
    # one person, two records (CSE's page names an ME teacher in full, ME's own page by initials): merge
    same: dict[str, str] = {}
    first: dict[tuple[str, str], str] = {}
    own_list = lambda tid: tid in names or "-" not in tid  # on a department's own teacher list (CSE: initials)
    for t in sorted(teachers.values(), key=lambda t: (len(t.id), t.id)):  # keep the department's own short id
        key = (t.dept, re.sub(r"^(Dr|Pf|Er|Prof|Mr|Ms)\.?\s+", "", t.name).lower())
        if " teacher (" in t.name or t.id.startswith("TBA-"):
            continue
        if key in first and not (own_list(t.id) and own_list(first[key])):  # two on one list: two people
            same[t.id] = first[key]
        elif key not in first:
            first[key] = t.id
    for l in lessons:
        l.teacher = same.get(l.teacher, l.teacher)
        l.co_teachers = list(dict.fromkeys(same.get(t, t) for t in l.co_teachers if same.get(t, t) != l.teacher))
    for tid in same:
        teachers.pop(tid)
    college = College(DEPTS, list(rooms.values()), list(teachers.values()), sections, lessons, BUILDINGS,
                      fixed_entries=entries)
    gndec_students.split_lab_groups(college)
    types, _ = gndec_students.student_types(college, gndec_students.load())
    college.set_student_types(types)
    college.rules = rules.load(ROOT / "data" / "gndec" / "rules.json")
    return college


# "D1 CS A" (CSE), "D1IT_A" (IT), "D1 CE A1" (in ME's timetable), "D1CSA1" / "D1ITA" (EE, ECE); ME's "CSE A" names no year
FIRST_YEAR = re.compile(r"^D1(CSE|CS|IT|ME|CE|ECE|EC|EE)([A-H])(\d?)$")  # only names that say D1
PROGRAMME = {"CSE": "CSE", "CS": "CSE", "IT": "IT", "ME": "ME", "CE": "CE", "ECE": "ECE", "EC": "ECE", "EE": "EE"}


def _link_first_year(sections: list[Section], lessons: list[Lesson], entries: list, rooms: dict) -> tuple:
    """First year is taught by several departments (workshop and drawing by ME, BEE by EE / ECE, the student's own
    department), and each timetable names the groups its own way. Link every name to the owning department's
    section and lab group, so a first-year student sees the whole week. Then drop the "taught elsewhere"
    placeholders that a linked class now covers."""
    owner_of = lambda prog, letter: f"D1-CS-{letter}" if prog == "CSE" else f"D1-{prog}-{letter}"
    by_id = {s.id: s for s in sections}
    target: dict[str, tuple[str, str]] = {}  # section id -> (owning section, lab group suffix or "")
    for s in sections:
        if s.year not in (1, 5) or not (m := FIRST_YEAR.match(fet_dept.norm(s.name))):
            continue
        prog, letter, sub = PROGRAMME[m.group(1)], m.group(2), m.group(3)
        own = owner_of(prog, letter)
        if own in by_id and own != s.id:
            target[s.id] = (own, f"{letter}{sub}" if sub else "")
    if not target:
        return sections, lessons, entries
    # each owning section's lab groups: its own and every one another timetable refers to
    subs: dict[str, set[str]] = {}
    for own in {o for o, _ in target.values()}:
        subs[own] = {g.rsplit("-", 1)[1] for g in by_id[own].groups} - {"ALL"}
    for own, sub in target.values():
        if sub:
            subs[own].add(sub)
    for own, ss in subs.items():
        if ss:
            by_id[own].groups = [f"{own}-{x}" for x in sorted(ss)]

    def rewrite(b: str) -> list[str]:
        sid = b.rsplit("-", 1)[0]
        if sid in target:
            own, sub = target[sid]
            return [f"{own}-{sub}"] if sub else list(by_id[own].groups)
        if sid in subs and b.endswith("-ALL"):  # the owner's whole-section group became lab groups
            return list(by_id[sid].groups)
        return [b]
    for l in lessons:
        l.batches = sorted({x for b in l.batches for x in rewrite(b)})
    sections = [s for s in sections if s.id not in target]

    # one class written in two departments' timetables (same teacher, same students, same time): keep it once
    L = {l.id: l for l in lessons}
    sec_dept = {s.id: s.dept for s in sections}
    seen: dict[tuple, set[str]] = {}
    once = []
    for e in entries:
        l = L[e.lesson]
        if rooms[e.room].kind != "Other department":
            keys = [(t, e.day, e.start) for t in (l.teacher, *l.co_teachers) if not t.startswith("TBA-")]
            if any(set(l.batches) & seen.get(k, set()) for k in keys):
                continue
            for k in keys:
                seen.setdefault(k, set()).update(l.batches)
        once.append(e)
    entries = _renumber(once, lessons)

    # placeholders for hours "taught in another department": only the students' own department's count, and
    # not where a linked class now shows what actually happens
    real = defaultdict(set)
    for e in entries:
        if rooms[e.room].kind != "Other department":
            for b in L[e.lesson].batches:
                for q in e.slots:
                    real[b, e.day, q].add(e.lesson)
    keep = []
    for e in entries:
        l = L[e.lesson]
        if rooms[e.room].kind == "Other department" and l.code.startswith("Outside:"):
            left = [b for b in l.batches if sec_dept.get(b.rsplit("-", 1)[0]) == l.dept
                    and not any(real[b, e.day, q] for q in e.slots)]
            if not left:
                continue
            l.batches = left
        keep.append(e)
    used = {e.lesson for e in keep}
    return sections, [l for l in lessons if l.id in used], keep


def _renumber(entries: list, lessons: list[Lesson]) -> list:
    """After dropping duplicate sessions: number each lesson's sessions 0..n-1 again and set its count."""
    count: dict[str, int] = {}
    out = []
    for e in entries:
        out.append(replace(e, session=count.get(e.lesson, 0)))
        count[e.lesson] = count.get(e.lesson, 0) + 1
    for l in lessons:
        l.sessions = count.get(l.id, 0)
    return out


def _central() -> College:
    """Only the central venues of the seed (seminar halls, auditorium, lecture theatres, library reading room)."""
    seed = _build_seed(["CSE"])
    keep = [r for r in seed.rooms if r.kind in ("Seminar Hall", "Auditorium", "Lecture Theatre", "Study Area")]
    return College(DEPTS, keep, [], [], [], BUILDINGS)


def _build_seed(depts: list[str]) -> College:
    rooms: list[Room] = []
    teachers: list[Teacher] = []
    sections: list[Section] = []
    lessons: list[Lesson] = []

    # --- rooms -----------------------------------------------------------
    for d in depts:
        for i in range(1, 5):
            rooms.append(Room(f"{d}-20{i}", "Classroom", 66, d))
    rooms += [Room(f"CL-{i}", "Computer Lab", 36) for i in range(1, 6)]  # central computer labs
    rooms += [Room(f"ECE-Lab-{i}", "Electronics Lab", 32, "ECE") for i in range(1, 4)]
    rooms += [Room(f"ME-Lab-{i}", "Mechanical Lab", 32, "ME") for i in range(1, 4)]
    rooms += [Room(f"CE-Lab-{i}", "Civil Lab", 32, "CE") for i in range(1, 4)]
    rooms += [Room("LT-1", "Lecture Theatre", 120), Room("LT-2", "Lecture Theatre", 120),
              Room("Library Reading Room", "Study Area", 80)]
    # event venues (never used by the solver; bookable through the venues lane)
    rooms += [Room("WS SEMINAR HALL", "Seminar Hall", 150, None, "WS", "Ground",
                   ["projector", "sound", "ac", "stage"], sittable=False, bookable=True),
              Room("MBA Seminar Hall", "Seminar Hall", 120, "CSE", "MBA", "First",
                   ["projector", "sound", "ac"], sittable=False, bookable=True),
              Room("Auditorium", "Auditorium", 600, None, "MAIN", "Ground",
                   ["projector", "sound", "ac", "stage"], sittable=False, bookable=True)]
    _place_rooms(rooms)

    # --- teachers --------------------------------------------------------
    n = 0

    def new_teacher(dept: str, kind: str = "Regular", unavailable=None) -> Teacher:
        nonlocal n
        name = f"{TITLES[n % 3]} {FIRST[n % len(FIRST)]} {LAST[(n * 7) % len(LAST)]}"
        n += 1
        t = Teacher(f"T{n:02d}", name, dept, kind, unavailable or [])
        teachers.append(t)
        return t

    dept_teachers: dict[str, list[Teacher]] = {d: [new_teacher(d) for _ in range(TEACHERS_PER_DEPT)] for d in depts}
    # realism: one teacher has PhD coursework on Friday afternoons
    dept_teachers[depts[0]][2].unavailable = [(4, p) for p in range(5, 8)]
    as_teachers = [new_teacher("AS") for _ in range(3)]
    visiting_dept = "CSE" if "CSE" in depts else depts[0]
    visiting = new_teacher(visiting_dept, "Visiting", [(d, p) for d in (0, 2, 4) for p in range(len(PERIODS))])
    visiting.name = "Er. Kavya Malhotra (Visiting)"
    shared_pool = dept_teachers["CSE"] if "CSE" in depts else dept_teachers.get("IT", [])

    load: dict[str, int] = {t.id: 0 for t in teachers}

    def pick(pool: list[Teacher]) -> Teacher:
        return min(pool, key=lambda t: (load[t.id], t.id))

    # --- sections & lessons (GNDEC naming: D2-IT-A with lab groups A1/A2) --------------------
    for d in depts:
        for year in (2, 3):
            secs = []
            for letter, room_no in (("A", 1 if year == 2 else 3), ("B", 2 if year == 2 else 4)):
                sid = f"D{year}-{d}-{letter}"
                s = Section(sid, d, year, f"D{year} {d} {letter}", 60, f"{d}-20{room_no}",
                            [f"{sid}-{letter}1", f"{sid}-{letter}2"])
                sections.append(s)
                secs.append(s)

            theory, labs = CURRICULUM[d][year]
            work = [(name, code, hrs, "theory") for name, code, hrs in theory]
            work += [(name, code, 2, "lab") for name, code in labs]
            # heaviest first so the greedy balances load
            work.sort(key=lambda w: -(w[2] * 2 if w[3] == "theory" else 8))
            for name, code, hrs, kind in work:
                if d == "IT" and code in ("DS", "CN") and shared_pool is not dept_teachers[d]:
                    teacher = pick(shared_pool)  # shared across departments
                else:
                    teacher = pick(dept_teachers[d])
                for s in secs:
                    if kind == "theory":
                        lessons.append(Lesson(f"{s.id}:{code}", code, name, "theory", d, teacher.id, s.name,
                                              s.batches, hrs, 1, "Classroom", [s.home_room], s.size))
                        load[teacher.id] += hrs
                    else:
                        lab_rooms = [r.id for r in rooms if r.kind == LAB_KIND[d]]
                        for b in s.batches:
                            lessons.append(Lesson(f"{b}:{code}", code, name, "lab", d, teacher.id,
                                                  f"{s.name}{b[-1]}", [b], 1, 2, LAB_KIND[d], lab_rooms,
                                                  s.size // 2))
                            load[teacher.id] += 2

            for s in secs:
                if year == 2:
                    t = pick(as_teachers)
                    lessons.append(Lesson(f"{s.id}:M3", "M3", "Engineering Mathematics III", "theory", "AS",
                                          t.id, s.name, s.batches, 3, 1, "Classroom", [s.home_room], s.size))
                    load[t.id] += 3
                elif d == visiting_dept:
                    lessons.append(Lesson(f"{s.id}:SE", "SE", "Software Engineering", "theory", d,
                                          visiting.id, s.name, s.batches, 2, 1, "Classroom", [s.home_room], s.size))
                    load[visiting.id] += 2

    return College(DEPTS, rooms, teachers, sections, lessons, BUILDINGS)


if __name__ == "__main__":
    c = build_college()
    print(f"{len(c.sections)} sections, {len(c.teachers)} teachers, {len(c.rooms)} rooms, "
          f"{len(c.lessons)} lessons, {sum(l.sessions for l in c.lessons)} sessions")
    hours: dict[str, int] = {}
    for l in c.lessons:
        hours[l.teacher] = hours.get(l.teacher, 0) + l.sessions * l.duration
    for t in c.teachers:
        print(f"  {t.id} {t.name:38s} {t.dept:4s} {hours.get(t.id, 0):3d} h")

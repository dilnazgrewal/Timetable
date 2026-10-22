"""Synthetic GNDEC-like college: 5 departments x 4 sections (2nd & 3rd year, A/B), shared labs,
an Applied Sciences department teaching Maths to every 2nd-year section, teachers shared across
departments, and a visiting teacher available only Tue/Thu."""
from __future__ import annotations

from app.models import PERIODS, Building, College, Department, Lesson, Room, Section, Teacher

DEPTS = [
    Department("CSE", "Computer Science & Engineering"),
    Department("IT", "Information Technology"),
    Department("ECE", "Electronics & Communication"),
    Department("ME", "Mechanical Engineering"),
    Department("CE", "Civil Engineering"),
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

FLOORS = ["Ground", "First", "Second"]
BUILDINGS = [
    Building("MBA", "MBA Block (CSE & IT)", FLOORS),
    Building("ECE", "ECE Block", FLOORS),
    Building("MECH", "Mechanical Block", FLOORS),
    Building("CIVIL", "Civil Block", FLOORS),
    Building("MAIN", "Main Block", FLOORS),
    Building("WS", "Workshop Block", ["Ground"]),
]
DEPT_BUILDING = {"CSE": "MBA", "IT": "MBA", "ECE": "ECE", "ME": "MECH", "CE": "CIVIL"}


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
    rooms: list[Room] = []
    teachers: list[Teacher] = []
    sections: list[Section] = []
    lessons: list[Lesson] = []

    # --- rooms -----------------------------------------------------------
    for d in ["CSE", "IT", "ECE", "ME", "CE"]:
        for i in range(1, 5):
            rooms.append(Room(f"{d}-20{i}", "Classroom", 66, d))
    rooms += [Room(f"CL-{i}", "Computer Lab", 36) for i in range(1, 6)]  # central, shared CSE+IT
    rooms += [Room(f"ECE-Lab-{i}", "Electronics Lab", 32, "ECE") for i in range(1, 4)]
    rooms += [Room(f"ME-Lab-{i}", "Mechanical Lab", 32, "ME") for i in range(1, 4)]
    rooms += [Room(f"CE-Lab-{i}", "Civil Lab", 32, "CE") for i in range(1, 4)]
    rooms += [Room("LT-1", "Lecture Theatre", 120), Room("LT-2", "Lecture Theatre", 120),
              Room("Library Reading Room", "Study Area", 80)]
    # event venues (never used by the solver; bookable through the venues lane)
    rooms += [Room("WS Seminar Hall", "Seminar Hall", 150, None, "WS", "Ground",
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

    dept_teachers: dict[str, list[Teacher]] = {}
    for d in ["CSE", "IT", "ECE", "ME", "CE"]:
        dept_teachers[d] = [new_teacher(d) for _ in range(TEACHERS_PER_DEPT)]
    # realism: one CSE teacher has PhD coursework on Friday afternoons
    dept_teachers["CSE"][2].unavailable = [(4, p) for p in range(5, 8)]
    as_teachers = [new_teacher("AS") for _ in range(3)]
    visiting = new_teacher("CSE", "Visiting", [(d, p) for d in (0, 2, 4) for p in range(len(PERIODS))])
    visiting.name = "Er. Kavya Malhotra (Visiting)"

    load: dict[str, int] = {t.id: 0 for t in teachers}

    def pick(pool: list[Teacher]) -> Teacher:
        return min(pool, key=lambda t: (load[t.id], t.id))

    # --- sections & lessons ---------------------------------------------
    for d in ["CSE", "IT", "ECE", "ME", "CE"]:
        for year in (2, 3):
            secs = []
            for letter, room_no in (("A", 1 if year == 2 else 3), ("B", 2 if year == 2 else 4)):
                s = Section(f"{d}-{year}{letter}", d, year, f"{d} {year}{'nd' if year == 2 else 'rd'} yr {letter}",
                            60, f"{d}-20{room_no}")
                sections.append(s)
                secs.append(s)

            theory, labs = CURRICULUM[d][year]
            work = [(name, code, hrs, "theory") for name, code, hrs in theory]
            work += [(name, code, 2, "lab") for name, code in labs]
            # heaviest first so the greedy balances load
            work.sort(key=lambda w: -(w[2] * 2 if w[3] == "theory" else 8))
            for name, code, hrs, kind in work:
                if d == "IT" and code in ("DS", "CN"):
                    teacher = pick(dept_teachers["CSE"])  # shared across departments
                else:
                    teacher = pick(dept_teachers[d])
                for s in secs:
                    if kind == "theory":
                        lessons.append(Lesson(f"{s.id}:{code}", code, name, "theory", d, teacher.id, s.id,
                                              s.batches, hrs, 1, "Classroom", [s.home_room], s.size))
                        load[teacher.id] += hrs
                    else:
                        lab_rooms = [r.id for r in rooms if r.kind == LAB_KIND[d]]
                        for b in s.batches:
                            lessons.append(Lesson(f"{b}:{code}", code, name, "lab", d, teacher.id,
                                                  f"{s.id} {b[-2:]}", [b], 1, 2, LAB_KIND[d], lab_rooms,
                                                  s.size // 2))
                            load[teacher.id] += 2

            for s in secs:
                if year == 2:
                    t = pick(as_teachers)
                    lessons.append(Lesson(f"{s.id}:M3", "M3", "Engineering Mathematics III", "theory", "AS",
                                          t.id, s.id, s.batches, 3, 1, "Classroom", [s.home_room], s.size))
                    load[t.id] += 3
                elif d == "CSE":
                    lessons.append(Lesson(f"{s.id}:SE", "SE", "Software Engineering", "theory", "CSE",
                                          visiting.id, s.id, s.batches, 2, 1, "Classroom", [s.home_room], s.size))
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

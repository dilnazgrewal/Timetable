"""A small, made-up college filled in through the Excel template (not GNDEC data): it proves another college's data
goes in the same way.  python -m data.colleges.demo_institute.make_sample  ->  demo_institute.xlsx next to this file.
Then: python -m app.importers.sheets data/colleges/demo_institute/demo_institute.xlsx"""
from pathlib import Path

from app.importers.sheets import write_workbook

HERE = Path(__file__).resolve().parent

PROFILE = [
    ["College", "Demo Institute of Technology (made-up sample)"],
    ["Days", "Mon, Tue, Wed, Thu, Fri"],
    ["Periods", "09:00-10:00, 10:00-11:00, 11:00-12:00, 12:00-13:00, 13:00-14:00, 14:00-15:00, 15:00-16:00, 16:00-17:00"],
    ["Departments", "CS = Computer Science; EC = Electronics & Communication"],
]
ROOMS = [
    *[[f"A10{i}", "Classroom", 66, "Main Block", "First", "CS" if i <= 4 else "EC", "yes", "yes"] for i in range(1, 7)],
    ["A107", "Classroom", 66, "Main Block", "First", "", "yes", "yes"],
    ["CS-Lab-1", "Lab", 36, "Main Block", "Ground", "CS", "no", "no"],
    ["CS-Lab-2", "Lab", 36, "Main Block", "Ground", "CS", "no", "no"],
    ["EC-Lab-1", "Lab", 36, "Tech Block", "Ground", "EC", "no", "no"],
    ["EC-Lab-2", "Lab", 36, "Tech Block", "Ground", "EC", "no", "no"],
    ["Seminar Hall", "Hall", 150, "Main Block", "Ground", "", "no", "yes"],
]
TEACHERS = [
    ["RS", "Dr. Ritu Sharma", "CS", ""], ["AK", "Dr. Arjun Kapoor", "CS", "Fri 6-8"], ["NM", "Pf. Neha Malhotra", "CS", ""],
    ["VG", "Pf. Vikram Gill", "CS", ""], ["SB", "Dr. Simran Bedi", "CS", "Tue 1-2"], ["MK", "Pf. Manav Khanna", "CS", ""],
    ["PD", "Dr. Pooja Dhillon", "EC", ""], ["HS", "Pf. Harpreet Sidhu", "EC", ""], ["JA", "Dr. Jaspreet Arora", "EC", "Mon 1-3"],
    ["KT", "Pf. Karan Thakur", "EC", ""], ["LB", "Pf. Lovepreet Bains", "EC", ""],
]
CLASSES = [
    ["CS-1A", "CS", 1, 64, "A101", "G1, G2"], ["CS-1B", "CS", 1, 64, "A102", "G1, G2"],
    ["CS-2A", "CS", 2, 62, "A103", "G1, G2"], ["CS-2B", "CS", 2, 62, "A104", "G1, G2"],
    ["EC-1A", "EC", 1, 60, "A105", "G1, G2"], ["EC-2A", "EC", 2, 58, "A106", "G1, G2"],
]
CURRICULUM = {  # section -> [(code, name, teacher, hours, lab rooms or None for theory)]
    "CS-1": [("MATH1", "Engineering Mathematics I", "SB", 4, None), ("PHY", "Engineering Physics", "MK", 3, None),
             ("PROG", "Programming in C", "RS", 4, None), ("ENG", "Communication Skills", "MK", 2, None),
             ("PROG Lab", "Programming Lab", "VG", 2, "CS-Lab-1, CS-Lab-2")],
    "CS-2": [("DS", "Data Structures", "AK", 4, None), ("DBMS", "Database Systems", "NM", 3, None),
             ("MATH3", "Discrete Mathematics", "SB", 3, None), ("OS", "Operating Systems", "RS", 3, None),
             ("DS Lab", "Data Structures Lab", "AK", 2, "CS-Lab-1, CS-Lab-2"),
             ("DBMS Lab", "Database Lab", "NM", 2, "CS-Lab-1, CS-Lab-2")],
    "EC-1": [("MATH1", "Engineering Mathematics I", "SB", 4, None), ("PHY", "Engineering Physics", "KT", 3, None),
             ("BEE", "Basic Electrical Engineering", "PD", 4, None), ("ENG", "Communication Skills", "MK", 2, None),
             ("BEE Lab", "Electrical Lab", "LB", 2, "EC-Lab-1, EC-Lab-2")],
    "EC-2": [("SIG", "Signals and Systems", "JA", 4, None), ("DIG", "Digital Electronics", "HS", 3, None),
             ("MATH3", "Engineering Mathematics III", "KT", 3, None), ("NET", "Network Theory", "PD", 3, None),
             ("DIG Lab", "Digital Electronics Lab", "HS", 2, "EC-Lab-1, EC-Lab-2")],
}


def lessons() -> list[list]:
    out = []
    for sid, *_ in CLASSES:
        for code, name, teacher, hours, lab_rooms in CURRICULUM[sid[:4]]:
            if lab_rooms is None:
                out.append([code, name, teacher, sid, "", "Theory", hours, ""])
            else:
                out += [[code, name, teacher, sid, g, "Lab", hours, lab_rooms] for g in ("G1", "G2")]
    return out


def build(path: Path = HERE / "demo_institute.xlsx") -> Path:
    write_workbook(path, {"Profile": PROFILE, "Rooms": ROOMS, "Teachers": TEACHERS, "Classes": CLASSES,
                          "Lessons": lessons()})
    return path


if __name__ == "__main__":
    print("Written:", build())

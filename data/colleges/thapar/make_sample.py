"""An illustrative sample for Thapar Institute of Engineering & Technology, Patiala, filled in through the Excel
template. Made up in Thapar's style (departments, 50-minute periods from 8:00, U-coded courses): it is NOT Thapar's
real timetable, and the teachers are invented.
python -m data.colleges.thapar.make_sample  ->  thapar.xlsx next to this file.
Then: python -m app.importers.sheets data/colleges/thapar/thapar.xlsx"""
from pathlib import Path

from app.importers.sheets import write_workbook

HERE = Path(__file__).resolve().parent

PROFILE = [
    ["College", "Thapar Institute of Engineering & Technology, Patiala (illustrative sample)"],
    ["Days", "Mon, Tue, Wed, Thu, Fri"],
    ["Periods", "08:00-08:50, 08:50-09:40, 09:40-10:30, 10:30-11:20, 11:20-12:10, 12:10-13:00, 13:00-13:50, 13:50-14:40"],
    ["Departments", "CSED = Computer Science & Engineering; ECED = Electronics & Communication Engineering; "
                    "MED = Mechanical Engineering; SOM = School of Mathematics; SHSS = School of Humanities & Social Sciences"],
]
ROOMS = [
    *[[f"B-10{i}", "Classroom", 72, "B Block", "First", "CSED", "yes", "yes"] for i in range(1, 6)],
    ["E-201", "Classroom", 72, "E Block", "Second", "ECED", "yes", "yes"],
    ["E-202", "Classroom", 72, "E Block", "Second", "ECED", "yes", "yes"],
    ["G-101", "Classroom", 72, "G Block", "First", "MED", "yes", "yes"],
    ["G-102", "Classroom", 72, "G Block", "First", "MED", "yes", "yes"],
    ["LT-301", "Classroom", 120, "LT Block", "Third", "", "yes", "yes"],
    ["CSED Lab 1", "Lab", 36, "B Block", "Ground", "CSED", "no", "no"],
    ["CSED Lab 2", "Lab", 36, "B Block", "Ground", "CSED", "no", "no"],
    ["CSED Lab 3", "Lab", 36, "B Block", "Ground", "CSED", "no", "no"],
    ["ECED Analog Lab", "Lab", 36, "E Block", "Ground", "ECED", "no", "no"],
    ["ECED Digital Lab", "Lab", 36, "E Block", "Ground", "ECED", "no", "no"],
    ["MED SOM Lab", "Lab", 36, "G Block", "Ground", "MED", "no", "no"],
    ["MED Workshop", "Lab", 36, "G Block", "Ground", "MED", "no", "no"],
    ["LT Seminar Hall", "Hall", 200, "LT Block", "Ground", "", "no", "yes"],
    ["Main Auditorium", "Hall", 800, "Central", "Ground", "", "no", "yes"],
]
TEACHERS = [
    ["AV", "Dr. Anil Verma", "CSED", ""], ["MR", "Dr. Meenakshi Rana", "CSED", "Wed 7-8"],
    ["RB", "Dr. Rohit Bansal", "CSED", ""], ["SM", "Dr. Shalini Mehta", "CSED", "Fri 6-8"],
    ["GS", "Dr. Gaurav Sood", "CSED", ""], ["TA", "Dr. Tanvi Arora", "CSED", ""],
    ["KS", "Mr. Karanveer Singh", "CSED", ""], ["IJ", "Ms. Ishita Jain", "CSED", "Mon 1-2"],
    ["NS", "Dr. Neeraj Saini", "ECED", ""], ["PW", "Dr. Priya Walia", "ECED", "Thu 7-8"],
    ["HV", "Dr. Harsh Vardhan", "ECED", ""], ["RC", "Ms. Ritika Chawla", "ECED", ""],
    ["MB", "Dr. Manpreet Brar", "MED", ""], ["SY", "Dr. Suresh Yadav", "MED", "Tue 1-3"],
    ["AM", "Mr. Amandeep Virk", "MED", ""], ["KN", "Ms. Kavya Nanda", "MED", ""],
    ["RJ", "Dr. Rajni Sethi", "SOM", ""], ["MA", "Dr. Mohit Ahuja", "SOM", ""],
    ["NK", "Dr. Nidhi Kalra", "SHSS", "Fri 1-4"],
]
CLASSES = [
    ["2COE1", "CSED", 2, 60, "B-101", "G1, G2"], ["2COE2", "CSED", 2, 60, "B-102", "G1, G2"],
    ["2COE3", "CSED", 2, 60, "B-103", "G1, G2"], ["3COE1", "CSED", 3, 60, "B-104", "G1, G2"],
    ["3COE2", "CSED", 3, 60, "B-105", "G1, G2"], ["2ECE1", "ECED", 2, 60, "E-201", "G1, G2"],
    ["2ECE2", "ECED", 2, 60, "E-202", "G1, G2"], ["2MEE1", "MED", 2, 60, "G-101", "G1, G2"],
    ["2MEE2", "MED", 2, 60, "G-102", "G1, G2"],
]
CSED_LABS, ECED_LABS = "CSED Lab 1, CSED Lab 2, CSED Lab 3", "ECED Analog Lab, ECED Digital Lab"
# section without its number -> [(code, name, teachers by section number (cycled), hours, lab rooms or None for theory)]
CURRICULUM = {
    "2COE": [("UCS301", "Data Structures", ("AV", "AV", "MR"), 4, None),
             ("UCS303", "Operating Systems", ("RB",), 3, None),
             ("UCS310", "Database Management Systems", ("SM", "SM", "GS"), 3, None),
             ("UMA021", "Discrete Mathematical Structures", ("RJ", "RJ", "MA"), 3, None),
             ("UHU005", "Humanities for Engineers", ("NK",), 2, None),
             ("UCS301 Lab", "Data Structures Lab", ("TA", "KS", "TA"), 2, CSED_LABS),
             ("UCS310 Lab", "Database Management Systems Lab", ("IJ", "IJ", "KS"), 2, CSED_LABS)],
    "3COE": [("UCS414", "Computer Networks", ("MR", "GS"), 3, None),
             ("UCS503", "Software Engineering", ("GS", "SM"), 3, None),
             ("UCS415", "Design & Analysis of Algorithms", ("TA", "AV"), 4, None),
             ("UCS521", "Artificial Intelligence", ("RB",), 3, None),
             ("UCS414 Lab", "Computer Networks Lab", ("KS", "IJ"), 2, CSED_LABS),
             ("UCS415 Lab", "Algorithms Lab", ("TA", "MR"), 2, CSED_LABS)],
    "2ECE": [("UEC301", "Analog Electronic Circuits", ("NS",), 4, None),
             ("UEC302", "Signals and Systems", ("PW",), 3, None),
             ("UEC303", "Digital Electronics", ("HV",), 3, None),
             ("UMA032", "Numerical Analysis", ("MA",), 3, None),
             ("UHU005", "Humanities for Engineers", ("NK",), 2, None),
             ("UEC301 Lab", "Analog Electronics Lab", ("RC",), 2, "ECED Analog Lab"),
             ("UEC303 Lab", "Digital Electronics Lab", ("HV", "RC"), 2, "ECED Digital Lab")],
    "2MEE": [("UME301", "Engineering Thermodynamics", ("MB",), 4, None),
             ("UME302", "Strength of Materials", ("SY",), 4, None),
             ("UME303", "Manufacturing Processes", ("AM",), 3, None),
             ("UMA032", "Numerical Analysis", ("RJ",), 3, None),
             ("UME302 Lab", "Strength of Materials Lab", ("KN",), 2, "MED SOM Lab"),
             ("UME303 Lab", "Manufacturing Workshop", ("AM", "KN"), 2, "MED Workshop")],
}


def lessons() -> list[list]:
    out = []
    for sid, *_ in CLASSES:
        n = int(sid[-1]) - 1
        for code, name, teachers, hours, lab_rooms in CURRICULUM[sid[:-1]]:
            teacher = teachers[n % len(teachers)]
            if lab_rooms is None:
                out.append([code, name, teacher, sid, "", "Theory", hours, ""])
            else:
                out += [[code, name, teacher, sid, g, "Lab", hours, lab_rooms] for g in ("G1", "G2")]
    return out


def build(path: Path = HERE / "thapar.xlsx") -> Path:
    write_workbook(path, {"Profile": PROFILE, "Rooms": ROOMS, "Teachers": TEACHERS, "Classes": CLASSES,
                          "Lessons": lessons()})
    return path


if __name__ == "__main__":
    print("Written:", build())

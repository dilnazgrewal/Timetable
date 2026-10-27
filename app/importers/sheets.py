"""Bring any college's data into TimeWeave from one Excel workbook (the onboarding path for colleges that don't use FET).

The workbook has five sheets. Write a blank one with:  python -m app.importers.sheets --template college_template.xlsx
  Profile   key / value: college name, working days, period times, departments
  Rooms     Room, Type (Classroom / Lab / Hall), Seats, Building, Floor, Department, Students may sit, Bookable
  Teachers  Code, Name, Department, Not available (e.g. "Fri 6-8; Tue 1")
  Classes   Section, Department, Year, Students, Home room, Lab groups (e.g. "G1, G2")
  Lessons   Subject code, Subject name, Teacher, Section, Lab group, Type (Theory / Lab), Hours per week, Lab rooms

Every mistake is reported in plain words with its sheet and row ("Lessons row 12: teacher 'XYZ' is not on the Teachers
sheet"), and nothing is imported until the workbook is clean. With no current timetable in it, TimeWeave generates
one (CP-SAT) and the independent validator checks it:
    python -m app.importers.sheets data/colleges/demo_institute/demo_institute.xlsx [--out timetable.xlsx]

Today the engine's week is 5 days x 8 periods with the midday break in periods 4-6, so a college's own period times
are used for display; moving the grid itself into the profile is the next step (see PLAN.md).
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.models import DAYS, SOLVER_PERIODS, Building, College, Department, Lesson, Room, Section, Teacher

SHEETS = {
    "Profile": ["Key", "Value"],
    "Rooms": ["Room", "Type", "Seats", "Building", "Floor", "Department", "Students may sit", "Bookable"],
    "Teachers": ["Code", "Name", "Department", "Not available"],
    "Classes": ["Section", "Department", "Year", "Students", "Home room", "Lab groups"],
    "Lessons": ["Subject code", "Subject name", "Teacher", "Section", "Lab group", "Type", "Hours per week", "Lab rooms"],
}
HELP = {  # first row under the header in the blank template: what goes in each column
    "Profile": [["College", "Your college's name"], ["Days", "Mon, Tue, Wed, Thu, Fri"],
                ["Periods", "09:00-10:00, 10:00-11:00, 11:00-12:00, 12:00-13:00, 13:00-14:00, 14:00-15:00"],
                ["Departments", "CS = Computer Science; EC = Electronics"]],
    "Rooms": [["R101", "Classroom", 60, "Main Block", "First", "CS", "yes", "yes"],
              ["Lab-1", "Lab", 32, "Main Block", "Ground", "CS", "no", "no"]],
    "Teachers": [["AK", "Dr. A. Kumar", "CS", "Fri 5-6"]],
    "Classes": [["CS-2A", "CS", 2, 60, "R101", "G1, G2"]],
    "Lessons": [["DS", "Data Structures", "AK", "CS-2A", "", "Theory", 4, ""],
                ["DS Lab", "Data Structures Lab", "AK", "CS-2A", "G1", "Lab", 2, "Lab-1"]],
}
ROOM_KINDS = {"classroom": "Classroom", "lab": "Lab", "hall": "Seminar Hall"}


@dataclass
class Workbook:
    """The rows of each sheet as dicts (header -> value), with their Excel row numbers."""
    rows: dict[str, list[tuple[int, dict]]] = field(default_factory=dict)


def write_workbook(path: Path, data: dict[str, list[list]]) -> None:
    from openpyxl import Workbook as XL
    from openpyxl.styles import Font, PatternFill

    wb = XL()
    wb.remove(wb.active)
    for name, header in SHEETS.items():
        ws = wb.create_sheet(name)
        ws.append(header)
        for c in ws[1]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="4F46E5")
        for row in data.get(name, []):
            ws.append(row)
        for i, h in enumerate(header):
            ws.column_dimensions[chr(65 + i)].width = max(14, len(h) + 4)
    if isinstance(path, Path):  # or a file object (the website's download)
        path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def read_workbook(path: Path) -> tuple[Workbook, list[str]]:
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True)
    out, errors = Workbook(), []
    for name, header in SHEETS.items():
        if name not in wb.sheetnames:
            errors.append(f"The workbook has no '{name}' sheet (needed: {', '.join(SHEETS)}).")
            continue
        ws = wb[name]
        got = [str(c.value).strip() if c.value is not None else "" for c in ws[1]]
        missing = [h for h in header if h not in got]
        if missing:
            errors.append(f"{name}: missing column(s) {', '.join(missing)}.")
            continue
        rows = []
        for r, values in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            row = {h: values[got.index(h)] if got.index(h) < len(values) else None for h in header}
            if any(v not in (None, "") for v in row.values()):
                rows.append((r, {k: (str(v).strip() if isinstance(v, str) else v) for k, v in row.items()}))
        out.rows[name] = rows
    return out, errors


def _yes(v) -> bool:
    return str(v or "").strip().lower() in ("yes", "y", "true", "1")


def _int(v) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _unavailable(text: str, n_periods: int = SOLVER_PERIODS) -> tuple[list[tuple[int, int]], str | None]:
    """'Fri 6-8; Tue 1' -> [(4, 5), (4, 6), (4, 7), (1, 0)]  (periods are 1-based in the sheet)."""
    out = []
    for part in [p.strip() for p in re.split(r"[;,]", text or "") if p.strip()]:
        m = re.match(r"^(Mon|Tue|Wed|Thu|Fri)\w*\s+(\d)(?:\s*-\s*(\d))?$", part, re.I)
        if not m:
            return [], f"'{part}' should look like 'Fri 6-8' or 'Tue 1'"
        day = DAYS.index(m.group(1).title()[:3])
        a, b = int(m.group(2)), int(m.group(3) or m.group(2))
        if not 1 <= a <= b <= n_periods:
            return [], f"'{part}': periods are 1 to {n_periods}"
        out += [(day, p - 1) for p in range(a, b + 1)]
    return out, None


def build_college(wb: Workbook) -> tuple[College | None, dict, list[str]]:
    """Workbook -> College (lessons ready for the generator), the profile, and every problem found."""
    errors: list[str] = []
    profile = {str(r["Key"]).strip().lower(): r["Value"] for _, r in wb.rows.get("Profile", []) if r["Key"]}
    days = [d.strip()[:3].title() for d in str(profile.get("days") or "Mon, Tue, Wed, Thu, Fri").split(",")]
    if days != DAYS:
        errors.append(f"Profile: Days must be {', '.join(DAYS)} for now (got {', '.join(days)}).")
    periods = [p.strip() for p in str(profile.get("periods") or "").split(",") if p.strip()]
    if not periods or len(periods) > SOLVER_PERIODS or not all(re.match(r"^\d{1,2}:\d{2}-\d{1,2}:\d{2}$", p) for p in periods):
        errors.append(f"Profile: Periods should be like '09:00-10:00, 10:00-11:00' (1 to {SOLVER_PERIODS} of them).")
    n_periods = len(periods) if periods and len(periods) <= SOLVER_PERIODS else SOLVER_PERIODS
    depts = {}
    for part in str(profile.get("departments") or "").split(";"):
        if "=" in part:
            code, name = part.split("=", 1)
            depts[code.strip()] = name.strip()
    if not depts:
        errors.append("Profile: Departments should be like 'CS = Computer Science; EC = Electronics'.")

    rooms: dict[str, Room] = {}
    for r, row in wb.rows.get("Rooms", []):
        rid, kind = str(row["Room"] or ""), ROOM_KINDS.get(str(row["Type"] or "").lower())
        seats = _int(row["Seats"])
        if not rid:
            errors.append(f"Rooms row {r}: the room has no name.")
        elif rid in rooms:
            errors.append(f"Rooms row {r}: '{rid}' is listed twice.")
        elif kind is None:
            errors.append(f"Rooms row {r}: Type should be Classroom, Lab or Hall (got '{row['Type']}').")
        elif not seats or seats < 1:
            errors.append(f"Rooms row {r}: Seats should be a number.")
        elif row["Department"] and row["Department"] not in depts:
            errors.append(f"Rooms row {r}: department '{row['Department']}' is not in the Profile's Departments.")
        else:
            rooms[rid] = Room(rid, kind, seats, row["Department"] or None, str(row["Building"] or ""),
                              str(row["Floor"] or ""), ["projector"], sittable=_yes(row["Students may sit"]),
                              bookable=_yes(row["Bookable"]))

    teachers: dict[str, Teacher] = {}
    for r, row in wb.rows.get("Teachers", []):
        tid = str(row["Code"] or "")
        off, problem = _unavailable(str(row["Not available"] or ""), n_periods)
        # a shorter college day: the periods after it don't exist, so nobody teaches then
        off = sorted(set(off) | {(d, q) for d in range(len(DAYS)) for q in range(n_periods, SOLVER_PERIODS)})
        if not tid or not row["Name"]:
            errors.append(f"Teachers row {r}: a teacher needs a Code and a Name.")
        elif tid in teachers:
            errors.append(f"Teachers row {r}: code '{tid}' is used twice.")
        elif row["Department"] not in depts:
            errors.append(f"Teachers row {r}: department '{row['Department']}' is not in the Profile's Departments.")
        elif problem:
            errors.append(f"Teachers row {r}: Not available {problem}.")
        else:
            teachers[tid] = Teacher(tid, str(row["Name"]), row["Department"], unavailable=off, max_per_day=SOLVER_PERIODS)

    sections: dict[str, Section] = {}
    for r, row in wb.rows.get("Classes", []):
        sid, year, size = str(row["Section"] or ""), _int(row["Year"]), _int(row["Students"])
        groups = [g.strip() for g in str(row["Lab groups"] or "").split(",") if g.strip()]
        if not sid or sid in sections:
            errors.append(f"Classes row {r}: section '{sid}' is missing or listed twice.")
        elif row["Department"] not in depts:
            errors.append(f"Classes row {r}: department '{row['Department']}' is not in the Profile's Departments.")
        elif not year or not size:
            errors.append(f"Classes row {r}: Year and Students should be numbers.")
        elif row["Home room"] not in rooms or rooms[row["Home room"]].kind != "Classroom":
            errors.append(f"Classes row {r}: home room '{row['Home room']}' is not a classroom on the Rooms sheet.")
        else:
            sections[sid] = Section(sid, row["Department"], year, sid, size, row["Home room"],
                                    [f"{sid}-{g}" for g in groups] or [f"{sid}-ALL"])

    lessons: list[Lesson] = []
    labs = sorted(r.id for r in rooms.values() if r.kind == "Lab")
    for r, row in wb.rows.get("Lessons", []):
        code, tid, sid = str(row["Subject code"] or ""), str(row["Teacher"] or ""), str(row["Section"] or "")
        kind, hours, group = str(row["Type"] or "").lower(), _int(row["Hours per week"]), str(row["Lab group"] or "")
        s = sections.get(sid)
        if not code:
            errors.append(f"Lessons row {r}: the subject has no code.")
        elif tid not in teachers:
            errors.append(f"Lessons row {r}: teacher '{tid}' is not on the Teachers sheet.")
        elif s is None:
            errors.append(f"Lessons row {r}: section '{sid}' is not on the Classes sheet.")
        elif kind not in ("theory", "lab"):
            errors.append(f"Lessons row {r}: Type should be Theory or Lab.")
        elif not hours or hours < 1:
            errors.append(f"Lessons row {r}: Hours per week should be a number.")
        elif kind == "lab" and hours % 2:
            errors.append(f"Lessons row {r}: labs come in 2-hour blocks, so hours should be even (got {hours}).")
        elif group and f"{sid}-{group}" not in s.groups:
            errors.append(f"Lessons row {r}: section '{sid}' has no lab group '{group}'.")
        elif kind == "theory":
            lessons.append(Lesson(f"{sid}:{code}", code, str(row["Subject name"] or code), "theory", s.dept, tid, sid,
                                  list(s.groups), hours, 1, "Classroom", [s.home_room], s.size))
        else:
            wanted = [x.strip() for x in str(row["Lab rooms"] or "").split(",") if x.strip()] or labs
            unknown = [x for x in wanted if x not in rooms or rooms[x].kind != "Lab"]
            batches = [f"{sid}-{group}"] if group else list(s.groups)
            size = s.size // len(s.groups) if group else s.size
            if unknown:
                errors.append(f"Lessons row {r}: lab room(s) {', '.join(unknown)} are not labs on the Rooms sheet.")
            elif not [x for x in wanted if rooms[x].capacity >= size]:
                errors.append(f"Lessons row {r}: no listed lab seats {size} students.")
            else:
                lessons.append(Lesson(f"{sid}:{code}:{group or 'ALL'}", code, str(row["Subject name"] or code), "lab",
                                      s.dept, tid, f"{sid} {group}".strip(), batches, hours // 2, 2, "Lab", wanted, size))
    for s in sections.values():
        if rooms.get(s.home_room) and rooms[s.home_room].capacity < s.size:
            errors.append(f"Classes: {s.id} has {s.size} students but its home room {s.home_room} seats "
                          f"{rooms[s.home_room].capacity}.")
    if errors:
        return None, profile, errors
    buildings = sorted({r.building for r in rooms.values() if r.building})
    college = College([Department(c, n) for c, n in depts.items()], list(rooms.values()), list(teachers.values()),
                      list(sections.values()), lessons,
                      [Building(b, b, sorted({r.floor for r in rooms.values() if r.building == b})) for b in buildings])
    return college, {**profile, "period_times": periods}, []


def section_grid(college: College, entries: list, s: Section) -> dict[tuple[int, int], list[str]]:
    """(day, period) -> what the section has then, e.g. 'DS Lab [G1] · AK · CS-Lab-1'."""
    grid: dict[tuple[int, int], list[str]] = {}
    for e in entries:
        l = college.lesson_by_id[e.lesson]
        if set(l.batches) & set(s.groups):
            for q in e.slots:
                who = "" if set(s.groups) <= set(l.batches) else f" [{l.section.split()[-1]}]"
                grid.setdefault((e.day, q), []).append(f"{l.code}{who} · {l.teacher} · {e.room}")
    return grid


def write_timetable(path, college: College, entries: list, periods: list[str]) -> None:
    """One sheet per section: days across, the college's own period times down (path may be a file object)."""
    from openpyxl import Workbook as XL
    from openpyxl.styles import Alignment, Font

    wb = XL()
    wb.remove(wb.active)
    for s in college.sections:
        ws = wb.create_sheet(s.id[:31])
        ws.append(["Period", *DAYS])
        grid = section_grid(college, entries, s)
        for p, label in enumerate(periods):
            ws.append([label, *["\n".join(grid.get((d, p), [])) for d in range(len(DAYS))]])
        for c in ws[1]:
            c.font = Font(bold=True)
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")
        for col in "BCDEF":
            ws.column_dimensions[col].width = 28
    wb.save(path)


def main(argv: list[str]) -> int:
    from app.solver import solve
    from app.validator import metrics, split_issues, validate

    if argv[:1] == ["--template"]:
        target = Path(argv[1] if len(argv) > 1 else "college_template.xlsx")
        write_workbook(target, HELP)
        print(f"Blank template with one example row per sheet: {target}")
        return 0
    if not argv:
        print(__doc__)
        return 1
    src = Path(argv[0])
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else src.with_name("timetable.xlsx")
    wb, errors = read_workbook(src)
    college, profile, more = build_college(wb) if not errors else (None, {}, [])
    errors += more
    if errors:
        print(f"{len(errors)} problem(s) to fix in {src.name}; nothing was imported:")
        for e in errors:
            print("  -", e)
        return 2
    print(f"{profile.get('college')}: {len(college.departments)} departments, {len(college.rooms)} rooms, "
          f"{len(college.teachers)} teachers, {len(college.sections)} sections, {len(college.lessons)} lessons, "
          f"{sum(l.sessions for l in college.lessons)} weekly sessions")
    res = solve(college, time_limit=30)
    if not res.entries:
        print("No timetable is possible:", *res.problems, sep="\n  - ")
        return 3
    clashes, notes = split_issues(validate(college, res.entries))
    m = metrics(college, res.entries)
    print(f"Generated ({res.status}, {res.seconds:.1f} s). Independent validator: {len(clashes)} clashes. "
          f"Student waiting periods per day: {m['idle_per_day']}; days with a single lecture: {m['lonely_days']}.")
    write_timetable(out, college, res.entries, profile["period_times"])
    print(f"Timetable written to {out}")
    return 0 if not clashes else 4


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

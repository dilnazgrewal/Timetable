"""Who actually sits in which class: GNDEC CSE distribution lists -> "student types".

In GNDEC's FET timetable the numbered sub-groups of 3rd and 4th year (A1..A6, A1..A5) are *slots*
that FET re-uses for different things: the 2nd option of Elective-III, the 2nd option of Elective-IV
and Technical-Aptitude lab batch 2 are all called "...A2", although they are different students.
A real student is: section + actual group + the options they chose. So we read the department's
distribution lists and build one *student type* per combination that really exists, with the exact
set of classes those students attend. Validator and optimiser then guarantee no clash for every type.

Privacy: the lists contain names and roll numbers. They stay in data/private/ (git-ignored); only
anonymous combinations with student counts are written to data/gndec/students.json.

    python -m app.importers.gndec_students     # reads data/private/*.pdf, writes data/gndec/students.json
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from app.models import College, Lesson, StudentType

ROOT = Path(__file__).resolve().parent.parent.parent
PRIVATE = ROOT / "data" / "private"
OUT = ROOT / "data" / "gndec" / "students.json"
D4_LIST = PRIVATE / "d4_2023-2027_electives.pdf"  # Departmental Elective-III, Elective-IV + TA lab groups
D3_LIST = PRIVATE / "d3_2024-2028_electives.pdf"  # departmental elective (by track), elective section + lab group

# list wording -> FET subject code
D4_ELECTIVE_III = {"Computer Vision": "CV", "DAAA": "DAAA", "DWDM": "DWDM", "SDN": "SDN"}
D4_ELECTIVE_IV = {"ACC": "ACC", "SC": "SC", "WT": "WT"}
D3_TRACK_ELECTIVE = {"Artificial Intelligence": "GAI", "Cyber Security": "CNS", "Data": "DWBI", "Software": "OOAD"}

ROW = re.compile(r"(\d{7})\s+(\d{7})\s+([A-F][12])\s+(Track\s*\d+\s*:?\s*[^\d]*?)(?=\s+\d{1,3}\s|\Z)", re.S)


def _text(path: Path, pages: range | None = None) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    idx = pages if pages is not None else range(1, len(reader.pages) + 1)
    return " ".join((reader.pages[i - 1].extract_text() or "") for i in idx)


def _rows(text: str) -> list[tuple[str, str, str]]:
    """-> [(crn, actual_group, tail)] where tail is everything after the group up to the next row."""
    text = re.sub(r"\s+", " ", text)
    starts = [m for m in re.finditer(r"(\d{7}) (\d{7}) ([A-F][12]) ", text)]
    out = []
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        out.append((m.group(1), m.group(3), text[m.end():end]))
    return out


def parse_d4(path: Path = D4_LIST) -> list[dict]:
    """One dict per student (in memory only): section, actual group, Elective-III, Elective-IV (+ lab group), TA group."""
    e3 = {}
    for crn, grp, tail in _rows(_text(path, range(7, 13))):
        choice = next((code for name, code in D4_ELECTIVE_III.items() if re.search(rf"\b{re.escape(name)}\b", tail)), None)
        e3[crn] = (grp, choice)
    students, ta_markers = [], []
    rows = _rows(_text(path, range(13, 19)))
    for i, (crn, grp, tail) in enumerate(rows):
        m = re.search(r"\b(ACC|SC|WT)\b\s*(?:\(\s*(A[12])\s*Group\s*\))?", tail.replace("( ", "("))
        if not m:
            m = re.search(r"\b(ACC|SC|WT)\b\s*\(?(A[12])?", tail)
        lab = re.search(r"\((A[12])", tail)
        for t in re.finditer(r"\bTA\s*A(\d)\b", tail):
            ta_markers.append((i, int(t.group(1))))
        students.append({"crn": crn, "actual": grp, "e4": D4_ELECTIVE_IV[m.group(1)] if m else None,
                         "e4_lab": lab.group(1) if lab and m and m.group(1) != "WT" else ""})
    # The TA column is one merged cell per block of consecutive rows (the printed list has its borders after
    # rows 30, 60, 90, 120): equal blocks in list order, as many as there are TA labels.
    labels = sorted({k for _, k in ta_markers})
    size = -(-len(students) // len(labels)) if labels else len(students)
    for i, s in enumerate(students):
        s["ta"] = labels[min(i // size, len(labels) - 1)] if labels else None
    for s in students:
        s["e3"] = e3.get(s["crn"], (None, None))[1]
        s["section"] = f"D4-CS-{s['actual'][0]}"
    return students


def parse_d3(path: Path = D3_LIST) -> list[dict]:
    students = []
    for crn, grp, tail in _rows(_text(path)):
        track = re.search(r"Track\s*\d+\s*:\s*([A-Za-z ]+?)\s+([AB][12])\b", tail)
        if not track:
            continue
        elective = next((code for key, code in D3_TRACK_ELECTIVE.items() if key.lower() in track.group(1).lower()), None)
        lab = track.group(2)
        students.append({"crn": crn, "actual": grp, "section": f"D3-CS-{grp[0]}", "elective": elective,
                         "el_section": lab[0], "el_lab": lab})
    return students


def combinations() -> dict:
    """Anonymous combinations with counts (what goes into data/gndec/students.json)."""
    out = {}
    d4 = parse_d4()
    c4 = Counter((s["section"], s["actual"], s["e3"], s["e4"], s["e4_lab"], s["ta"]) for s in d4)
    out["D4"] = [{"section": k[0], "actual": k[1], "elective_iii": k[2], "elective_iv": k[3], "elective_iv_lab": k[4],
                  "ta_lab": k[5], "count": n} for k, n in sorted(c4.items(), key=lambda kv: tuple(str(x) for x in kv[0]))]
    d3 = parse_d3()
    c3 = Counter((s["section"], s["actual"], s["elective"], s["el_section"], s["el_lab"]) for s in d3)
    out["D3"] = [{"section": k[0], "actual": k[1], "elective": k[2], "elective_section": k[3], "elective_lab": k[4],
                  "count": n} for k, n in sorted(c3.items(), key=lambda kv: tuple(str(x) for x in kv[0]))]
    out["source"] = {"D4": "Elective Track distribution lists 2023-2027 batch (Departmental Elective-III, -IV, TA lab)",
                     "D3": "Elective Sections and Lab groups list (2024-2028 batch), cse.gndec.ac.in"}
    return out


# Elective-IV labs run twice a week, once per lab group, but FET lists both sessions under one activity.
# Which day is which group was confirmed by a student (SC A1 group = Thursday 11:30): A1 groups on
# Thursday, A2 groups on Friday. Web Tech has a single lab group.
LAB_GROUP_DAY = {"SC Lab": {3: "A1", 4: "A2"}, "ACC Lab": {3: "A1", 4: "A2"}}


def split_lab_groups(college: College) -> None:
    """Give each Elective-IV lab group its own lesson (e.g. 'SC Lab A1' on Thursday, 'SC Lab A2' on Friday)."""
    from dataclasses import replace

    for l in [l for l in college.lessons if l.fixed and l.code in LAB_GROUP_DAY]:
        days = LAB_GROUP_DAY[l.code]
        mine = [e for e in college.fixed_entries if e.lesson == l.id]
        if not mine or any(e.day not in days for e in mine):
            continue  # the data doesn't match what we know: leave it as published
        for grp in sorted(set(days.values())):
            ents = sorted((e for e in mine if days[e.day] == grp), key=lambda e: (e.day, e.start))
            if not ents:
                continue
            new = replace(l, id=f"{l.id}-{grp}", code=f"{l.code} {grp}", name=f"{l.name} ({grp} group)",
                          sessions=len(ents), rooms=sorted({e.room for e in ents}))
            college.lessons.append(new)
            for k, e in enumerate(ents):
                college.fixed_entries[college.fixed_entries.index(e)] = replace(e, lesson=new.id, session=k)
        college.lessons.remove(l)
    college.__post_init__()


# --- combinations -> the exact classes each student type attends ----------------------------------
D4_E3_CODES, D4_E4_CODES = set(D4_ELECTIVE_III.values()), set(D4_ELECTIVE_IV.values())
D3_ELECTIVES = set(D3_TRACK_ELECTIVE.values())


def _base(code: str) -> str:
    return code.split(" ")[0]


def _in_section(l: Lesson, section: str) -> bool:
    return any(b.startswith(section + "-") for b in l.batches)


def d4_lessons(college: College, c: dict) -> tuple[list[str], list[str]]:
    sec = c["section"]
    letter = sec[-1]
    mine, unknown = [], []
    for l in college.lessons:
        if not _in_section(l, sec):
            continue
        base = _base(l.code)
        if base in D4_E3_CODES:
            ok = base == c["elective_iii"]
        elif base in D4_E4_CODES:
            group = l.code.rsplit(" ", 1)[-1] if l.code.endswith((" A1", " A2")) else ""
            ok = base == c["elective_iv"] and (not group or group == c["elective_iv_lab"])  # own lab group only
        elif l.code.startswith("TA Lab"):
            ok = f"{sec}-{letter}{c['ta_lab']}" in l.batches
        elif set(l.batches) >= set(college.section_by_id[sec].groups) or base == "MC":
            ok = True  # the whole section (project, JPAL, mentoring)
        else:
            ok = False
            unknown.append(l.id)
        if ok:
            mine.append(l.id)
    return mine, unknown


def d3_lessons(college: College, c: dict) -> tuple[list[str], list[str]]:
    sec = c["section"]
    own = f"{sec}-{c['actual']}"
    mine, unknown = [], []
    for l in college.lessons:
        if not _in_section(l, sec):
            continue
        base = _base(l.code)
        if base in D3_ELECTIVES:
            rest = l.code[len(base):].strip()  # "Group A" / "Lab A1"
            ok = base == c["elective"] and rest in (f"Group {c['elective_section']}", f"Lab {c['elective_lab']}")
            if base == c["elective"] and not rest.startswith(("Group", "Lab")):
                unknown.append(l.id)
        else:
            ok = own in l.batches  # section classes and the actual group's own labs
        if ok:
            mine.append(l.id)
    return mine, unknown


def student_types(college: College, data: dict) -> tuple[list[StudentType], list[str]]:
    """Build student types for every section: from the lists where we have them (D3, D4), otherwise one per
    FET group (D1, D2, M.Tech, PhD and generated departments, where groups really are lab groups)."""
    types, problems = [], []
    covered = set()
    for c in data.get("D4", []):
        lessons, unknown = d4_lessons(college, c)
        name = (f"{c['section'].replace('-', ' ')} · {c['actual']} · {c['elective_iii']} · "
                f"{c['elective_iv']}{' ' + c['elective_iv_lab'] + ' group' if c['elective_iv_lab'] else ''} · TA A{c['ta_lab']}")
        tid = f"{c['section']}:{c['actual']}:{c['elective_iii']}:{c['elective_iv']}{c['elective_iv_lab']}:TA{c['ta_lab']}"
        types.append(StudentType(tid, c["section"], name, lessons, c["count"],
                                 {"Actual group": c["actual"], "Elective-III": c["elective_iii"],
                                  "Elective-IV": c["elective_iv"] + (f" ({c['elective_iv_lab']} group)" if c["elective_iv_lab"] else ""),
                                  "Technical Aptitude lab": f"TA A{c['ta_lab']}"}))
        covered.add(c["section"])
        problems += [f"{tid}: class {u} not placed" for u in unknown]
    for c in data.get("D3", []):
        lessons, unknown = d3_lessons(college, c)
        name = (f"{c['section'].replace('-', ' ')} · {c['actual']} · {c['elective']} "
                f"(section {c['elective_section']}, lab {c['elective_lab']})")
        tid = f"{c['section']}:{c['actual']}:{c['elective']}:{c['elective_lab']}"
        types.append(StudentType(tid, c["section"], name, lessons, c["count"],
                                 {"Actual group": c["actual"], "Elective": c["elective"],
                                  "Elective section": c["elective_section"], "Elective lab group": c["elective_lab"]}))
        covered.add(c["section"])
        problems += [f"{tid}: class {u} not placed" for u in unknown]
    for s in college.sections:
        if s.id in covered:
            continue
        for g in s.groups:
            lessons = [l.id for l in college.lessons if g in l.batches]
            types.append(StudentType(g, s.id, f"{s.name} · {g.rsplit('-', 1)[-1]}", lessons, 0, {"Group": g.rsplit("-", 1)[-1]}))
    return types, problems


def load(path: Path = OUT) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


if __name__ == "__main__":
    data = combinations()
    OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")
    for year in ("D4", "D3"):
        n = sum(c["count"] for c in data[year])
        missing = [c for c in data[year] if None in c.values()]
        print(f"{year}: {n} students in {len(data[year])} combinations; rows with a missing value: {len(missing)}")
    print("->", OUT.relative_to(ROOT))

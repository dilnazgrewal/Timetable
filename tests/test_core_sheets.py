"""Onboarding another college from one Excel workbook: the blank template, the made-up sample college generated and
checked clash-free, and plain-language errors (with sheet and row) that stop a bad workbook from being imported."""
import importlib

import pytest

from app.importers import sheets
from app.solver import solve
from app.validator import split_issues, validate

sample = importlib.import_module("data.colleges.demo_institute.make_sample")


def workbook(tmp_path, **changes):
    """The sample college's sheets, with some rows replaced, written to a temp file."""
    data = {"Profile": sample.PROFILE, "Rooms": sample.ROOMS, "Teachers": sample.TEACHERS, "Classes": sample.CLASSES,
            "Lessons": sample.lessons()}
    data.update(changes)
    path = tmp_path / "college.xlsx"
    sheets.write_workbook(path, data)
    return sheets.read_workbook(path)


def test_the_blank_template_has_every_sheet_and_column(tmp_path):
    path = tmp_path / "template.xlsx"
    sheets.write_workbook(path, sheets.HELP)
    wb, errors = sheets.read_workbook(path)
    assert errors == [] and set(wb.rows) == set(sheets.SHEETS)
    college, _, problems = sheets.build_college(wb)
    assert problems == [] and len(college.lessons) == 2  # the example rows themselves are valid


def test_a_new_college_goes_in_through_the_template_and_gets_a_clash_free_timetable(tmp_path):
    wb, errors = workbook(tmp_path)
    college, profile, problems = sheets.build_college(wb)
    assert errors == problems == []
    assert len(college.sections) == 6 and len(college.teachers) == 11 and len(profile["period_times"]) == 8
    labs = [l for l in college.lessons if l.kind == "lab"]
    assert labs and all(l.duration == 2 and len(l.batches) == 1 for l in labs)  # one lab per lab group
    res = solve(college, time_limit=30)
    assert res.entries and split_issues(validate(college, res.entries))[0] == []  # the independent validator agrees
    arjun = college.teacher_by_id["AK"]  # "Fri 6-8" on the Teachers sheet
    assert (4, 5) in arjun.unavailable and not any(
        e.day == 4 and 5 <= q <= 7 for e in res.entries if college.lesson_by_id[e.lesson].teacher == "AK" for q in e.slots)
    out = tmp_path / "timetable.xlsx"
    sheets.write_timetable(out, college, res.entries, profile["period_times"])
    assert out.exists()


def test_mistakes_are_explained_by_sheet_and_row_and_nothing_is_imported(tmp_path):
    bad_lessons = sample.lessons() + [
        ["XX", "Unknown teacher", "ZZ", "CS-1A", "", "Theory", 3, ""],
        ["YY Lab", "Odd lab", "RS", "CS-1A", "G1", "Lab", 3, ""],
        ["ZZ Lab", "No such group", "RS", "CS-1A", "G9", "Lab", 2, ""],
    ]
    bad_classes = sample.CLASSES + [["CS-3A", "CS", 3, 60, "CS-Lab-1", "G1"]]  # a lab is not a home room
    bad_teachers = sample.TEACHERS + [["QQ", "Dr. Q", "CS", "Someday 9"]]
    wb, errors = workbook(tmp_path, Lessons=bad_lessons, Classes=bad_classes, Teachers=bad_teachers)
    college, _, problems = sheets.build_college(wb)
    assert college is None
    text = "\n".join(problems)
    assert "teacher 'ZZ' is not on the Teachers sheet" in text
    assert "labs come in 2-hour blocks" in text
    assert "has no lab group 'G9'" in text
    assert "home room 'CS-Lab-1' is not a classroom" in text
    assert "'Someday 9' should look like 'Fri 6-8'" in text
    assert all(" row " in p for p in problems)  # every problem points at its row


def test_a_missing_sheet_or_column_is_reported(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.title = "Rooms"
    wb.active.append(["Room", "Type"])
    path = tmp_path / "half.xlsx"
    wb.save(path)
    _, errors = sheets.read_workbook(path)
    assert any("no 'Teachers' sheet" in e for e in errors)
    assert any("Rooms: missing column(s) Seats" in e for e in errors)

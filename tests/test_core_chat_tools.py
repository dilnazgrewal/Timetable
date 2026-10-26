"""The assistant's read-only tools on the real college data (called directly: no Claude API call, no credit)."""
import json

from app.chat import Assistant

A = Assistant()


def run(name, **kw):
    out = json.loads(A._run_tool(name, kw))
    assert "error" not in out, out
    return out


def test_search_finds_people_sections_and_rooms_in_any_spelling():
    assert [t["id"] for t in run("search", query="Harpuneet")["teachers"]] == ["ME-HPS"]  # one person, one record
    assert any(s["id"] == "D2-IT-C" for s in run("search", query="D2IT")["sections"])
    assert [r["id"] for r in run("search", query="S-213")["rooms"]] == ["S213"]  # IT's spelling of CSE's S213


def test_schedules_for_students_sections_teachers_rooms():
    mine = run("get_schedule", kind="student", id="D4-CS-A:A2:CV:SCA1:TA3", day="Monday")["classes"]
    assert mine[0]["time"].startswith("08:30") and "Open elective" in mine[0]["subject"]
    first_year = run("get_schedule", kind="student", id="D1-CS-A-A1", day="Tue")["classes"]
    assert any("BEEE" in c["subject"] for c in first_year)  # taught by ECE, linked into CSE's first year
    assert run("get_schedule", kind="section", id="D2-IT-C", day="Mon")["classes"]
    assert run("get_schedule", kind="teacher", id="ME-HPS", day="Mon")["classes"]
    assert run("room_status", room="G17", day="Thu", time="10:45")["free"] is False


def test_free_rooms_and_teacher_slots():
    floors = run("free_rooms", day="Mon", time="12:30")["free_by_floor"]
    rooms = {r["room"] for rs in floors.values() for r in rs}
    assert rooms and not rooms & {"OTHER DEPARTMENT", "APPLIED SCIENCES"}  # stand-ins are never free rooms
    assert run("teacher_free_slots", teacher_id="IT-RDK", day="Wed")["free_periods"]


def test_bad_input_is_reported_not_crashing():
    assert "error" in json.loads(A._run_tool("get_schedule", {"kind": "section", "id": "D2-IT-C", "day": "Sunday"}))
    assert "error" in json.loads(A._run_tool("room_status", {"room": "NOPE"}))

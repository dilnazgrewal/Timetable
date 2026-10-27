"""Another college sets itself up on the website: template and sample download, the workbook checked row by row,
then a timetable the independent validator agrees with. No sign-in, nothing kept, GNDEC's data untouched."""
from fastapi.testclient import TestClient

from app.api import onboard
from app.main import app
from app.store import STORE

web = TestClient(app)  # nobody signed in


def test_the_template_and_sample_download_without_signing_in():
    for path in ("/api/onboard/template", "/api/onboard/sample"):
        r = web.get(path)
        assert r.status_code == 200 and r.content[:2] == b"PK"  # an .xlsx is a zip file


def test_a_bad_file_or_a_bad_row_is_explained():
    assert web.post("/api/onboard/check", content=b"").status_code == 400
    assert web.post("/api/onboard/check", content=b"not a workbook").status_code == 400
    template = web.get("/api/onboard/template").content
    assert web.post("/api/onboard/check", content=template).json()["ok"]  # the example rows are valid
    from openpyxl import load_workbook
    import io
    wb = load_workbook(io.BytesIO(template))
    wb["Lessons"].append(["XX", "Unknown", "ZZ", "CS-2A", "", "Theory", 3, ""])
    buf = io.BytesIO()
    wb.save(buf)
    b = web.post("/api/onboard/check", content=buf.getvalue()).json()
    assert not b["ok"] and any("Lessons row" in p and "'ZZ'" in p for p in b["problems"])


def test_the_sample_college_gets_a_clash_free_timetable_and_gndec_is_untouched(monkeypatch):
    monkeypatch.setattr(onboard, "HOSTED", True)  # the short time limit of the public server
    before = len(STORE.week())
    sample = web.get("/api/onboard/sample").content
    assert web.post("/api/onboard/check", content=sample).json()["summary"]["sections"] == 6
    b = web.post("/api/onboard/generate", content=sample).json()
    assert b["ok"] and b["clashes"] == [] and len(b["sections"]) == 6 and b["file"]
    assert len(b["sections"][0]["rows"]) == 8 and len(b["sections"][0]["rows"][0]) == 5
    assert len(STORE.week()) == before

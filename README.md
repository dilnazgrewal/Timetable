# TimeWeave: clash-free college timetables

TimeWeave generates the whole college's weekly timetable in seconds with Google OR-Tools **CP-SAT**. Every result is checked by an **independent validator** that shares no code with the solver. The solver also minimises the idle gaps students sit through between lectures.

Scope today:
- **Seed data:** 5 departments (CSE, IT, ECE, ME, CE) plus Applied Sciences, 20 sections, 39 teachers and 38 rooms.
- **Grids:** by section, teacher or room, mobile-first.
- **Metrics:** "0 clashes", idle periods, single-lecture days, teacher load, room use.
- **Free-room finder:** "which rooms are empty right now?"
- **Read-only AI assistant:** Claude with tools. It cannot change the timetable.

## Run it
```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
copy .env.example .env        # optional: add ANTHROPIC_API_KEY for the assistant
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```
Open http://localhost:8000. A generated timetable is cached in `data/solution.json`, so the app starts instantly.

Other commands:
```bash
.venv/Scripts/python -m app.solver 30     # solve from the CLI and print validator + metrics
.venv/Scripts/python -m pytest -q         # validator mutation tests + solver golden test
```

## How it works
- **Model:**
  - One boolean per (session, day, start period, room).
  - Hard rules:
    - No teacher, student-batch or room is double-booked.
    - Teacher availability is respected (a visiting teacher is in only on Tue/Thu).
    - Labs are 2-period blocks that never cross lunch, in a lab of the right type.
    - A theory subject runs at most once a day.
    - Daily caps apply.
  - Soft rules (minimised): student idle gaps, days with a single lecture, teacher gaps, and streaks of 4 or more periods.
- **Batches:** a batch (G1/G2) is the atomic student group.
  - A whole-section lecture occupies both batches.
  - A lab occupies one batch.
  - An elective can occupy batches from several sections.
- **Trust:** `app/validator.py` independently re-checks every timetable. `tests/` injects each kind of clash to prove the validator catches it.

## Demo script (3 min)
1. **The pain:** a hand-made timetable takes weeks, still clashes, and leaves students waiting 3 hours between lectures.
2. **Generate:** press **Regenerate whole college**. All 394 sessions are placed in about 20 s.
3. **Trust:** the green **✔ 0 clashes** badge comes from the independent validator. Idle periods per day drop from **1.47 → 0**, and single-lecture days drop from **5 → 0**, compared with an unoptimised solution.
4. **Section view, CSE 3rd yr A:** compact days, protected lunch, and labs as 2-hour G1/G2 blocks in the shared computer labs.
5. **Teacher view:** open *Er. Kavya Malhotra (Visiting)*, who teaches only Tue/Thu. Then open a CSE teacher who also teaches IT, which shows sharing across departments.
6. **Teacher load tab:** balanced loads, with classroom and lab utilisation.
7. **Phone width, Student role, Free rooms → "Right now":** empty rooms and how long they stay free.
8. **Ask TimeWeave:** "When is Harpreet Kaur free on Wednesday?" The answer comes from tools only, and the assistant can't modify anything.
9. **Roadmap** (`docs/PLAN.md`):
   - Excel import, plus a validator for existing hand-made timetables.
   - Manual editor with live clash detection.
   - Absences with ranked substitutes.
   - Minimal-change repair with a diff preview.
   - Google login with roles.

See `CLAUDE.md` for the architecture rules and `docs/PLAN.md` for the full design.

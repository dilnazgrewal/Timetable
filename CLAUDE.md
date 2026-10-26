# CLAUDE.md: TimeWeave (campus time and space platform)

Guidance for Claude Code (and humans) working in this repository.

## What this is
A web app for a whole college's time and space.
- It generates and validates **clash-free timetables** (CP-SAT, with an independent validator).
- It runs on **GNDEC Ludhiana's real CSE timetable**, imported from the FET pages the college publishes.
- Around the timetable, it solves everyday campus problems:
  - **free rooms** to sit in, by building and floor
  - finding a **teacher's free slots** and requesting a meeting
  - **booking seminar halls and rooms** for club events, approved by faculty advisor → HOD
  - an **event slot finder**, so visiting organisations get a time when a whole batch is free, plus a venue

It is built to be adaptable to any college: a college profile plus importers, with GNDEC as the demo data.

**Hackathon submission: Tuesday 27 Oct 2026.**
- End-to-end plan, versions and status: `PLAN.md`
- Detailed design: `docs/DESIGN.md`
- API contract: `docs/API.md`

## Stack
- **Backend:** Python 3.12+ / FastAPI, Google OR-Tools **CP-SAT** solver.
- **Frontend:** plain HTML pages with Tailwind (CDN) and Alpine.js (CDN), no build step, mobile-first.
  - `static/index.html`: timetable and dashboards
  - `static/venues.html`: venues and events
  - `static/login.html`: sign-in; `static/compare.html`: optimised CSE; `static/audit.html`: audit log
  - `static/js/shell.js`: shared top bar, `TW.api()` and `TW.can`
- **State:** `app/store.py` `STORE`, in memory.
  - `data/solution.json` holds the base timetable (committed).
  - `data/state.json` holds overrides, requests and notifications (runtime only, git-ignored).
- **Chatbot:** Anthropic SDK, model `claude-opus-5-5` at low effort, key in `.env` as `ANTHROPIC_API_KEY` (never committed). The user has limited credit, so test it sparingly.

## Commands
```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt   # setup (Windows)
.venv/Scripts/python -m app.solver          # solve seeded college from CLI, print status + validator result
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8001   # run app → http://localhost:8001
.venv/Scripts/python -m pytest -q           # tests
```

## Architecture rules (do not break these)
1. **The validator is independent of the solver.** `app/validator.py` must never import OR-Tools or solver code. Every generated, imported or edited timetable is checked by it, and "0 clashes" claims come from the validator only.
2. **One shared state.** Read and write only through `app.store.STORE`. What anyone sees for a real date comes from `STORE.effective(date)`, which is the base weekly timetable ⊕ that date's overrides (cancel, substitute, room_change, booking). Never keep your own copies of the timetable.
3. **Authorization lives in `app/auth.py`.** Routers call `require(user, action, resource)`, and every rule is a row in `PERMISSIONS` (deny by default). The UI hides things using `TW.can` from `/api/me` and never re-implements a rule; the server is the gate.
   - **Sign-in:** session cookie from `/login.html` (demo mode: pick any account, no password; Google sign-in later). No sign-in → 401. Tests send `X-User: <id>` (demo mode only).
   - **Roles:** student, teacher, coordinator (department timetable), HOD, Dean (read-only), club lead, org (visitor / T&P), admin (timetable office: generate, publish, central halls).
   - **Optimised timetable:** the department proposes, the timetable office publishes. Privileged actions go to the audit log (`/audit.html`).
4. **The chatbot never applies changes.** It has read tools and, later, *propose* tools. Applying happens through a UI Confirm button calling the API as the signed-in user.
5. **One write path for timetable edits** (editor, substitution, chatbot, import): propose → validate → preview → apply.

## Parallel lanes (several Claude sessions in the same folder: no branches, no merging)
Each lane **only edits the files it owns**. Shared files are owned by Lane A.

| Lane | Owns |
|---|---|
| **A. Core and data** | `app/models.py`, `app/rules.py`, `app/store.py`, `app/auth.py`, `app/substitutions.py`, `app/optimise.py`, `app/static/compare.html`, `app/static/login.html`, `app/static/audit.html`, `app/main.py`, `app/seed.py`, `app/solver.py`, `app/validator.py`, `app/chat.py`, `app/importers/*`, `data/gndec/*`, `app/api/core.py`, `app/static/js/shell.js`, `.claude/launch.json`, `docs/API.md` (Core and Shared sections), `PLAN.md`, `CLAUDE.md`, `README.md`, `tests/test_core_*`, `tests/test_validator.py` |
| **B. Dashboards UI** | `app/static/index.html`, `app/static/js/dashboards.js`, `app/static/css/*`, `app/api/dashboards.py`, `docs/API.md` (Lane B section), `tests/test_dashboards_*` |
| **C. Venues and events** | `app/static/venues.html`, `app/static/js/venues.js`, `app/venues/*`, `app/api/venues.py`, `docs/API.md` (Lane C section), `tests/test_venues_*` |

Rules for every lane:
- **Need a change in a file you don't own?** Append a request to `docs/REQUESTS.md` and work around it meanwhile. Never edit another lane's file.
- **Commits:** stage **only your own paths** (`git add <your files>`), never `git add -A`. Commit after each working step, and **never push** (the user pushes).
- **Your own dev server:** Lane A uses port 8001, Lane B port 8011 (`timeweave-dashboards`), Lane C port 8012 (`timeweave-venues`) in `.claude/launch.json`.
- **Keep it runnable:** `pytest -q` stays green, and the app imports cleanly. A broken import in your router breaks everyone's server.
- **Front end:** use `TW.api()` from `shell.js` for every request (session cookie, redirect to sign-in on 401), and `TW.can.<capability>` for what to show. Keep the `#tw-shell` div outside any Alpine `x-data` root.

## Domain glossary
- **Period model:** 8 periods a day, 60 minutes each, 8:30–4:30 (P1 8:30 … P8 3:30). GNDEC's real timetable has a 9th slot, 4:30–5:30, mostly used for mentoring. **Lunch is flexible:** every batch and teacher gets at least one free period in the lunch window P4–P6 (11:30–2:30). The solver picks which, and that free period is not counted as idle time.
- **Batch / group:** a group as the FET timetable names it (`D3 CS A1`). **Careful:** in GNDEC's 3rd and 4th year these numbers are reused slots, not sets of students. "D4 CS A2" = the 2nd option of Elective-III (DWDM) *and* of Elective-IV (Soft Computing) *and* TA lab batch 2, which are different people. In 1st and 2nd year, groups are real lab groups.
- **Student type:** a real combination of students: section + actual group + electives + elective lab groups + TA lab group, e.g. `D4-CS-A:A2:CV:SCA1:TA3`, with the exact lessons they attend and how many students have it.
  - Built from the department's distribution lists by `app/importers/gndec_students.py` (the lists live in git-ignored `data/private/`; only anonymous counts go to `data/gndec/students.json`).
  - Sections without lists get one type per group.
  - **No-overlap, the midday break, waiting gaps and "my timetable" are all per student type** (`College.units()`, `STORE.attends()`). Never decide a student's classes from a group id.
- **Lesson:** a teaching assignment (subject + teacher + audience groups + sessions per week + duration).
- **Session:** one weekly occurrence of a lesson; the solver places sessions.
- **Entry:** a placed session (day, start period, duration, room).
- **Occupancy:** what's happening in a room for a block of periods (a class or a booking). This is what `week()` and `effective()` return.
- **Override:** a change for one date (cancel, substitute, room_change, booking).
- **Room flags:**
  - `building` / `floor` are used by free rooms "near me".
  - `sittable` means students may sit there in a free period (labs: no).
  - `bookable` means it can be requested for events.
  - `features` list what a room has: projector, sound, ac, computers, stage.
- **Home room:** each section has a fixed classroom; only labs and halls get rooms assigned by the solver.
- Labs are 2-period contiguous blocks. A teacher's lab for two groups of one class (e.g. `SC Lab A1` / `SC Lab A2`, or D2 CS B's OOP Lab for B1 and B2) goes on **different days** (`College.lab_pairs()`; validator metric `lab_same_day`). The optimiser enforces this wherever the college's own timetable already does.
- **Classes outside CSE rooms:** open electives (D4 `OE-II`: ERP, EVS or E-Waste, Mon/Wed/Fri 8:30) are taught in another department, so only FET's *groups* page shows them. `app/importers/fet.py` reads the rooms page and then `add_groups_html()` adds these as fixed lessons in the room `APPLIED SCIENCES` (never a free room). The optimiser never moves them. "Self Study · Library" slots are free periods, not classes, and are not imported.

## College rules (each college's own timetable habits)
- Written per college in `data/<college>/rules.json`, read by `app/rules.py` (no solver code, so the validator and API use it too) into `College.rules`.
- Rule types:
  - `keep_as_published`: never moves (mentoring, M.Tech/PhD, classes run with other departments)
  - `labs_apart`: a teacher's lab for two groups of one class on different days
  - `nothing_after`: no class for the section after it that day (JPAL: only ~20 of 150 D4 students attend)
  - `real_class_daily`: every weekday has a real lecture or lab, not only OE / project / mentoring / JPAL
  - `allowed_times`: only in these periods
- `must` rules are never broken wherever the college's own timetable keeps them. `prefer` rules are penalised and never broken more often than the college does.
- `rules.report()` counts breaks (college vs optimised): shown on the compare page, saved in `cse_optimised.json`, and publishing is refused if any rule is broken more often than the college does.
- **To add a college habit:** add a rule to the JSON. A new rule type needs a check in `rules.breaks()` and a constraint in `optimise.py`.

## Solver model (summary)
- A boolean `x[s,d,p]` for each valid start; labs with several candidate rooms get `y[s,d,p,r]`.
- **Hard rules:**
  - each session is placed once
  - no teacher, group or room overlap
  - teacher availability is respected
  - at most 1 session of a theory lesson per day
  - lunch window and daily caps apply
  - same-lesson sessions are symmetry-broken by day
- **Soft goals (minimised):** student idle gaps (w10), single-lecture days (w6), teacher gaps (w2), more than 3 in a row (w5).
- Time limit about 30 s with 8 workers. Prechecks give human-readable infeasibility reasons before solving.

## Git workflow
- Remote: `https://github.com/dilnazgrewal/Timetable.git`, branch `main`.
- **Commit after every milestone** with a clear message. **Never push**; the user pushes.
- Never commit `.env`, `.venv/`, `__pycache__/` or `data/state.json`.

## Conventions
- **Python:** type hints, dataclasses for domain objects, small pure functions, no premature abstraction.
- **New permissions:** add new actions to `authorize()` (Lane A), via `docs/REQUESTS.md` if you're in another lane.
- **UI text:** plain and friendly for non-technical coordinators and students.
- **Tests:** each lane adds its own `tests/test_<lane>_*.py`. Tests must not write to `data/`; monkeypatch `app.store.STATE` to a temp path.

# CLAUDE.md — TimeWeave (college timetable platform)

Guidance for Claude Code (and humans) working in this repository.

## What this is
A web app that generates and manages clash-free college timetables (GNDEC-style B.Tech college:
CSE, IT, ECE, ME, CE; ~4 sections per department; classes 8:30–4:30; 5 working days).
Roles: **Admin/timetable office**, **Department coordinator**, **Teacher**, **Student**.

Hackathon context: a working prototype is demoed **today at 4 PM**. Prototype scope (P0):
seeded college data → CP-SAT generation → independent validator ("0 clashes") → grid views by
section / teacher / room → quality metrics → free-room finder. Read-only chatbot is a stretch goal.
Full plan (roadmap P1–P3, data model, permissions, chatbot design) lives in `docs/PLAN.md`.

## Stack
- **Backend:** Python 3.12+ / FastAPI, Google OR-Tools **CP-SAT** solver.
- **Frontend:** single page `app/static/index.html` — Tailwind (CDN) + Alpine.js (CDN), no build step, mobile-first.
- **Storage (P0):** in-memory Python objects + `data/solution.json` cache. P1 → SQLite/SQLModel, deploy → Postgres (Neon).
- **Chatbot (stretch):** Anthropic SDK, model `claude-sonnet-5-5`, key in `.env` as `ANTHROPIC_API_KEY` (never committed).

## Commands
```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt   # setup (Windows)
.venv/Scripts/python -m app.solver          # solve seeded college from CLI, print status + validator result
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000   # run app → http://localhost:8000
.venv/Scripts/python -m pytest -q           # tests
```

## Architecture rules (do not break these)
1. **The validator is independent of the solver.** `app/validator.py` must never import OR-Tools or solver
   code. Every generated or edited timetable is checked by it; "0 clashes" claims come from the validator only.
2. **One write path.** Every change to a timetable (manual editor, leave/substitution, chatbot, import) goes
   through the change engine (`app/services/change_engine.py`, P1+): propose → validate → diff preview → apply.
3. **The chatbot never applies changes.** It only has read tools and *propose* tools; applying happens via a UI
   Confirm button calling the API with the user's own session. Permissions come from the session, never the chat.
4. **Authorization lives in the service layer** (`authorize(user, action, resource)`), not the UI or prompt.
5. **Base + overrides.** What anyone sees for a date = published base weekly timetable ⊕ that date's overrides
   (cancel, substitute, swap, room_change, move, booking). Readers use `effective(date)` only.

## Domain glossary
- **Period model:** 8 periods/day, 60 min, 8:30–4:30 (P1 8:30 … P8 3:30). **Lunch is flexible:** every batch and teacher gets at least one free period in the lunch window P4–P6 (11:30–2:30); the solver picks which, and that one free period is not counted as idle time.
- **Batch:** the atomic student group (e.g. CSE-3A-G1). A whole-section class occupies all its batches; a lab occupies one batch;
  an elective occupies batches from several sections. No-overlap is enforced per batch.
- **Lesson:** a teaching assignment (subject + teacher(s) + audience batches + sessions/week + duration).
- **Session:** one weekly occurrence of a lesson; the solver places sessions.
- **Entry:** a placed session (day, start period, duration, room).
- **Home room:** each section has a fixed classroom; only labs (and shared halls) get rooms assigned by the solver.
- Labs are 2-period contiguous blocks.

## Solver model (summary)
- Bool `x[s,d,p]` per valid start; labs with several candidate rooms get `y[s,d,p,r]`.
- Hard: each session once; no teacher/batch/room overlap; teacher availability; ≤1 session of a theory lesson per day;
  daily caps; symmetry-break same-lesson sessions by day.
- Soft (minimise): student idle gaps (w10), single-lecture days (w6), teacher gaps (w2), >3 consecutive (w5).
- Time limit ~30 s, 8 workers. Prechecks give human-readable infeasibility reasons before solving.

## Git workflow
- Remote: `https://github.com/dilnazgrewal/Timetable.git`, branch `main`.
- **Stage and commit after every milestone** with a clear message. **Never push** — the user pushes.
- Never commit `.env`, `.venv/`, `__pycache__/`.

## Conventions
- Python: type hints, dataclasses for domain objects, small pure functions; no premature abstraction.
- Keep P0 simple: if a feature is not in today's scope, note it in `docs/PLAN.md` instead of building it.
- UI text is plain and friendly for non-technical coordinators and students.

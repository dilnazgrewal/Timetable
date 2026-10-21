# TimeWeave: College Timetable Platform (Plan)

## Context
Teachers at GNDEC-style colleges build semester timetables by hand. It takes weeks, the result still has clashes and uneven loads, and students sit through long idle gaps (one class at 12:30, the next at 3:30). The timetable is also fragile, so nobody dares fix it. Day-to-day changes like absences and free rooms have no tooling.

The goal is one app where the timetable office, department coordinators, teachers and students each do their part. Every change goes through a single validated change engine.

**Hard constraint today:** a hackathon demo at **4:00 PM**. The time is now about 2:25 PM, which leaves about 90 minutes of build time.

**Decisions taken (from your answers):**
- Must-have for the demo: auto-generation plus a clash-free grid.
- Stretch goals: a free room finder, then a read-only chatbot. You have a Claude API key.
- Frontend: FastAPI serving one HTML page (Tailwind and Alpine.js from a CDN).
- Data: realistic synthetic seed data shaped like GNDEC.

**Environment:** `D:\Desktop\Hack` is empty. Python 3.14.6, Node 24, npm 11.

> ⚠ **Risk 0:** the OR-Tools wheel may not exist for Python 3.14 yet. The first thing to do is `pip install ortools`. If it fails, use `uv venv --python 3.12` (uv downloads 3.12 in about 20 seconds). Don't lose 20 minutes to this.

---

## 0. TODAY: the 4 PM build (what I'll implement after approval)

**Scope:**
- A seeded college with 5 departments (CSE, IT, ECE, ME, CE), 4 sections each, about 45 teachers including a few shared across departments and a part-time teacher, home classrooms, about 8 labs of 3 types, and 2 shared seminar halls.
- CP-SAT generates the whole college timetable in at most 30 seconds.
- An **independent validator** proves there are 0 clashes.
- The UI shows the grid by section, teacher or room, plus quality metrics.
- Stretch 1: the free room finder.
- Stretch 2: a read-only chatbot.

**Week model:**
- 5 days, 7 teaching periods of 60 minutes: 8:30, 9:30, 10:30, 11:30, then lunch 12:30–1:30 (fixed, never schedulable), then 1:30, 2:30, 3:30.
- Labs are 2-period blocks that cannot span lunch. Valid starts are periods P1, P2, P3, P5 and P6.

**Git workflow (your requirement):**
- Run `git init` in `D:\Desktop\Hack`, then `git remote add origin https://github.com/dilnazgrewal/Timetable.git` and use the `main` branch.
- I **stage and commit** after every milestone row below, with a small, descriptive commit message.
- I **never push**. You push yourself.
- `.gitignore` covers `.venv/`, `__pycache__/`, `.env` (it holds `ANTHROPIC_API_KEY`) and `*.pyc`.

| Time | Step | Done when |
|---|---|---|
| **First** | Write **`CLAUDE.md`** in the working folder. It covers: the project purpose and the 4 PM scope; the stack and run commands; the architecture rules (every write goes through the change engine; the validator is independent of the solver; the chatbot never applies changes); the data-model glossary (batch = atomic student group, lesson, session, base vs overrides); the period model; the git rule (commit after each milestone, never push); and the coding conventions. Add `.gitignore` and `README.md` stub, then make the first commit | `git log` shows "Add CLAUDE.md and project scaffold" |
| 14:30–14:40 | Create the venv and install `fastapi uvicorn ortools anthropic`. Check that OR-Tools imports. | `python -c "from ortools.sat.python import cp_model"` runs without error |
| 14:40–15:05 | Write `seed.py` (the data model as dataclasses), `solver.py` (CP-SAT with hard constraints and the gap objective), and `validator.py` | `python -m app.solver` prints "FEASIBLE/OPTIMAL, 0 clashes, avg student gap X" |
| 15:05–15:30 | Write `main.py`, which serves the API and `static/index.html`: role and view switcher, department → section/teacher/room picker, colour-coded weekly grid, "Generate" button showing solve time and status | You can click through every section with no overlaps on screen |
| 15:30–15:40 | Add the metrics panel: "✔ Verified 0 clashes", average idle periods per section-day, teacher load bars, room utilisation % | Panel renders |
| 15:40–15:50 | Stretch: `/free-rooms?day&period`, with a phone-sized "Free rooms now" card | Returns correct rooms for a picked slot |
| 15:50–16:00 | **Freeze.** Rehearse the demo. Pre-generate and cache the solution so the demo never waits on the solver. | You can run the 3-minute script twice |

Chatbot: only if Stretch 1 is done by 15:45. It answers questions only, with 3 tools (`get_schedule`, `free_rooms`, `teacher_free_slots`). It does not make changes today.

**Demo script (3 minutes):**
1. Pain: a hand-made timetable takes weeks, has clashes, and leaves students with 3-hour gaps.
2. Click **Generate**: the whole college appears in about 20 seconds.
3. The "Verified: 0 clashes" badge appears, checked by a separate validator, not by the solver.
4. Open the CSE-3A grid: compact days, labs as 2-hour blocks, G1 and G2 in different labs at the same time.
5. Open the teacher view for a shared teacher teaching in CSE and IT, and the part-time teacher available only Tuesday and Thursday.
6. On a phone view, "Which rooms are free now?"
7. Roadmap slide: substitutions, minimal-change edits, chatbot with preview and confirm.

**Today's shortcuts (say so openly to the judges):**
- Data lives in memory plus a JSON file, not a database.
- No auth, just a role dropdown labelled "demo mode".
- No editing yet.

---

## 1. Clarifying questions: answered and still open
Answered: demo scope, LLM access, frontend, demo data (see above).

Still open for days 2–4. I'll use the default shown unless you say otherwise:
1. **Home rooms:** does each section have a fixed home classroom? *Default: yes.* This is the biggest simplification. Only labs and shared halls need room assignment.
2. **Working days:** 5 or 6, and is it the same for all departments? *Default: a per-term setting, 5 for the demo.*
3. **Periods:** are periods all 60 minutes, or mixed (for example 50 + 50 + 30)? *Default: a period template table, so mixed lengths are supported, uniform for the demo.*
4. **Who publishes:** does the central timetable office approve department timetables? *Default: the coordinator submits, the office publishes.*
5. **Notification channel:** what does your college actually read: WhatsApp, email, or an app? *Default: in-app plus email plus web push.*

---

## 2. Major decisions: options and recommendations

| Decision | Options | Recommendation |
|---|---|---|
| **Generation strategy** | (a) Pure CP-SAT, whole college. (b) Heuristic or genetic algorithm. (c) Solve per department, then merge. | **(a), with a home-room decomposition.** At about 20–100 sections the model is about 10⁴–10⁵ booleans, which CP-SAT handles in seconds to minutes. A genetic algorithm gives no feasibility proof and no explanation of infeasibility. A per-department merge breaks on shared teachers and labs. Use (c) only as *workflow*: departments edit their own part while other departments' entries stay locked. |
| **Solve time** | 10s / 60s / minutes | Initial generation: **60s in the background with progress**, returning the best solution so far. Repair: **≤5s**. Demo: 30s, pre-cached. |
| **Shared rooms across departments** | (a) Central pre-allocation of slots to departments. (b) Request and approval. (c) Joint solve. | **(c) for the initial generation**, run by the timetable office. After that, **(b)** for mid-semester requests, with the office approving and the change engine validating. (a) wastes capacity. |
| **Workflow** | (a) Git-like branches per department. (b) One shared draft with small atomic changesets. (c) Locking whole departments. | **(b)**, with optimistic concurrency on a version number. On a conflict, re-validate against the latest draft and re-preview. (a) is merge hell. (c) blocks people. |
| **Mid-semester changes** | Overrides for every week, or a new base version | **A new base version with `effective_from`.** Overrides are for one-off dates only. |
| **Data entry** | Manual forms / Excel import / copy last semester | **All three, in this order of value:** copy last term, then an Excel template (one sheet per entity, validated with a row-level error report), then forms for small edits. |
| **Real-time** | Polling / Server-Sent Events / WebSockets / Supabase Realtime | **SSE** from FastAPI. It is one-way, simple, and works on a free tier. Polling every 60s is the fallback. |
| **Frontend (days 2–4)** | Keep FastAPI + Alpine / Vite + React / Next.js | **Keep FastAPI + HTMX/Alpine.** Use SortableJS for drag and drop in the grid. A rewrite in 4 days is the biggest self-inflicted risk. Next.js adds SSR you don't need. |
| **Database** | SQLite / Postgres (Neon or Supabase free tier) | SQLite on day 2 (via SQLModel), then **Postgres on Neon** for deployment. Exclusion constraints there give a second clash guard. |
| **Auth** | Custom JWT / Supabase Auth / Google OAuth via Authlib | **Google OAuth (Authlib), restricted to the `gndec.ac.in` domain (`hd` claim)**, plus a server-side session cookie. Roles live in your own `user_role` table, not in the identity provider. |

**Where I'd push back on your assumptions:**
1. **The generator is not the first thing colleges will adopt.** Coordinators trust their own hand-built timetable. Your best wedge is: *"Import your existing timetable → we show the clashes, idle gaps and overloads in 10 seconds."* That gives value with zero trust required, and the same importer feeds the generator later.
2. **Don't solve rooms for everything.** Indian colleges give each section a home room. Solving rooms only for labs and halls makes the model about 10× smaller and makes the output match how people actually think.
3. **Minimal-change repair should be a local search, not a global re-solve with a penalty.** Unlock only the "blast radius" (entries that share a teacher, section or room with the change), solve, and widen the radius if it's infeasible. It's faster, and it's easier to explain ("3 classes move").
4. **For each absence there are 3 options, not just a substitute:** substitute, swap periods with another teacher of the same section, or cancel (which frees the room in the finder).
5. **The chatbot is a nice-to-have.** The change engine with diff preview is the real product. The chatbot is just another client of it.

---

## 3. Architecture and stack

```
Browser (phone-first PWA: Tailwind + Alpine/HTMX)
   │  REST + SSE
FastAPI (Python 3.12)
   ├─ api/         routers: auth, admin, dept, timetable, overrides, rooms, chat
   ├─ services/    change_engine ← the ONLY write path
   │               effective.py  (base ⊕ overrides for a date)
   │               substitutes.py, import_xlsx.py, notify.py
   ├─ solver/      model.py (CP-SAT), repair.py, prechecks.py, explain.py
   ├─ validator/   independent clash checker (pure Python, no OR-Tools)
   └─ chat/        Claude tool-use loop (claude-sonnet-5-5), tools = service calls
PostgreSQL (Neon free tier)        Background solves: asyncio task + status row
```

- **Why this shape:** a single Python language keeps OR-Tools, the API and the chatbot in one process, with no microservices. The validator is deliberately a separate implementation from the solver, so the "no clashes" proof is not the solver grading itself.
- **Hosting (free):**
  - App on Render or Fly.io, database on Neon, email via Resend or Gmail SMTP, push via Web Push (VAPID).
  - Free-tier CPUs are weak and Render's free tier sleeps. **Run solves locally or with a time limit, and never demo from a cold free-tier instance.**
  - For judges' phones: run locally plus a `cloudflared` tunnel and show a QR code.

---

## 4. Data model

**Institution and calendar**
- `department(id, code, name)`
- `room_type(id, name)`: classroom, CS lab, electronics lab, workshop, seminar hall
- `room(id, name, type_id, capacity, owner_dept_id NULL = central, active)`
- `term(id, name, start_date, end_date, working_days[])`
- `holiday(term_id, date, reason)`
- `period_template(term_id, day, idx, start, end, kind: teaching|fixed, label)`: lunch, library, sports, and mixed lengths live here

**Academic**
- `teacher(id, name, email, home_dept_id, type: regular|part_time|visiting, max_per_week, max_per_day, max_consecutive)`
- `teacher_dept(teacher_id, dept_id)`: for teachers shared across departments
- `teacher_availability(teacher_id, term_id, day, period_idx, status: unavailable|avoid|prefer)`
- `subject(id, dept_id, code, name, kind: theory|lab|tutorial, room_type_id, block_len)`
- `section(id, dept_id, year, name, size, home_room_id)`
- `batch(id, section_id, name: G1|G2|ALL, size)`: a **batch is the atomic student group.** An unsplit section has one `ALL` batch.
- `lesson(id, term_id, subject_id, sessions_per_week, duration, fixed_room_id NULL)`: one teaching assignment
- `lesson_teacher(lesson_id, teacher_id)`: allows team teaching
- `lesson_audience(lesson_id, batch_id)`: **one model handles every case:**
  - a section class: every batch of that section
  - a lab: one batch
  - an elective: batches from several sections

**Timetable (base layer)**
- `tt_version(id, term_id, status: draft|published|archived, effective_from, parent_id, version_no, created_by, solver_run_id)`
- `tt_entry(id, version_id, lesson_id, session_no, day, start_idx, duration, room_id, locked bool)`

**Date-specific layer**
- `leave(id, teacher_id, date, period_from, period_to, reason, status)`
- `override(id, date, kind: cancel|substitute|swap|room_change|move|booking, entry_id NULL, new_teacher_id, new_room_id, new_day/start, reason, status, changeset_id)`
- `room_booking`: this is `override` with `kind=booking` and `entry_id NULL`, so there's one table for the room finder to read.
- `sub_request(override_id, teacher_id, rank, score, reasons jsonb, status: offered|accepted|declined)`

**Change and audit**
- `changeset(id, version_id, base_version_no, author_id, source: editor|leave|chat|import|solver, ops jsonb, diff jsonb, score_delta, status: proposed|applied|rejected|conflicted)`
- `audit_log(id, at, actor_id, action, entity, before jsonb, after jsonb)`, append-only. Rollback means applying the inverse changeset, never deleting history.
- `app_user(id, email, role, dept_id NULL, teacher_id NULL, section_id NULL)`

**Effective schedule:** `effective(date)` works as follows.
1. Pick the published version with the largest `effective_from ≤ date`.
2. Take the entries for `weekday(date)`, dropping everything if the date is a holiday.
3. Apply that date's overrides in order: cancel removes, substitute replaces the teacher, room_change replaces the room, move relocates, booking adds a room occupancy.

The room finder, student "today" view, substitute ranking and chatbot all read **only** `effective()`.

---

## 5. Solver and minimal-change repair (implementable level)

**Instance:**
- For every lesson × session_no there is a *session* `s`, with a duration, teachers T(s), batches B(s), and candidate rooms R(s).
- R(s) is {home room} for theory, labs of the right type with enough capacity for labs, or the fixed room.
- Valid starts V(s) = (day, p) such that the block fits inside one contiguous teaching run (it does not cross lunch or fixed slots) and every teacher in T(s) is available for the whole block.

**Variables:**
- `x[s,d,p]`: a boolean for each valid start.
- Labs with more than one candidate room also get `y[s,d,p,r]`, with `sum_r y = x`.
- Helper: `cover(s,d,t) = Σ x[s,d,p]` for p ≤ t < p + dur.

**Hard constraints:**
1. `Σ x[s,·,·] == 1` for every s.
2. **Teacher:** for every teacher, day and t, `Σ cover ≤ 1` over the sessions that teacher teaches.
3. **Batch (atomic student group):** for every batch, day and t, `Σ cover ≤ 1`. A whole-section class covers G1 and G2, a G1 lab covers only G1, and an elective covers batches across sections.
4. **Room:** for every room, day and t, `Σ y-cover ≤ 1`. Home rooms are implied by rule 3, unless two sections share a home room.
5. At most one session of the same theory lesson per day (or at most 2 if sessions > days).
6. Batch: at most `max_per_day` periods per day (for example 6). Teacher: at most `max_per_day` per day and `max_per_week` per week.
7. Fixed or locked entries: pinned with `x == 1`.
8. **Symmetry break:** sessions of the same lesson are ordered by day (`day(s_k) < day(s_{k+1})`). This is a large speed-up.

**Soft constraints (weighted objective, minimised):**
- **Student idle gaps (weight 10).** This is your "don't make students wait" rule. For each batch and day, `occ[t]` is that batch's cover. Then:
  - `started[t] = max(occ[0..t])`
  - `pending[t] = max(occ[t..])`
  - `gap[t] ≥ started[t] + pending[t] − occ[t] − 1`
  - Minimise `Σ gap`.
- **Lonely days (weight 6):** penalise a batch day that has exactly 1 period. Coming in for one class is worse than a gap.
- **Teacher gaps (weight 2), more than 3 consecutive periods (weight 5),** and teacher `avoid`/`prefer` slots (weight 3 / −1).
- **Load balance (weight 1):** penalise `max − min` daily load per batch.

**Solver parameters:** `max_time_in_seconds=30–60`, `num_search_workers=8`, and a solution callback that streams progress to the UI.

**Infeasibility explanations, in two layers:**
1. **Prechecks before solving** (fast, readable):
   - Teacher hours vs available slots: "Prof. X is assigned 32 hours but available for 28".
   - Batch hours vs days × max_per_day.
   - Lab demand vs supply per room type: "CS labs: 46 two-hour blocks needed, 40 available".
   - Sessions per week vs days, under the once-per-day rule.
   - Teacher availability with no 2 consecutive free periods for a lab.
2. **CP-SAT assumptions.**
   - Wrap each constraint *group* in an enforcement literal: one per teacher's availability, per batch's daily cap, per once-per-day rule, and per room type.
   - Call `AddAssumptions` and, when the model is infeasible, `SufficientAssumptionsForInfeasibility()`.
   - Map the returned core to template sentences: "These can't all hold: Prof. X availability, CSE-3A max 6/day, Lab-2 capacity."
   - Offer one-click relaxations.

**Minimal-change repair** (an edit, a new teacher, or a room going out of service):
1. Apply the requested ops to a copy of the draft, which forces the changed entries.
2. **Blast radius:** unlock only the entries that share a teacher, batch or room with the changed entries on the affected days. Everything else is fixed, and user-`locked` entries are always fixed.
3. Objective = `1000 × Σ moved[e]` + soft score. `moved[e] = 1 − x[e, old_d, old_p]` (plus a room term). Use `AddHint` with the current positions.
4. If it's infeasible, widen the radius: same days → same department → whole week. If it's still infeasible, return the explanation.
5. Output a **diff**: a list of `{entry, from:(day,period,room,teacher), to:(...)}`, the affected people, the score delta, and validator = OK. Nothing is saved until the user confirms, and it is applied with `base_version_no` checked (optimistic concurrency).

**Manual editor clash detection:** dragging a cell calls `change_engine.propose()` using the validator only, with no solver, so the result comes back within 50 ms. A red cell shows the reason. Saying "make it fit" triggers the repair.

---

## 6. Roles and permissions

| Action | Admin / office | Dept coordinator | Teacher | Student |
|---|---|---|---|---|
| Rooms, room types, term, periods, holidays, departments | ✅ | ❌ (read) | ❌ | ❌ |
| Teachers, subjects, sections, lessons | ✅ all | ✅ own dept | ❌ | ❌ |
| Run generation | ✅ college-wide | ✅ own dept, others locked | ❌ | ❌ |
| Edit draft | ✅ | ✅ entries whose lesson belongs to own dept | ❌ | ❌ |
| Publish version / rollback | ✅ | Submit for approval | ❌ | ❌ |
| Request a shared room / one-off booking | ✅ approve | ✅ request | ✅ request (own classes) | ❌ |
| Mark leave | ✅ | ✅ for own dept teachers | ✅ self | ❌ |
| Confirm substitution / swap / cancel | ✅ | ✅ own dept | Accept or decline offers to self | ❌ |
| Set availability and preferences | ✅ | ✅ own dept | ✅ self | ❌ |
| View timetables | All | All (edit only own) | All | All (read-only) |
| Free room finder | ✅ | ✅ | ✅ | ✅ |
| Chatbot | Same rights as the user's role. It can only *propose*, and applying always takes a UI click | ← | ← | Read-only tools |
| Audit log | All | Own dept | Own entries | ❌ |

Enforcement happens in one `authorize(user, action, resource)` function inside the service layer, never in the UI and never in the prompt.

---

## 7. Chatbot design

- **Model:** `claude-sonnet-5-5`, which is fast and cheap for tool use. Load the `claude-api` skill when implementing.
- **Tools** (all run server-side as the calling user, through `authorize`):
  - **Read:**
    - `resolve(name, kind?)` → candidate IDs. It always runs first, which avoids made-up names.
    - `get_schedule(entity, date|weekday)`
    - `free_rooms(date, period|time_range, min_capacity?, room_type?)`
    - `teacher_free_slots(teacher, date|weekday)`
    - `who_is_in(room, datetime)`
    - `my_entries(date?)`
  - **Propose** (these return a changeset preview and never apply):
    - `propose_move(entry_id, target_day?, target_period?, target_room?)`
    - `suggest_slots(entry_id, n=3)`: the engine ranks feasible minimal-disruption targets
    - `propose_substitution(teacher, date, periods)`
    - `request_room(room, date, periods, purpose)`
  - There is **deliberately no `apply` tool.** The UI renders the preview card with a **Confirm** button, which calls `POST /changesets/{id}/apply` with the user's own session.
- **Vague requests**, for example "move my Monday class":
  1. `my_entries(Monday)`.
  2. If there is more than one entry, ask "Which one: CS301 at 9:30 (3A) or CS305 at 2:30 (3B)?"
  3. `suggest_slots`.
  4. Show 3 options, each with "N other changes".
  5. The user picks one, which leads to the preview card and then Confirm.
- **Anti-hallucination:**
  - The system prompt says to answer only from tool results, and to say "I don't know" or ask when unsure.
  - Factual answers render as **structured cards built from the tool output**, so the LLM's prose can't misstate a room or time.
  - Each tool returns `as_of` with the effective date.
- **Safety:** the role and department come from the session, never from chat text. Tool-call count and rate are capped. Every proposal is logged with `source=chat`. Text injected through names or notes is treated as data.

---

## 8. Roadmap

| Phase | Contents | Definition of done |
|---|---|---|
| **P0: today 4 PM** | Seed, CP-SAT generation, validator, grid views, metrics, free room finder (stretch) | Live generation of 20 sections with "0 clashes" verified independently, and the demo runs twice without failure |
| **P1: day 2: real data** | SQLite/SQLModel persistence, Excel template import with error report, **validate an existing timetable**, copy last term, draft/published versions, manual grid editor with live clash detection through `change_engine` | A coordinator imports the department's Excel file, sees the clashes, edits a cell, gets a red/green result in under 100 ms, and publishes. The audit log shows every change |
| **P2: day 3: daily operations** | `effective()` overrides, leave → ranked substitutes (swap/cancel alternatives) → confirm → SSE update, student "Today" PWA, free rooms with overrides and bookings, Google login + roles, email and in-app notifications | A teacher marks leave, the coordinator confirms the substitute, a student's phone shows the change within 5s, and the room finder reflects the cancellation the same day only |
| **P3: day 4: intelligence and polish** | Minimal-change repair with diff preview, infeasibility explanations, chatbot (read and propose), ICS export, printable section PDF, room QR door page, deploy (Render + Neon) | "Prof. X unavailable Fridays" gets repaired with ≤ N moves and a diff shown. The chatbot answers 10 scripted questions correctly and can't apply without a click. The app is deployed |

**Substitute ranking (P2):**
- **Hard filters:** free in that slot per `effective()`, not on leave, under the daily maximum, and not exceeding the consecutive-period limit.
- **Score:**
  - +40 teaches the same subject
  - +20 same department
  - +15 already teaches that section
  - +5 adjacent to one of their own periods (no extra trip)
  - −8 for each substitution this month (fairness)
  - −4 for each period already taught today
- Show the reasons alongside the score.
- Offer to the top 3 in sequence, or let the coordinator pick directly.

**Extra features, ranked by value ÷ effort:**
1. Validate an imported existing timetable (very high value, low effort; it is the adoption wedge).
2. Student "Now / Next" card plus free rooms on mobile (high, low).
3. ICS calendar subscribe link per section or teacher (high, low).
4. Printable PDF per section, teacher and room (high, low).
5. Room QR door page "now / next / free until" (high, low; it reuses `effective()`).
6. Teacher load dashboard (medium-high, low).
7. Room utilisation heatmap, which justifies room allocation politically (medium, low).
8. Copy last term with a diff of what changed (high, medium).
9. Substitution fairness report (medium, low).
10. "What-if" sandbox draft for a new section or teacher (medium, medium).
11. Exam-week mode (medium, high; later).
12. WhatsApp notifications (high in India, but costly or awkward; use a Telegram bot as the free alternative).

---

## 9. Risks, open questions, testing

**Risks:**
- **Adoption.** Coordinators distrust black-box output. *Mitigations:* the validate-existing wedge; locks; minimal-change edits; "why is this here?" explanations; people stay in control of publishing.
- **Data entry.** This is the real bottleneck. *Mitigations:* an Excel template, copy last term, and row-level errors.
- **Bad data → infeasible models →** "the tool doesn't work". *Mitigation:* prechecks run before every solve.
- **Politics over shared rooms.** *Mitigations:* a transparent request log and the utilisation heatmap.
- **Technical:**
  - OR-Tools on Python 3.14 (use 3.12).
  - Free-tier cold starts and weak CPUs.
  - Solve time growing with the whole college plus electives (use time limits, symmetry breaking, home rooms).
  - LLM cost or latency (Sonnet, cached system prompt, capped tool calls).
- **Today:** scope creep. If it isn't in Section 0, it doesn't get built before 4 PM.

**Testing: proving the solver never produces a clash:**
1. **Independent validator** (no OR-Tools imports). It checks teacher, batch and room double-booking, room type and capacity, availability, lab contiguity, lunch and fixed slots, and daily caps. It runs after *every* solve and every changeset apply, and in CI. An apply that fails the validator is rejected, even if the solver produced it.
2. **Property-based tests (Hypothesis):** generate random instances. The invariant is that the solver either returns INFEASIBLE with a non-empty explanation, or returns a solution the validator accepts with zero errors.
3. **Validator mutation tests:** take a valid timetable, inject each kind of clash, and assert that the validator catches it. This tests the tester.
4. **Change-engine fuzzing:** random sequences of moves, leave and bookings. After each step, `effective(date)` validates clean, and the moved count is ≤ the radius size.
5. **Database guard (P1+):** Postgres `EXCLUDE` constraints on (teacher, day, period range), so a bug in the app layer can't persist a clash.
6. **Golden instances:** the seeded college plus 2 hand-built tricky cases (an elective across 3 sections, a part-time teacher with 2 available days), with solve time asserted under 60s.

---

## 10. Folder structure

```
D:\Desktop\Hack\
├─ README.md                  # run instructions + demo script
├─ requirements.txt           # fastapi uvicorn ortools anthropic (later: sqlmodel authlib openpyxl hypothesis)
├─ app/
│  ├─ main.py                 # FastAPI app, mounts static, routers
│  ├─ models.py               # dataclasses today → SQLModel tables on day 2
│  ├─ seed.py                 # synthetic GNDEC-like college
│  ├─ solver/
│  │  ├─ model.py             # CP-SAT build + solve (generation & repair)
│  │  ├─ prechecks.py         # human-readable infeasibility checks
│  │  └─ explain.py           # assumption cores → sentences   (P3)
│  ├─ validator.py            # independent clash checker
│  ├─ services/
│  │  ├─ change_engine.py     # propose / apply / diff           (P1)
│  │  ├─ effective.py         # base ⊕ overrides                 (P2)
│  │  ├─ substitutes.py       # ranking                          (P2)
│  │  └─ importer.py          # Excel/CSV templates              (P1)
│  ├─ api/                    # routers per area                 (P1+)
│  ├─ chat/                   # tools.py, agent.py               (P3, read-only stretch today)
│  └─ static/
│     └─ index.html           # Tailwind + Alpine single page (grid, metrics, free rooms)
├─ data/solution.json         # cached generated timetable for the demo
└─ tests/
   ├─ test_validator.py       # mutation tests
   ├─ test_solver_props.py    # Hypothesis
   └─ test_golden.py
```

---

## Verification (today)
1. `python -m app.solver`: prints status, solve time, "validator: 0 clashes", and the average student gap.
2. `uvicorn app.main:app --reload`, then open `http://localhost:8000`:
   - Generate.
   - Click through 3 sections, 2 teachers (one shared, one part-time) and 1 lab room. No overlapping cells.
   - Labs appear as 2-period blocks, and nothing is in the lunch row.
3. Free rooms: pick Tuesday P3, then cross-check one listed room in its room view, which should be empty.
4. Use a phone-width viewport (375px) to check the student view and room finder.
5. Restart the server: the cached `data/solution.json` loads instantly, which is the safety net for the demo.

# TimeWeave: end-to-end plan

> This is the master plan for what we're building and why, what's done, what's left, and what ships on submission day.
> Deeper design notes (option comparisons, data model, solver internals, chatbot safety) are in [`docs/DESIGN.md`](docs/DESIGN.md).
> Working rules for code are in [`CLAUDE.md`](CLAUDE.md).

**Status legend:** ✅ done · 🟡 partly done · ⬜ not started

**Timeline:** 4-day hackathon.

| Day | Date | Milestone |
|---|---|---|
| Day 1 | Wed 21 Oct 2026 | Prototype demo at 4 PM |
| Day 2 | Thu 22 Oct | Real data in, editable |
| Day 3 | Fri 23 Oct | Daily operations |
| Day 4 | Sat 24 Oct | Submission (adjust if the official date differs) |

---

## 1. The problem
- **Hand-built timetables are slow and flawed.** Teachers build the semester timetable by hand. It takes weeks and still ends up with clashes, uneven teaching loads and empty rooms.
- **Students lose time.** They sit through long idle gaps, for example a class at 12:30 and the next at 3:30.
- **Changes are scary.** Moving one lecture sets off a chain of other changes, so nobody fixes problems.
- **Day-to-day changes have no tooling.** Nothing helps with an absent teacher (substitutes), and students can't find an empty room in a free period.

## 2. The solution in one line
One web app where the timetable office, department coordinators, teachers and students each do their part. A **constraint solver** generates a clash-free, student-friendly timetable. An **independent validator** proves it is clash-free, and every later change goes through the same checks.

---

## 3. Architecture

### 3.1 Pipeline (how a timetable is made)
```
 INPUT                Seed data (v0.1) → Excel/CSV upload (v0.2)
   │
 PRE-CHECKS           Plain-English errors before solving:
   │                  "Prof. X has 32 h assigned but is available only 28 h"
   │
 CP-SAT SOLVER        HARD rules (never broken):
 (Google OR-Tools)      no teacher / student-batch / room double-booking
   │                    teacher availability (part-time, visiting)
   │                    labs = 2-hour blocks in the right lab type with enough seats
   │                    flexible lunch: a free hour somewhere 11:30–14:30 for everyone
   │                    daily caps; a theory subject at most once a day
   │                  SOFT goals (minimised):
   │                    gaps between lectures · single-lecture days ·
   │                    teacher gaps · 4+ periods in a row
   │
 INDEPENDENT          Separate code re-checks every result → "✔ 0 clashes"
 VALIDATOR            (tests inject clashes to prove it catches them)
   │
 SAVED TIMETABLE      base weekly timetable (+ date-specific overrides from v0.3)
   │
 OUTPUTS              Grids by section / teacher / room · Free-room finder ·
                      Teacher load · Chatbot (read-only) · PDF · Excel · Calendar
```

### 3.2 System (how the app is built)
```
 Browser (phone-first page: Tailwind + Alpine.js, no build step)
     │  REST (+ live updates via Server-Sent Events from v0.3)
 FastAPI (Python)
     ├─ solver.py        CP-SAT model: generate, and repair with minimal changes (v1.0)
     ├─ validator.py     independent clash checker + quality metrics
     ├─ change engine    ONE write path for editor / leave / chatbot: propose → validate → diff → apply (v0.2)
     ├─ effective(date)  base timetable ⊕ that day's overrides (v0.3)
     ├─ importer         Excel/CSV templates with row-level errors (v0.2)
     └─ chat.py          Claude with read-only tools (+ propose-only tools in v1.0)
 Storage: in-memory + JSON cache (v0.1) → SQLite (v0.2) → Postgres on Neon (deploy, v1.0)
```

### 3.3 Rules that never change
1. The validator never shares code with the solver, so the solver never grades itself.
2. Every change goes through the change engine, whether it comes from the editor, a leave request or the chatbot.
3. The chatbot can only read or **propose**. A human always clicks Confirm.
4. Permissions are enforced on the server, never only in the UI or in the prompt.
5. What anyone sees for a date = the base timetable ⊕ that date's overrides.

---

## 4. The finished product on submission day (v1.0)

### By role
| Role | What they can do in v1.0 |
|---|---|
| **Timetable office (admin)** | Manage rooms, periods, working days and the lunch window. Upload the Excel template. Generate the whole college. See the 0-clash proof. Publish versions and roll back. View teacher-load and room-usage dashboards. |
| **Dept coordinator (HOD)** | Edit their department's timetable in a grid with live clash warnings. "Make it fit" repair with a preview of exactly what changes. Confirm substitutes when a teacher is absent. |
| **Teacher** | My schedule. Mark leave. Accept or decline substitution requests. Set availability. Add to Google Calendar. |
| **Student** | Today's timetable on the phone, including substitutions and cancellations. Free-room finder ("right now"). Ask the chatbot. |

### Headline features (for judges)
1. Whole-college generation in under a minute, **proven clash-free** by an independent validator.
2. **Student-friendly days:** minimised idle gaps and flexible lunch, with before/after numbers.
3. **Safe edits:** minimal-change repair with a diff preview before saving.
4. **Absences:** ranked substitute suggestions, confirmed by the coordinator, visible for that day only.
5. **Free-room finder:** accounts for cancellations and one-off bookings.
6. **AI assistant:** answers from live data and can propose changes that go through the same validation.
7. **Exports:** one-page PDF, Excel and a calendar feed.

---

## 5. Versions and status

### v0.1 Prototype: Day 1 (Wed 21 Oct), demo at 4 PM ✅
| Feature | Status |
|---|---|
| `CLAUDE.md`, plan and repo scaffold, git history | ✅ |
| Seeded GNDEC-style college: CSE / IT / ECE / ME / CE + Applied Sciences, 20 sections, 39 teachers, 38 rooms, 394 weekly sessions | ✅ |
| Realism: G1/G2 lab batches, shared central computer labs, teachers shared across departments, a visiting teacher available only Tue/Thu, Friday-afternoon unavailability | ✅ |
| CP-SAT solver with hard rules and soft goals (Section 3.1) | ✅ |
| Flexible lunch: a free hour anywhere in 11:30–14:30, chosen per section and teacher | ✅ |
| Plain-English pre-checks for impossible inputs | ✅ |
| Independent validator: "✔ 0 clashes" badge, re-run on every load | ✅ |
| Quality metrics vs an unoptimised baseline (idle periods 1.2 → 0.07 per day; single-lecture days 5 → 3) | ✅ |
| Grid views by section, teacher or room; phone layout with day tabs | ✅ |
| Free-room finder with a "Right now" button and "free until" times | ✅ |
| Teacher-load bars, classroom and lab utilisation % | ✅ |
| Read-only AI assistant (Claude + 4 tools: search, schedule, free rooms, teacher free slots) | ✅ |
| Print / Save as PDF: one-page A4 landscape per section, teacher or room | ✅ |
| Role switcher (demo mode, no real login) | 🟡 UI only |
| 12 automated tests (validator mutation tests, solver golden test, lunch rule) | ✅ |

### v0.2 Real data and editing: Day 2 (Thu 22 Oct) ⬜
| Feature | Status |
|---|---|
| **Excel template** (one workbook: Settings, Rooms, Teachers, Sections, Assignments) + CSV, with row-level error report | ⬜ |
| Upload an **existing hand-made timetable → show its clashes, gaps and overloads** (the adoption hook) | ⬜ |
| Copy last semester's setup | ⬜ |
| Settings screen: working days (5/6), period timings, lunch window | ⬜ |
| SQLite persistence (SQLModel) instead of a JSON file | ⬜ |
| **Change engine**: propose → validate → diff → apply, with optimistic locking for two coordinators editing at once | ⬜ |
| Manual grid editor: drag a class, see instant red/green clash feedback, lock entries | ⬜ |
| Draft vs published versions, rollback, audit log of who changed what | ⬜ |
| Excel export (same format as the import) | ⬜ |

**Done when:** a coordinator uploads the Excel file, sees errors per row, generates, drags a class into a clash and is warned, fixes it, and publishes. The audit log shows the change.

### v0.3 Daily operations: Day 3 (Fri 23 Oct) ⬜
| Feature | Status |
|---|---|
| Date-specific overrides layer: cancel, substitute, swap, room change, one-off booking | ⬜ |
| Teacher marks leave → **ranked substitutes** → coordinator confirms → affected people notified | ⬜ |
| Swap and cancel as alternatives to a substitute | ⬜ |
| Student "Today" view with substitutions and cancellations; live updates (SSE) | ⬜ |
| Free-room finder that respects cancellations and bookings | ⬜ |
| Google sign-in restricted to the college domain; roles scoped by department | ⬜ |
| In-app notifications (+ email if time allows) | ⬜ |
| Calendar feed (.ics) per section and teacher | ⬜ |

Substitute ranking:
- **Must:** be free in that slot, not on leave, and under their daily limit.
- **Score:**
  - +40 teaches the same subject
  - +20 same department
  - +15 already teaches that section
  - +5 has a class next to the slot (no extra trip)
  - −8 for each substitution this month (fairness)
  - −4 for each class already taught that day
- The reasons are shown with every suggestion.

**Done when:** a teacher marks leave, the coordinator confirms a substitute, the student's phone shows the change for that day only, and the freed room appears in the finder.

### v1.0 Submission: Day 4 (Sat 24 Oct) ⬜
| Feature | Status |
|---|---|
| **Minimal-change repair:** "Prof. X can't do Fridays" → re-solve moving as few classes as possible, show the diff, confirm | ⬜ |
| Chatbot can **propose** changes ("move my Monday class") → preview card → human Confirm | ⬜ |
| Infeasibility explanations: "These can't all hold together: …" with suggested relaxations | ⬜ |
| Room door QR page: "now / next / free until" | ⬜ |
| Deploy: Render (app) + Neon (database), free tiers; a QR code to the live link for judges | ⬜ |
| Polish: loading states, empty states, phone testing, demo data reset | ⬜ |
| Final demo script, slides and README screenshots | ⬜ |

**Done when:** every headline feature in Section 4 can be demoed live from the deployed link on a phone, and all tests pass.

### Later (after the hackathon)
- Electives that combine several sections; shared seminar-hall requests between departments.
- WhatsApp or Telegram notifications; push notifications (PWA).
- Exam timetables; a what-if sandbox; analytics on substitution fairness.

### If we fall behind, cut in this order (last item = keep at all costs)
Room QR page → calendar feed → email → chatbot propose → swap/cancel options → Google login (keep demo roles) → manual editor drag-and-drop (keep a click-to-move form) → **never cut:** Excel import, substitutions, minimal-change repair, the validator.

---

## 6. Input format (from v0.2)
One **Excel workbook** (`timetable_template.xlsx`), with each sheet also accepted as CSV:

| Sheet | One row per | Columns |
|---|---|---|
| Settings | – | working days, period start/end times, lunch window, max periods per day |
| Rooms | room | room id, type (Classroom / Computer Lab / …), capacity, owning dept or "central" |
| Teachers | teacher | name, email, dept, regular/part-time/visiting, max per day, unavailable slots (`Mon; Fri P6-P8`) |
| Sections | section | dept, year, section name, students, home room, split into G1/G2 (yes/no) |
| Assignments | teacher + subject + section | subject code, subject name, theory/lab, hours per week, batch (All/G1/G2), room type |

- **Why Excel:** departments already keep workload sheets in Excel, so there's nothing new to learn.
- **Validation:** every upload is checked and errors point to the exact row ("Assignments row 14: teacher 'Dr. Mehta' is not in the Teachers sheet").
- **Internally:** everything becomes JSON / database rows. Free text and PDFs are never accepted as input.

## 7. Output formats
| Output | For | Status |
|---|---|---|
| Live web link + QR code (always current, shows substitutions) | everyone | ✅ link · ⬜ QR |
| PDF, one A4 page per section, teacher or room | notice boards, HOD sign-off | ✅ |
| Excel export (same format as the import) | timetable office records | ⬜ v0.2 |
| Calendar feed (.ics) | students' and teachers' phones | ⬜ v0.3 |

---

## 8. Proving it never clashes (testing)
1. **Independent validator** after every solve, load and edit. A change that fails it is rejected.
2. **Mutation tests:** inject each kind of clash (student, teacher, room, wrong room type, unavailable teacher, missing lunch, missing session, past end of day) and check that the validator catches it. ✅
3. **Golden test:** the seeded college solves and validates clean. ✅
4. **Property tests** (v0.2): random small colleges must be either solved clean or rejected with a reason.
5. **Edit fuzzing** (v0.2): random edit sequences never leave a clash.
6. **Database guard** (v1.0, Postgres): exclusion constraints so even a bug can't save a double booking.

## 9. Risks
| Risk | Mitigation |
|---|---|
| Coordinators don't trust an auto-generated timetable | Start with "check my existing timetable"; locks; minimal-change edits; people publish, not the machine |
| Data entry is the real bottleneck | Excel template, copy last semester, row-level errors |
| Bad data makes the problem unsolvable ("the tool doesn't work") | Pre-checks + plain-English explanations |
| Solve time grows with the full college | Home rooms (only labs get rooms assigned), time limits, best-so-far result |
| Free-tier servers are slow or sleep | Demo locally with a pre-generated timetable; warm the deployed app before judging |
| LLM cost and limited API credit | Low effort, short history, read-only tools, chatbot is optional for the demo |

## 10. Repository layout
```
CLAUDE.md            rules for working on the code
PLAN.md              this file
README.md            how to run + demo script
docs/DESIGN.md       detailed design: options compared, data model, solver, chatbot, permissions
app/
  models.py          domain model (periods, lunch window, rooms, teachers, sections, lessons)
  seed.py            demo college data
  solver.py          CP-SAT generator + pre-checks
  validator.py       independent clash checker + metrics
  chat.py            read-only Claude assistant
  main.py            FastAPI API + serves the UI
  static/index.html  the whole UI (grid, free rooms, load, chat, print)
data/solution.json   cached timetable so the demo starts instantly
tests/               validator mutation tests + solver golden test
```
Planned additions: `app/importer.py`, `app/services/change_engine.py`, `app/services/effective.py`, `app/services/substitutes.py`, `app/auth.py`, `templates/timetable_template.xlsx`.

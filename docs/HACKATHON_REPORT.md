# TimeWeave: complete project documentation (hackathon report source)

> **What this file is:** the complete, checked record of what TimeWeave is, what was built, how it works, the real GNDEC data it uses, the numbers, and every automated test with the edge case it covers. Use it as the source for the submission report (submission: **Tuesday 27 Oct 2026**).
>
> **How it was checked:** every claim comes from the repository (code, docs, git history), the test suite, or a command run on **Mon 26 Oct 2026**. Nothing is from memory. The commands are listed under [Sources](#18-sources). Anything that could not be confirmed yet is listed under [Pending](#19-pending).
>
> **State of the repo when this was written:**
> - Final numbers are from commit `32f1b45` (26 Oct 2026; 51 commits up to and including it). That commit adds **College rules** (each college's own timetable habits, written down, obeyed by the optimiser and checked independently) and re-optimises CSE.
> - Before it: `becb48e` added the lab-pair rule, and `3acc154` imported D4's open elective from the FET *groups* page.
> - **All 95 tests pass** on `32f1b45`.

---

## Contents
1. [The project in one page](#1-the-project-in-one-page)
2. [The problem](#2-the-problem)
3. [Architecture](#3-architecture)
4. [Real GNDEC data](#4-real-gndec-data)
5. [Feature list (everything built)](#5-feature-list-everything-built)
6. [How the main parts work](#6-how-the-main-parts-work)
7. [Roles, sign-in and permissions](#7-roles-sign-in-and-permissions)
8. [Pages and screens](#8-pages-and-screens)
9. [API summary](#9-api-summary)
10. [Results and numbers](#10-results-and-numbers)
11. [Testing: every test and the edge case it covers](#11-testing-every-test-and-the-edge-case-it-covers)
12. [Timeline: how it was built](#12-timeline-how-it-was-built)
13. [How the team worked (3 parallel lanes)](#13-how-the-team-worked-3-parallel-lanes)
14. [How to run it](#14-how-to-run-it)
15. [Demo script](#15-demo-script)
16. [Known limitations and future work](#16-known-limitations-and-future-work)
17. [Key numbers for slides](#17-key-numbers-for-slides)
18. [Sources](#18-sources)
19. [Pending](#19-pending)

---

## 1. The project in one page

**TimeWeave** is a web app for a whole college's **time and space**. It runs on **GNDEC Ludhiana's real CSE timetable**, imported from the FET pages the department publishes, and it is built to work for any college through a college profile plus importers.

What it does:

| Area | What it does |
|---|---|
| **Clash-free timetables** | Generates timetables with Google OR-Tools **CP-SAT**. Every timetable (generated, imported, optimised or edited) is checked by an **independent validator** that shares no code with the solver. |
| **Optimised real timetable** | Re-optimises GNDEC's own CSE timetable. It keeps the same lessons, teachers, groups and rooms, changes only the times, and is never worse than the college's version on any measure. The department proposes it and the timetable office publishes it. |
| **College rules** | Each college writes down its own timetable habits (e.g. "a teacher's lab for two groups goes on two days", "nothing after JPAL", "a real class every working day") in a JSON file. The optimiser obeys them, an independent checker counts every break, and publishing is refused if a rule is broken more often than in the college's own timetable. |
| **Real students** | Models students as real **combinations of choices** ("student types", built from the department's elective distribution lists), so no real student ever gets two classes at once. |
| **Everyday campus problems** | Free rooms to sit in (by building and floor), find a teacher's free slots and request a meeting, Now/Next card, leave with ranked substitutes, venue booking with approvals, an event slot finder for a whole batch. |
| **Roles** | 8 roles with sign-in, a server-side permission table (deny by default) and an audit log. |
| **AI assistant** | A read-only Claude assistant answering timetable questions from live data through 5 tools. It can never change anything. |

**Stack:**
- **Backend:** Python 3.12+, FastAPI, OR-Tools CP-SAT.
- **Frontend:** plain HTML with Tailwind and Alpine.js from a CDN. No build step; mobile-first.
- **State:** in memory, persisted to JSON files.
- **Chatbot:** Anthropic SDK, model `claude-opus-5-5` at low effort.

**Tests:** **95 automated tests, all 95 pass** (commit `32f1b45`; see [11](#11-testing-every-test-and-the-edge-case-it-covers)).

---

## 2. The problem
(From `PLAN.md` §1 and `CLAUDE.md`.)

- **Hand-made timetables are slow and flawed.** They take weeks, still end up with clashes and uneven teaching loads, and leave rooms empty.
- **Students lose time.** They sit through long idle gaps between classes, and some days have no midday break.
- **Changes are scary.** Moving one lecture sets off a chain of other changes, so nobody fixes problems.
- **Day-to-day changes have no tooling:**
  - substitutes for absent teachers
  - an empty room to sit in during a free period
  - finding when a teacher is free
  - booking a seminar hall
  - finding a time when a whole batch is free for a visiting company

---

## 3. Architecture

### 3.1 System
```
Browser (phone-first pages: Tailwind + Alpine.js, no build step)
   │   shared top bar shell.js: TW.api() (session cookie, 401 → sign-in), TW.can (capabilities)
   │   REST/JSON
FastAPI app (app/main.py, signed session cookie "tw_session")
   ├─ /api/auth/*        sign-in (demo accounts), logout                 Lane A
   ├─ /api/*             core: meta, timetable, effective(date), free rooms, generate,
   │                     leave + substitutions, compare/propose/publish, students, chat, audit   Lane A
   ├─ /api/dash/*        dashboards: views, teacher free slots, meetings, now/next              Lane B
   └─ /api/venues/*      venue ranking, booking requests + approvals, event slot finder        Lane C
        │
   app/auth.py      PERMISSIONS table (deny by default) + capabilities + audit
   app/store.py     STORE: the one shared state; effective(date) = base ⊕ that date's overrides
   app/solver.py    CP-SAT generator (seeded departments) + plain-English prechecks
   app/validator.py independent checker (no OR-Tools import) + quality metrics
   app/optimise.py  re-optimises the REAL CSE timetable (never worse, large-neighbourhood search)
   app/rules.py     college rules (data/gndec/rules.json): who stays put, labs apart, nothing after JPAL,
                    a real class daily; counts every break (no solver code), also turned into optimiser constraints
   app/importers/   fet.py (FET HTML → model), gndec_students.py (distribution lists → student types)
   app/substitutions.py  leave → ranked substitutes
   app/venues/      ranking.py, requests.py (approval chain), slots.py (slot finder), common.py
   app/chat.py      read-only Claude assistant (5 tools)
Storage: data/solution.json (base timetable), data/gndec/*.json (imported data, optimised timetable),
         data/state.json (overrides, requests, notifications, audit; runtime only, git-ignored)
```

### 3.2 How a timetable is made and trusted
```
GNDEC FET pages ──► FET importer ──► real CSE lessons + placements (fixed)
Distribution lists ─► student types (real combinations of electives and lab groups)
Seed data ──────────► other departments (IT, ECE, ME, CE, Applied Sciences)
                         │
              prechecks (plain-English "impossible" reasons)
                         │
              CP-SAT solver places the seeded departments around the fixed CSE classes
                         │
              INDEPENDENT VALIDATOR ──► "0 clashes" + quality notes + metrics
              COLLEGE RULES CHECK (app/rules.py) ──► how often each of the college's own rules is broken
                         │
              base weekly timetable ⊕ date overrides (cancel / substitute / room change / booking / leave)
                         │
              every screen, free rooms, venues, slot finder and chatbot read STORE.effective(date)
```

### 3.3 The five architecture rules
(From `CLAUDE.md`. All of them are enforced in code, and several by tests.)
1. **The validator is independent of the solver.** `app/validator.py` never imports OR-Tools or solver code. "0 clashes" claims come only from it.
2. **One shared state.** Everything reads and writes through `app.store.STORE`. What anyone sees for a real date comes from `STORE.effective(date)` = base weekly timetable ⊕ that date's overrides.
3. **Authorization lives in `app/auth.py`.** Routers call `require(user, action, resource)`; every rule is a row in `PERMISSIONS`, and anything not listed is denied. The UI only hides things using `TW.can`; the server is the gate.
4. **The chatbot never applies changes.** It has read tools only.
5. **One write path for timetable edits:** propose → validate → preview → apply. This is the design rule. Today the propose → publish flow for the optimised timetable follows it; the general editor is not built yet (see [16](#16-known-limitations-and-future-work)).

### 3.4 Domain model (`app/models.py`)
**The day:**
- **Periods:** 9 slots of 60 minutes, P1 8:30 … P8 3:30–4:30, plus P9 4:30–5:30 (GNDEC uses it mostly for mentoring).
- The generator only uses P1–P8 (`SOLVER_PERIODS = 8`).
- **Lunch is flexible:** every batch and teacher must get at least one free period in the lunch window P4–P6 (11:30–2:30), and the solver picks which one. That free period is not counted as idle time.
- At most 6 periods a day per student group (`MAX_BATCH_PER_DAY`) in generated departments.

**Main types:**
- **Room:** `building`, `floor`, `features`, plus two flags:
  - `sittable`: students may sit there in a free period (labs: no)
  - `bookable`: can be requested for events
- **Teacher:** with `unavailable` slots and `max_per_day`.
- **Section** and its **groups**.
- **Lesson:** a teaching assignment (subject + teacher + co-teachers + groups + sessions per week + duration + room kind). `fixed=True` means it was imported, and the generator never moves it.
- **Entry:** a placed session.
- **StudentType:** a real combination of choices and the exact lessons it attends.
- **Override:** a one-date change: cancel, substitute, room change, booking or leave.
- **Requests and people:** `User`, `Club`, `BookingRequest` + `ApprovalStep`, `MeetingRequest`, `Notification`.
- **Occupancy:** what happens in a room for a block of periods on one day. This is what `week()` and `effective()` return.
- **College.rules:** the college's own timetable rules, loaded from `data/gndec/rules.json` by `app/rules.py` (see [6.3b](#63b-college-rules-apprulespy-datagndecrulesjson)).

---

## 4. Real GNDEC data

### 4.1 Source
- **Timetable:** GNDEC CSE timetable for **Jul–Dec 2026, w.e.f. 19/08/2026**, published by the department at cse.gndec.ac.in and generated there with **FET** (free desktop timetabling software).
- **Raw copies** (committed in `data/gndec/raw/`):
  - `rooms.html`: one table per room
  - `groups.html`: one table per group
  - `teachers.html`
- **Importer:** `app/importers/fet.py` turns them into `data/gndec/cse.json`.
- **Elective distribution lists:** for 3rd year (2024–2028 batch) and 4th year (2023–2027 batch). They contain student names and roll numbers, so they stay in the git-ignored `data/private/`. Only **anonymous combinations with counts** are written to `data/gndec/students.json`, and a test checks that no 7-digit roll numbers leak into it.

### 4.2 What was imported (`data/gndec/cse.json`, measured 26 Oct)
| Item | Count |
|---|---|
| Rooms | 41 (includes one placeholder, "APPLIED SCIENCES", for the open elective taught in another department) |
| Teachers | 62 (incl. Applied Sciences and other-department teachers who teach CSE classes) |
| Sections | 26: D1–D3 CS A–F, D4 CS A–E, M1-CS, M3-CS, PHD-CS |
| Lessons | 318 in the file (320 after Elective-IV labs are split per lab group) |
| Placed weekly sessions | 537 |
| Lab sessions | 146 (all 2-period blocks) |
| Lessons with 2–3 teachers (co-taught) | 47 (labs mostly) |

- **Real rooms** (from `PLAN.md` and the importer):
  - Ground floor: G6, G7, G10–G18
  - First floor: F105, F107
  - Second floor: S202–S205, S213–S219
  - 13 labs (SL-I … SL-IV, PL, OS, R, DBMS, HW, MBA COMP, CG, …)
  - The WS Seminar Hall
- **Capacities:** classrooms seat 75 with a projector. Lab seat counts come from GNDEC CSE "Laboratories 2025" (e.g. SL-I 35, OS LAB 25).
- **Unused classrooms:** S215, S216, S217 and S219 are on the department's "Class Rooms 2025" list but never used by the timetable, which backs the free-room feature.

**Importer details worth reporting:**
- **Cell parsing:** each FET cell has groups, teacher(s) and an activity. Labs span two rows. "---" means free and "-x-" means unavailable.
- **Teacher tags:** tags such as "(App. Sci.)" or "(JDS-CE)" map to departments.
- **Subject names:** subject codes map to full names (e.g. `ERP` = Entrepreneurship Practices; `CV E(T)` = Computer Vision (elective)).
- **Lesson groups:** sessions with the same subject, teacher, groups and length are grouped into one lesson.
- **The groups page** (commit `3acc154`): the importer also reads FET's groups page (`add_groups_html()`, which also parses the small tables nested inside its cells). It adds two kinds of class the rooms page cannot show; both are fixed, and the optimiser never moves them:
  - D4's **open elective OE-II** (ERP, EVS or E-Waste) for D4 CS A–E, Mon, Wed and Fri at 8:30. It is taught in another department; its room is a placeholder, "APPLIED SCIENCES", which never shows as a free room.
  - A **class in two rooms at once:** D1 CS C mentoring, Thu 10:30, in S202 + S203 together (stored in S202).
  - "Self Study · Library" slots (D4, Mon/Tue 1:30) are deliberately skipped: they are free periods, not classes.
- **A real bug a student caught:** ERP was missing from their timetable. The importer only read the rooms page, so classes held outside CSE rooms were silently dropped. Reading the groups page fixed it, and a test now guards it.

### 4.3 The FET quirk, and how it was fixed with "student types"
- **The quirk:** in GNDEC's 3rd and 4th year, FET's numbered sub-groups (A1…A6) are **re-used slots, not sets of students**. "D4 CS A2" is at the same time:
  - the 2nd option of Elective-III (DWDM)
  - the 2nd option of Elective-IV (Soft Computing)
  - Technical-Aptitude lab batch 2

  These are different people.
- **The bug:** filtering a student's timetable by group number showed the wrong classes. This was caught as real user feedback (`docs/REQUESTS.md`, 26 Oct).
- **The fix** (`app/importers/gndec_students.py`, commit `39df85d`): a real student is *section + actual group + the options they chose*. The importer reads the distribution lists and builds one **student type** per combination that really exists, with the exact set of classes those students attend, e.g. `D4-CS-A:A2:CV:SCA1:TA3`.
- **Who uses student types:** the validator, the optimiser, metrics, "My timetable", Now/Next and the chatbot. So "no clash" is guaranteed for every real combination, not for FET's group numbers.

| Year | Students | Real combinations (student types) |
|---|---|---|
| D4 (4th year, 5 sections) | **150** | **48** |
| D3 (3rd year, 6 sections) | **340** | **57** |

(Both checked against `data/gndec/students.json`, and also by a test.)
- **Other sections:** D1, D2, M.Tech, PhD and the seeded departments get one student type per group, because there the groups really are lab groups. Total in the combined college: **164 student types**.
- **Elective-IV labs per lab group** (commit `81eba30`): Soft Computing and ACC labs run twice a week, but FET lists both sessions under one activity. A student confirmed which is which: the A1 groups go on **Thursday** and the A2 groups on **Friday**. The importer splits them into "SC Lab A1" / "SC Lab A2", so each student sees only their own lab.

### 4.4 The rest of the college (seeded)
- The other departments are a **GNDEC-shaped seed** (`app/seed.py`):
  - IT, ECE, ME and CE, each with 2nd- and 3rd-year sections A/B (16 sections)
  - Applied Sciences teaching Maths to every 2nd-year section
  - shared central computer labs (CL-1…5)
  - teachers shared across departments
  - a **visiting teacher available only Tue/Thu**
  - buildings and floors (MBA Block, ECE, Mechanical, Civil, Main and Workshop blocks)
  - lecture theatres LT-1/LT-2 (120 seats), the MBA Seminar Hall (120, owned by CSE) and the Auditorium (600, central)
- Seeded: 138 lessons, **316 weekly sessions**, generated by CP-SAT.
- **Combined college** (working tree, 26 Oct):

| Item | Count |
|---|---|
| Departments | 6 |
| Buildings | 6 |
| Rooms | 76 (45 sittable; 62 bookable) |
| Teachers | 94 |
| Sections | 42 |
| Groups | 120 |
| Lessons | 458 |
| Weekly sessions | **853** (537 real CSE + 316 generated) |

---

## 5. Feature list (everything built)
Status as of commit `32f1b45`. ✅ built and committed · ⬜ designed, not built.

### 5.1 Core and data (Lane A)
| # | Feature | Status |
|---|---|---|
| A1 | Seeded GNDEC-style college with buildings, floors, room features, sittable/bookable flags | ✅ |
| A2 | CP-SAT generator with hard rules and soft goals; plain-English prechecks for impossible inputs | ✅ |
| A3 | Flexible lunch: a free hour anywhere in 11:30–14:30 per batch and teacher | ✅ |
| A4 | Independent validator: hard clashes vs quality notes, and quality metrics | ✅ |
| A5 | FET importer for GNDEC's real CSE timetable (rooms page), re-checked by the validator | ✅ |
| A5b | FET groups page: open elective OE-II and a two-room class | ✅ |
| A6 | Student types from the elective distribution lists (privacy-safe) | ✅ |
| A7 | Elective-IV labs split per lab group (A1 Thursday, A2 Friday) | ✅ |
| A8 | Shared store: `effective(date)` = base ⊕ that date's overrides (cancel / substitute / room change / booking / leave) | ✅ |
| A9 | Free-room finder: by day or real date, building, floor, sittable-only, capacity; "free until"; booking-aware | ✅ |
| A10 | Leave and ranked substitutes, with notifications to the substitute, the absent teacher and the students | ✅ |
| A11 | Optimiser for the real CSE timetable: same lessons, never worse, large-neighbourhood search | ✅ |
| A11b | Rule: a teacher's lab for two groups of one class stays on two different days (e.g. SC Lab A1 / A2); `lab_same_day` metric; card on the compare page | ✅ |
| A11c | **College rules:** 6 GNDEC rules in `data/gndec/rules.json` (5 rule types, must/prefer); the optimiser obeys them; an independent checker counts breaks; "GNDEC's timetable rules" section on the compare page; publishing refused if a rule is broken more often than in the college's timetable | ✅ |
| A12 | Propose (department) → publish / unpublish (timetable office), re-validated on publish | ✅ |
| A13 | Sign-in (session cookie, demo accounts), 8 roles, PERMISSIONS table, capabilities, audit log | ✅ |
| A14 | In-app notifications (🔔 in the shared top bar) | ✅ |
| A15 | Read-only Claude assistant with 5 date-aware tools | ✅ |
| A16 | Pages: sign-in, compare (college vs optimised), audit log; shared top bar | ✅ |
| A17 | Demo reset (admin) | ✅ |

### 5.2 Dashboards (Lane B, `index.html`, `/api/dash`)
| # | Feature | Status |
|---|---|---|
| B1 | Role-aware home: students see their student type, teachers their week, HOD/coordinator/Dean/admin a department | ✅ |
| B2 | Timetable views by department → year → section → student (group + electives), teacher, room; weekly, one date, or a dated week | ✅ |
| B3 | Find a teacher: day view with each period's state (teaching / free / unavailable / leave / meeting) | ✅ |
| B4 | Meeting requests: students ask for a free period, the teacher accepts or declines, both are notified | ✅ |
| B5 | Now / Next / next-free card | ✅ |
| B6 | Free rooms by building and floor, "near me", "Right now" | ✅ |
| B7 | Mark leave (teacher for themself; HOD/coordinator/admin for their department) | ✅ |
| B8 | Substitutions board: next 6 school days, state chips, ranked candidates with reasons, Assign, Cancel class | ✅ |
| B9 | Substituted classes marked in timetables and Now/Next (names both teachers) | ✅ |
| B10 | Panel comparing the real and generated timetables; teacher-load bars; classroom and lab use | ✅ |
| B11 | Print / Save as PDF: one A4 landscape page per section, teacher or room | ✅ |
| B12 | Ask tab (chat UI) | ✅ |
| B13 | Phone layout with day tabs | ✅ |

### 5.3 Venues and events (Lane C, `venues.html`, `/api/venues`)
| # | Feature | Status |
|---|---|---|
| C1 | Venue ranking: free bookable rooms ranked by fit, with plain-English reasons and "near misses" | ✅ |
| C2 | Booking requests with an approval chain: club → faculty advisor → room's HOD (central halls → admin); pre-approved steps for approvers | ✅ |
| C3 | Approvals inbox, rejection with a reason, cancel, a timeline per request, warnings about competing requests | ✅ |
| C4 | An approved booking becomes a booking override, so the room leaves Free rooms for those periods; cancelling gives it back | ✅ |
| C5 | Event slot finder: common free time for a batch (dept+year, sections or groups) on real dates, with best-fit venues, lunch protection and "nearly free" times naming who would miss which class | ✅ |
| C6 | "Book this" from the slot finder with an audience: the batch's students are notified on approval and on cancellation | ✅ |
| C7 | Clubs may use the slot finder | ✅ |

---

## 6. How the main parts work

### 6.1 CP-SAT generator (`app/solver.py`)
**Variables:** one boolean `x[session, day, start, room]` for every valid start of every session that can move. Imported (fixed) CSE lessons stay where they are.

**Hard rules:**
- each session is placed exactly once
- no teacher, student group or room is double-booked
- teacher unavailability is respected (e.g. the visiting teacher only Tue/Thu)
- labs are contiguous 2-period blocks in a room of the right kind
- a theory lesson at most once a day (twice only if it has more sessions than available days); identical sessions are symmetry-broken by day order
- teacher daily cap (`max_per_day`) and student daily cap (6)
- **flexible lunch:** at most 2 of the 3 lunch-window periods may be busy, for every batch and teacher, every day

**Soft goals (minimised, weights):**

| Goal | Weight |
|---|---|
| Student idle gaps | 10 |
| Single-lecture days | 6 |
| 4+ periods in a row for a teacher | 5 |
| Teacher gaps | 2 |

One free period in the lunch window is the lunch break, not idle time.

**Run settings:** 8 workers, random seed 7, time limit 30 s by default. The "baseline" is the first feasible solution, used for the before/after numbers.

**Prechecks** run before solving and give plain-English reasons, for example:
- "X is assigned 32 hours but can teach at most 28 with their availability"
- a batch needs more periods than the weekly limit
- not enough lab blocks of a kind

### 6.2 Independent validator (`app/validator.py`)
- **No shared code:** it does not import OR-Tools or the solver.
- **When it runs:** on every install of a timetable (`STORE.publish`), on import, on publish of the optimised timetable, and in tests.

**Hard errors (clashes):**
- unknown lesson or room
- invalid day
- wrong duration
- a block that runs past the end of the day
- wrong room kind
- room too small
- teacher unavailable
- wrong number of sessions
- teacher / student / room double-booking

**Quality notes** (rules a good timetable follows but a hand-made one may break; kept separate from clashes):
- `NO LUNCH …` (busy all of 11:30–2:30)
- `LONG DAY …` (over a teacher's daily limit, or over 6 periods for students)

**Students are checked per student type,** so two electives the same real student takes can never overlap.

**Metrics:**

| Group | Metrics |
|---|---|
| Students | idle periods (total, per day, worst gap), single-lecture days, days with no lunch, days over 6 periods |
| Teachers | streak days (4+ in a row), no-lunch days, idle periods, load |
| Rooms and late classes | late sessions (P9), classroom and lab utilisation |
| Lab pairs | `lab_same_day`: how often a teacher's lab for two groups of one class falls on the same day |

### 6.3 Optimising the real CSE timetable (`app/optimise.py`, page `/compare.html`)
**Kept exactly as the college decided:**
- every lesson's teacher(s), including co-teachers
- groups, including cross-section electives and A1/A2 lab groups
- weekly hours and durations (2-hour labs)
- the kind of room

**What changes:** only *when* each session happens, and which room of the right kind it uses. Rooms come only from those the college already uses for these classes, so the comparison is fair.

**Pinned (never moved):** since `32f1b45` this comes from the college's `keep_as_published` rules (see 6.3b), not hard-coded checks:
- mentoring (MC)
- M.Tech and PhD classes
- classes run with other departments (teacher `TBA-…`: open electives, JPAL)
- classes in rooms that aren't CSE's own

Pinned sessions occupy teachers, groups and rooms as constants.

**Lab pairs on different days** (commit `becb48e`; a student reported it):
- **The problem:** in an earlier optimised run, Soft Computing lab A1 and A2 were both on Friday with the same teacher.
- **Lab pairs:** `College.lab_pairs()` in `app/models.py` finds pairs of labs one teacher gives to two groups of the same class, e.g. "SC Lab A1" / "SC Lab A2", or D2 CS B's OOP Lab for B1 and for B2. There are 86 pairs in the college, 54 of them in CSE.
- **The rule:** wherever the college already keeps a pair on different days, the optimiser forbids putting both on one day (a hard constraint). Since `32f1b45` this is the college rule `labs-on-different-days`.
- **Existing same-day pairs:** the college itself has 12 same-day pairs (mostly 2nd year, e.g. D2 CS B's OOP lab with both groups on Friday). Those may stay, so the college's own timetable is still a valid starting point.
- **Result** (final run, `32f1b45`):
  - SC Lab A1 Fri 2:30 and A2 Thu 10:30 (teacher DN): two different days
  - ACC Lab A1 Mon 12:30 and A2 Tue 12:30
  - same-day pairs 12 → 9

**Never worse:** the college's own numbers are hard ceilings for:
- days with no free midday hour (students and teachers)
- student waiting periods
- teacher days with 4+ in a row
- classes in the 4:30–5:30 slot
- days over 6 periods
- single-lecture days
- the same lab for two groups on one day (`lab_same_day`), via the rule above
- every college rule (6.3b): never broken more often than in the college's timetable

Within the ceilings it minimises (weighted):

| Goal | Weight |
|---|---|
| No-lunch days (students) | 100 |
| Each break of a "prefer" college rule | 30 |
| No-lunch days (teachers) | 20 |
| Waiting gaps | 10 |
| Use of spare rooms | 8 |
| Single-lecture days | 6 |
| Streaks | 5 |
| Late classes | 4 |
| Periods beyond 6 | 3 |
| Teacher gaps | 2 |

**Search:** large-neighbourhood search that starts from the college's own timetable (which meets every rule and ceiling). Each step frees one slice and re-solves it exactly, keeping the result if it is better. The slice is one of:
- one year group
- a handful of teachers
- everything on two days

Theory rooms are then assigned per day with a small exact model that prefers the room the class had before.

**Output:** `data/gndec/cse_optimised.json` with before/after metrics, clash counts and college-rule break counts. It is re-validated by tests. A department can re-run it from the page (`POST /api/compare/cse/run`, background thread, 60–1800 s).

**New pins:** `add_new_pins()` puts newly imported pinned classes (e.g. OE-II) into the saved optimised timetable and re-measures it, without re-solving. The final result (§10.3) comes from a full 15-minute re-run with these classes pinned.

### 6.3b College rules (`app/rules.py`, `data/gndec/rules.json`)
**Why** (from the project owner): every college has timetable habits an algorithm can't know, for example:
- teachers don't take a lab for two groups on one day
- nothing after JPAL
- "students must have real classes every working day"

So TimeWeave lets each college **write its rules down**. The optimiser obeys them and an independent checker counts every break.

**How it works:**
- **One file per college:** `data/<college>/rules.json`. `app/rules.py` loads it into `College.rules`.
- **No solver code in `app/rules.py`:** it only reads timetables, so its break counts are independent of the optimiser. `app/optimise.py` turns the same rules into CP-SAT constraints.
- **What a rule has:**
  - an id, a type, plain-English `text` and `why`
  - a strength
  - a `match` that selects lessons by department, subject code prefix, year or teacher prefix
- **Strength:**
  - **must:** never broken wherever the college's own timetable keeps it
  - **prefer:** penalised (weight 30 per break), and never broken more often than the college does

**The 5 rule types:**

| Type | Means |
|---|---|
| `keep_as_published` | these lessons never move |
| `labs_apart` | a teacher's lab for two groups of one class is on two different days |
| `nothing_after` | no class for the whole section after this one on its day |
| `real_class_daily` | every weekday has at least `min` real classes, not counting e.g. open elective or project |
| `allowed_times` | these lessons only start in given periods (type available; GNDEC doesn't use it) |

**The 6 GNDEC rules:**

| Rule | Strength | Means | Breaks: college → optimised |
|---|---|---|---|
| `keep-mentoring` | must | Mentoring stays exactly where the college has it | 0 → 0 |
| `keep-postgraduate` | must | M.Tech and PhD classes stay put | 0 → 0 |
| `keep-other-departments` | must | Classes run with other departments (open electives, JPAL) stay where they are | 0 → 0 |
| `labs-on-different-days` | must | A teacher's lab for two groups of one class is on two different days | 12 → **9** |
| `nothing-after-jpal` | prefer | No class for the whole section after JPAL that day. Only about 20 of 150 D4 students take JPAL, so a class after it makes everyone else wait. | 1 → 1 (the college's own D4 CS C mentoring, Wed 3:30, which is pinned) |
| `real-class-every-day` | must | Every weekday has at least one real lecture or lab for D2–D4, not just the open elective, major project, mentoring or JPAL | 0 → **0** |

**Notes on the rules:**
- **real-class-every-day** was the project owner's own example. The previous optimised timetable (`becb48e`) broke it **6 times**: D4 student types whose Friday had only the major project and the open elective (verified here with `rules.breaks()`). The new run breaks it 0 times.
- **D1 is excluded** from real-class-every-day, because 1st-year subjects are taught by Applied Sciences and are not in CSE's timetable.
- **Only confirmed rules are added.** A guessed rule ("project only in the morning") was dropped, because the college itself has a project hour at Mon 3:30.

**Where the rules are used:**
- `rules.report()` gives each rule with its break counts for the college and the optimised timetable, plus up to 5 examples. It is shown on the compare page ("GNDEC's timetable rules") and saved in `cse_optimised.json`.
- **Publishing is refused (409)** if any rule is broken more often than in the college's own timetable.
- **To add a habit:** add a JSON rule. A new rule *type* needs a check in `rules.breaks()` and a constraint in `optimise.py`.

### 6.4 Shared store and date overrides (`app/store.py`)
- `STORE.week()` is the base weekly timetable.
- `STORE.effective(date)` is what actually happens on a real date:
  - **weekend:** nothing
  - **cancel:** removes the class
  - **substitute:** changes the teacher (status `substituted`)
  - **room_change:** changes the room (status `room_changed`)
  - **booking:** adds an event occupancy
  - **leave:** marks a teacher absent (read by substitutions, free slots and Now/Next)
- Other dates and the base weekly timetable are never touched.
- `STORE.attends(student_type, occupancy)` decides whether a student sits in a class. For bookings, it checks whether their section is in the audience.
- Imported placements always come from the import (or from the published optimised file), never from a stale saved file.
- Everything is protected by a re-entrant lock and saved to `data/state.json`.

### 6.5 Substitutions (`app/substitutions.py`)
**Marking leave:** a teacher (or their HOD/coordinator/admin) marks leave for a date, the whole day or some periods. Every class that teacher has that day is listed with a state:
- `open`
- `covered` (a co-teacher is present, so no substitute is needed)
- `substituted`
- `cancelled`

**Candidates must:**
- be free for the whole class on that date (co-taught labs count as busy)
- be on campus that weekday
- not be on leave
- stay within their daily limit after taking the class

**Score:**

| Rule | Points |
|---|---|
| Teaches the same subject | +40 |
| Same department | +20 |
| Already teaches these students | +15 |
| Has a class right next to it (no extra trip) | +5 |
| Each substitution already done this month (fairness) | −8 |
| Each period already taught that day | −4 |

Every candidate comes with plain-English reasons.

**Deciding:**
- Assigning re-checks that the substitute is free (409 if not) and replaces any earlier decision for that class.
- The substitute, the absent teacher and the students are notified.
- Only that date changes.

### 6.6 Venue ranking, approvals and slot finder (`app/venues/`)
**Common rules:**
- dates are Mon–Fri and not in the past
- periods must be back to back
- `needs` must be known features (projector, ac, sound, computers, smart_board, stage)
- "free" always means free in `STORE.effective(date)`

**Ranking** (`ranking.py`):
- **Fits:** free, big enough, has every need.
- **Order:** no competing request first, then the smallest room that fits, then more features, then building/floor.
- **Reason line**, e.g. "Seats 120 for 100 people · has projector and sound · …".
- **Near misses:** up to 6, each saying why it doesn't fit (busy with which class or booking, too small, missing feature).

**Approval chain** (`requests.py`), built when the request is made:
- **Club lead:** faculty advisor (endorse) → room's HOD (approve). Central halls (`dept=None`) go to the admin instead of a HOD.
- **Teacher, coordinator, HOD, org, admin:** skip the advisor.
- **Requester who is an approver:** that step is pre-approved.
- **Statuses:** pending → endorsed → approved, or rejected / cancelled.
- **Checks:** rejection needs a note. The room is re-checked before the final approval (409 "no longer free"). A new request for an already-booked slot is refused up front.
- **On approval:** a `booking` override is added.
- **Notifications** go to:
  - the next approver
  - the requester
  - the final approver, on cancel
  - the event's audience (students of those groups)

**Slot finder** (`slots.py`):
- **Audience:** dept + year, sections, or groups. A class blocks a group if the group or its section is in the class's batches.
- **Inputs:** `duration` 1–9 periods. Dates default to today + 13 days (at most 31 days). Weekends and periods already started today are skipped.
- **Output:** up to 40 slots where *every* group is free, each with up to 3 fitting venues.
- **Order:** by date; slots with a venue first; slots that don't eat a lunch break first; earliest first.
- **Warnings:** "Uses the only lunch break left for …" (only when it takes a group's last free lunch-window period) and "No free venue fits".
- **Nearly free:** when there are fewer than 10 exact slots, up to 6 "almost" times are listed, saying which section and groups would miss which class.

### 6.7 Read-only AI assistant (`app/chat.py`)
**Model:** `claude-opus-5-5`, low effort, at most 6 tool rounds, the last 10 messages of history. If the beta call fails it falls back to a standard call.

**The 5 tools all read `STORE`:**

| Tool | What it does |
|---|---|
| `search` | Turns names into ids |
| `get_schedule` | Student type / section / teacher / room, for a date or a weekday |
| `free_rooms` | By building and floor, sittable-only, minimum seats |
| `room_status` | e.g. "will G17 be empty at 12:30 on Friday?" |
| `teacher_free_slots` | Counts co-taught labs and leave |

**System prompt rules:**
- answer only from tool results; never guess
- resolve "today/tomorrow/Friday" to real dates
- plain text for phones
- point people to the right screen for changes

**The asker's identity** is passed in, so "my timetable" uses the student's own type.

It has **no write tools**.

---

## 7. Roles, sign-in and permissions

### 7.1 Sign-in
- **Session:** a signed session cookie `tw_session` (Starlette SessionMiddleware, 7 days), set by `/login.html`.
- **Demo mode** (`TIMEWEAVE_DEMO=1`, the default):
  - anyone can sign in as any demo account without a password
  - API clients and tests may send `X-User: <account id>`
- **No sign-in → 401** on every `/api/*` route except `/api/auth/*`. There is no default account.
- **Demo accounts (276):**

| Role | Accounts | Notes |
|---|---|---|
| student | 164 | one per student type |
| teacher | 94 | |
| hod | 6 | |
| coordinator | 5 | |
| club | 3 | DMC, CODE, ROBO, each with a faculty advisor |
| org | 2 | T&P cell, a visiting organisation |
| admin | 1 | |
| dean | 1 | |

### 7.2 The 8 roles and what they can do
(From `PERMISSIONS` and `capabilities()` in `app/auth.py`. The admin may do everything; anything not listed is denied.)

| Role | Can | Cannot |
|---|---|---|
| **Student** | view timetables, My timetable (their student type), free rooms, find a teacher, request a meeting, Now/Next, ask the assistant | book venues, use the slot finder, see the optimised timetable, approve anything |
| **Teacher** | My timetable, reply to their own meeting requests, mark their own leave, request venues (no advisor step), slot finder, cancel own bookings | mark a colleague's leave, change classes, approve venues |
| **Coordinator** (department timetable) | everything for **their own** department: substitutions (`override.create`), mark leave for department teachers, view / re-run / **propose** the optimised timetable, insights; books like a teacher | approve venues, publish, act on other departments |
| **HOD** | same as the coordinator, plus **approve bookings of rooms their department owns** | publish, regenerate, approve central halls, act on other departments |
| **Dean** (read-only) | every department's timetable, optimised view, insights, leave board, **audit log**, slot finder | change anything: propose, override, publish, book, request meetings |
| **Club lead** | request venues (goes to the faculty advisor first), slot finder, cancel own requests | endorse or approve its own request |
| **Org** (visitor / T&P) | request venues (no advisor step), slot finder, book for a batch audience | approve |
| **Admin** (timetable office) | everything: **regenerate**, **publish/unpublish**, approve **central halls**, see all accounts, demo reset, audit log | (none) |

- **Faculty advisor** is not a role: it is a teacher named as a club's advisor (`booking.endorse`).
- **Who approves a booking** depends on the room: its owning department's HOD, or the admin for central rooms.

### 7.3 Propose → publish flow (optimised CSE timetable)
1. The CSE HOD or coordinator opens `/compare.html`, compares the two timetables and presses **Propose to the timetable office**. Status → `proposed`; admins are notified.
2. The admin presses **Publish to everyone**:
   - It is refused (409) unless the optimised file has 0 clashes.
   - It is refused (409) if it breaks any college rule more often than the college's own timetable does; the message names the rule.
   - After installing it, the **independent validator re-checks** the whole college; if it finds any clash, publishing is undone (409).
   - Every CSE student and teacher is notified.
3. **Go back to the college's version** (unpublish) returns to `draft` and notifies everyone again.

### 7.4 Audit log
- **What is logged:** every privileged action through `require()` (everything except pure reads), **allowed or refused**, with time, user, role, action and target.
- **Retention:** the newest 2000 entries are kept, saved in `data/state.json`.
- **Where to see it:** `/audit.html` (admin and Dean).

### 7.5 The UI never decides
- `GET /api/me` returns `can`, a dictionary of 23 capabilities (e.g. `request_meeting`, `approve_venues`, `publish`).
- Pages show and hide tabs and buttons from `TW.can`, never from role names. The server is the gate.

---

## 8. Pages and screens
| Page | Who | What's on it |
|---|---|---|
| `/login.html` | everyone | Demo sign-in: pick an account by role |
| `/` (`index.html`, Lane B) | everyone signed in | **Timetable** tab: views and filters, week / dated week, the real-vs-generated panel (insights), **Regenerate** (admin), Print / Save PDF. **Find a teacher** (`#teacher`): day view, Request meeting. **Free rooms** (`#rooms`): Right now, building/floor, near me. **Meetings** (`#meetings`). **Substitutions** (`#subs`): leave board, candidates, Assign, Cancel class. **Teacher load** (`#load`). **Ask** (`#ask`, chatbot). **Mark leave**. **Now/Next** card. Phone layout with day tabs. |
| `/venues.html` (Lane C) | staff, clubs, orgs (by capability) | `#book` Book a venue (requirement form → ranked venues → request), `#requests` My requests with timeline, `#inbox` Approvals (endorse/approve/reject), `#slots` Event slot finder ("Find common free time", "Nearly free", "Book this") |
| `/compare.html` (Lane A) | CSE HOD/coordinator, Dean, admin | College vs optimised CSE timetable by section, student (group and electives) or teacher; before/after numbers (incl. "Same lab for two groups on one day"); **"GNDEC's timetable rules"**: each rule in plain words, must/prefer, and how often each version breaks it; Propose / Publish / Go back |
| `/audit.html` (Lane A) | admin, Dean | Audit log, newest first |
| Shared top bar (`shell.js`) | every page | Logo, navigation (hides what you can't use), account menu, 🔔 notifications |

---

## 9. API summary
Full contract: `docs/API.md`. The app has **35 API routes**:

| Group | Routes | Paths |
|---|---|---|
| Auth (`/api/auth/*`) | 3 | demo-accounts, demo-login, logout |
| Core (`/api/*`) | 22 | meta, me, users, audit, timetable, effective, generate, free-rooms, notifications (+read), demo/reset, chat, leave (POST/GET), substitutions, compare/cse (+run, propose, publish, unpublish), students/types, students/{type}/timetable |
| Dashboards (`/api/dash/*`) | 7 | ping, views, teacher/{id}/free, meetings (POST/GET), meetings/{id}/reply, now |
| Venues (`/api/venues/*`) | 7 | list, rank, requests (POST/GET), requests/{id}/decide, requests/{id}/cancel, slot-finder |

Errors are always `{"detail": "plain-English message"}` with status 400, 401, 403, 404 or 409.

---

## 10. Results and numbers

### 10.1 Generated departments (seeded IT/ECE/ME/CE/AS)
- **Saved timetable** (`data/solution.json`): status FEASIBLE, 45.9 s for the whole college.
- **Validator:** **0 clashes** for the whole college (853 sessions). The 329 quality notes all come from the real imported CSE data, never from generated classes (a test checks this).

Generated part, first feasible solution ("baseline") vs optimised:

| Measure | Baseline | Optimised |
|---|---|---|
| Idle periods per student-group day | 1.34 | **0.00** |
| Idle periods (total) | 214 | **0** |
| Single-lecture days | 5 | **0** |
| Days with no lunch break | 0 | 0 |
| Days over 6 periods | 0 | 0 |

(Day 1, before the real CSE import, the progress report showed **1.2 → 0.07** idle periods per day for 394 sessions in 20 sections.)

### 10.2 Real CSE timetable vs generated departments (`/api/timetable` → `compare`)
| Measure | GNDEC real CSE (as published) | TimeWeave-generated departments |
|---|---|---|
| Clashes | 0 | 0 |
| Idle periods per student day | 0.29 | 0.0 |
| Student-type days with **no lunch break** | **44** | 0 |
| Student-type days **over 6 periods** | **280** | 0 |
| Teacher days with 4+ in a row | 5 | 0 |
| Teacher days with no lunch | 5 | 0 |
| Classes in the 4:30–5:30 slot | 7 | 0 |

### 10.3 Optimised CSE timetable (same lessons, better times)
**Final result** (commit `32f1b45`, `data/gndec/cse_optimised.json`):
- a 15-minute run (896 s) with all 6 GNDEC college rules on
- the open elective and the two-room mentoring class pinned
- status IMPROVED
- **347 sessions moved, 69 pinned**
- 537 sessions in total

| Measure (CSE only, per real student type) | College (published) | TimeWeave optimised |
|---|---|---|
| Clashes (independent validator) | 0 | **0** |
| Student waiting periods per week | 181 | **75** (−59%) |
| Waiting periods per student day | 0.29 | **0.12** |
| Student-type days with **no free hour 11:30–2:30** | 44 | **0** |
| Single-lecture days | 11 | **10** |
| Student-type days over 6 periods | 280 | **253** |
| Teacher waiting periods | 314 | **100** (−68%) |
| Teacher days with 4+ lectures in a row | 5 | **1** |
| Teacher days with no free hour 11:30–2:30 | 5 | **3** |
| Same lab for two groups on one day (`lab_same_day`) | 12 | **9** |
| Classes after 4:30 (4:30–5:30 slot) | 7 | 7 (pinned mentoring) |
| Worst gap | 4 | 4 |
| Room use (classrooms / labs) | 17.8% / 29.9% | 17.8% / 29.9% (same rooms) |
| **College rules** (6.3b): breaks of `labs-on-different-days` / `nothing-after-jpal` / `real-class-every-day` / the 3 keep rules | 12 / 1 / 0 / 0 | **9 / 1 / 0 / 0** |

**Why the numbers changed between runs:**
- **The `aac5df1` run** showed waiting periods 181 → 16. That was measured **without** the open elective. Three 8:30 classes a week for all of D4 (OE-II, which can't be moved) make some longer waits unavoidable. The college column changed slightly too, because the open elective is now counted.
- **The `3acc154` run** put SC Lab A1 and A2 on the same day (reported by a student). The lab-pair rule (`becb48e`) fixed that: waiting periods 81, teacher waiting periods 109.
- **The `becb48e` run** left 6 D4 Fridays with only the major project and the open elective. The college rules (`32f1b45`) fixed that (real-class-every-day: 6 → 0 breaks) and also give the final, better numbers above.

**Publishing is guarded.** While the re-run was going on, the saved optimised file briefly had 1 clash (a moved class overlapping the newly pinned OE-II), and publishing was correctly refused with 409.

---

## 11. Testing: every test and the edge case it covers

### 11.1 Totals
Commands: `.venv/Scripts/python -m pytest -q -rA` and `pytest --collect-only -q`, run 26 Oct 2026.

| Code state | Tests | Passed | Failed | Time |
|---|---|---|---|---|
| **Final: commit `32f1b45`** | 95 | **95** | **0** | 58 s |
| Earlier: commit `becb48e` (before the 7 college-rules tests) | 88 | 88 | 0 | 67 s |
| Earlier: commit `3acc154` (before the lab-pair test) | 87 | 87 | 0 | 28 s |
| Earlier: commit `aac5df1` (before the 3 groups-page tests) | 84 | 84 | 0 | 64 s |

| File | Lane | Tests | Pass |
|---|---|---|---|
| `tests/test_validator.py` | A | 12 | 12 |
| `tests/test_core_permissions.py` | A | 17 (incl. 5 parametrised) | 17 |
| `tests/test_core_fet.py` | A | 7 (3 added in `3acc154`) | 7 |
| `tests/test_core_students.py` | A | 6 | 6 |
| `tests/test_core_store.py` | A | 4 | 4 |
| `tests/test_core_substitutions.py` | A | 4 | 4 |
| `tests/test_core_optimise.py` | A | 3 (1 added in `becb48e`) | 3 |
| `tests/test_core_rules.py` | A | 7 (added in `32f1b45`) | 7 |
| **Lane A total** | | **60** | **60** |
| `tests/test_dashboards_api.py` | B | **14** | 14 |
| `tests/test_venues_approvals.py` | C | 7 | 7 |
| `tests/test_venues_ranking.py` | C | 8 (incl. 4 parametrised) | 8 |
| `tests/test_venues_slots.py` | C | 6 | 6 |
| **Lane C total** | | **21** | 21 |
| **Overall** | | **95** | **95** |

**Note:** while the optimiser re-run was in progress, 2 tests failed as expected:
- `test_core_optimise.py::test_no_clashes_and_never_worse`
- `test_core_permissions.py::test_propose_publish_unpublish_keeps_zero_clashes`

The saved optimised timetable didn't yet fit around the newly pinned open elective, and publishing was refused with 409. Both pass from `3acc154` on. This shows the tests catch a stale optimised timetable.

**Test hygiene (applies to all files):**
- **Tests never write to `data/`:** every test that changes state monkeypatches `app.store.STATE` to a pytest temp folder. One dashboards test checks this (`STATE.exists()` in the temp path). The permissions tests also restore the published state, audit log and notifications after each test.
- **Fresh data:** most tests build their own fresh, solved seed college and store, or reset overrides, bookings, meetings and notifications, so they don't depend on demo state.
- **No hard-coded ids:** tests pick accounts dynamically (e.g. "a HOD of another department"), because ids changed when the real GNDEC data arrived.
- **Sign-in:** tests sign in with `X-User` (demo mode) or through `/api/auth/demo-login`.

### 11.2 `tests/test_validator.py`: proving the "0 clashes" claim (12)
These are "testing the tester": mutation tests inject each kind of mistake and check that the validator catches it.

| Test | What it checks · edge case |
|---|---|
| `test_solver_output_has_no_clashes` | Solver output has 0 clashes; quality notes may come only from imported real data, never from generated classes |
| `test_every_session_placed_once` | Number of placed sessions equals the sum of all lessons' sessions (nothing dropped or duplicated) |
| `test_detects_student_and_teacher_clash` | Moving a class on top of another class the **same student type** attends is reported as `CLASH Students` |
| `test_detects_room_clash` | Two labs moved into the same room at the same time are reported as `CLASH Room` |
| `test_detects_block_past_end_of_day` | A 2-period lab starting in the last period is reported as "runs past the end of the day" |
| `test_every_generated_group_gets_lunch` | No generated group has a `NO LUNCH` day (flexible lunch rule) |
| `test_detects_missing_lunch` | Three classes packed into all of 11:30–2:30 are reported as `NO LUNCH Students` |
| `test_detects_unavailable_teacher` | The visiting teacher (Tue/Thu only) moved to Monday is reported as "unavailable" |
| `test_detects_missing_session` | Deleting one session is reported as "sessions placed … required" |
| `test_detects_wrong_room_type` | A lab put in a lecture theatre is reported as "needs a Computer Lab" |
| `test_precheck_explains_overloaded_teacher` | Prechecks explain an impossible input in plain English (teacher available only Tuesday, max 3 a day, with 4 hours assigned) |
| `test_unknown_lesson_flagged` | An entry for a lesson that doesn't exist is flagged |

### 11.3 `tests/test_core_permissions.py`: role-based access (17)
| Test | What it checks · edge case |
|---|---|
| `test_every_api_route_needs_sign_in_except_auth` | Walks **every** `/api` route of the app and checks that it depends on `current_user` (except `/api/auth/*`): no route is accidentally left open |
| `test_no_sign_in_is_401` ×5 | `/api/meta`, `/api/me`, `/api/timetable`, `/api/free-rooms`, `/api/notifications` return **401** with no sign-in |
| `test_session_sign_in_and_out` | The demo account list is open; signing in as an unknown user gives 404; signing in as the Dean works and `/api/me` shows `audit` but not `publish`; after logout `/api/me` gives 401 |
| `test_admin_may_do_everything_and_unknown_actions_are_refused` | The admin passes every rule; an **unknown action is refused even for the admin** (deny by default) |
| `test_college_wide_actions_are_admin_only` | Generate, publish, see accounts and demo reset are refused for Dean, HOD, coordinator, teacher, student, club and org |
| `test_department_staff_only_manage_their_own_department` | HOD and coordinator of CSE may view/run/propose/override for **CSE but not ME**; the ME HOD can't see the CSE optimiser; students and teachers can't |
| `test_dean_reads_but_never_changes` | The Dean may view the optimiser, insights, audit and timetables, but not run, propose, override, publish or **request meetings** |
| `test_leave_rules` | A teacher may mark **their own** leave but not a colleague's; HOD and coordinator may for their department, another department's HOD may not; the Dean may view but not mark leave |
| `test_venue_approval_goes_to_the_rooms_hod` | Only the HOD of the room's department approves (not another HOD, not the coordinator); only the club's advisor endorses (not the club itself); only the requester may cancel (not another club) |
| `test_capabilities_follow_the_table` | `/api/me.can` matches the table: a student can request meetings but not publish or approve; the admin has everything except the teacher-only items; HOD CSE can propose and substitute but not publish; the ME HOD can't see the CSE optimiser |
| `test_endpoint_refusals` | Real HTTP calls: student → 403 on compare, users, audit, demo reset; ME HOD → 403 on the CSE compare; CSE HOD → 403 on publish; Dean → 403 on propose but 200 on view; a student can read their own timetable |
| `test_refusals_are_audited` | A refused demo reset by a student lands in the audit log with `allowed: false`, and the Dean sees it first in `/api/audit` |
| `test_propose_publish_unpublish_keeps_zero_clashes` | Coordinator proposes → admin notified → admin publishes → the independent validator finds 0 issues → unpublish → still 0. Edge case seen for real: while the saved optimised file had 1 clash (during the re-run), publish was refused with 409, the "publish refused when there are clashes" rule |

### 11.4 `tests/test_core_fet.py`: importing GNDEC's real timetable (7)
| Test | What it checks · edge case |
|---|---|
| `test_matches_published_room_page` | Matches the published page: room **G17 is busy in exactly 30 of 45 slots**; G17, S218, SL-I LAB and WS SEMINAR HALL exist |
| `test_sections_groups_and_labs` | D2 CS A has groups A1/A2; D3 CS A has **6 elective sub-groups**; every lab is a 2-period block; some lessons have 2–3 co-teachers |
| `test_real_timetable_has_no_clashes` | GNDEC's real timetable has **0 hard clashes**; the only notes are `NO LUNCH` and `LONG DAY` quality notes |
| `test_cell_parsers` | Parsing of group lists ("D3 CS A1, D3 CS B1"), a whole section with no sub-group ("D2 CS D"), teacher tags that are departments ("(App. Sci.)" → AS, "(JDS-CE)" → CE), lab vs lecture codes, elective names |
| `test_groups_page_adds_open_elective_and_two_room_class` | *(added in `3acc154`)* The rooms page can't show OE-II; the groups page adds exactly 4 classes and **skips "Self Study"**; OE-II covers all D4 groups, 3 sessions, pinned, Mon/Wed/Fri 8:30 in the other-department room; the **two-room class** (S202 + S203) is added once; still 0 clashes |
| `test_open_elective_is_pinned_and_in_d4_timetables` | *(added in `3acc154`)* The optimiser may not move OE-II; **every D4 student type** has it in its timetable |
| `test_outside_room_is_never_a_free_room` | *(added in `3acc154`)* The "other department" placeholder room never shows up as a free room |

### 11.5 `tests/test_core_students.py`: real students (6)
| Test | What it checks · edge case |
|---|---|
| `test_saved_combinations_hold_no_personal_data` | **Privacy:** `students.json` has no 7-digit roll numbers and only the allowed anonymous fields; D4 adds up to **150** students and D3 to **340** |
| `test_every_class_has_its_students` | Every real D3/D4 class is attended by at least one student type (no orphan classes) |
| `test_a_real_student_sees_only_their_electives` | `D4-CS-A:A2:CV:SCA1:TA3` gets CV, SC, **SC Lab A1** and TA Lab, and **not** DWDM/DAAA/SDN/ACC/WT or **the other lab group's SC Lab A2** (the FET re-used-group bug) |
| `test_college_timetable_has_no_clash_for_any_real_student` | Real CSE plus generated departments: no student clash for any real combination |
| `test_validator_catches_a_clash_between_two_electives_one_student_takes` | Moving Soft Computing on top of Computer Vision is caught as a clash for CV+SC students (electives that look unrelated in FET) |
| `test_student_timetable_api` | `/api/students/{type}/timetable` gives 401 without sign-in, then exactly that student's classes (CV and SC, no DWDM); days are valid; `/api/me` shows the student type and section |

### 11.6 `tests/test_core_store.py`: date overrides (4)
| Test | What it checks · edge case |
|---|---|
| `test_effective_matches_weekday_and_weekend` | A real Friday has exactly the Friday classes; a **Saturday is empty** |
| `test_cancel_substitute_and_room_change` | Substitute → status `substituted`; room change → new room; cancel → gone. The **base timetable is untouched** and **the next Friday is unaffected** |
| `test_booking_occupies_room_only_on_that_date` | A booking of the WS Seminar Hall blocks it that date only, not a week later |
| `test_permissions` | Students and HODs can't regenerate, the admin can; the advisor endorses but the club can't; the CSE HOD approves the CSE-owned MBA Seminar Hall, the ME HOD can't; **the Auditorium (central) is admin only** |

### 11.7 `tests/test_core_substitutions.py`: absences (4)
| Test | What it checks · edge case |
|---|---|
| `test_leave_lists_classes_with_free_candidates` | The busiest teacher on leave: every open class has candidates; **no candidate is the absent teacher or busy at that time** (co-taught classes count); scores are sorted high → low |
| `test_assign_substitute_only_changes_that_date` | After assigning, the class shows the substitute (`substituted`) **only that date**; the next Friday still has the regular teacher; **re-deciding (cancel instead) replaces the earlier decision**, leaving exactly one override |
| `test_substitute_is_not_offered_twice_at_the_same_time` | A teacher already substituting at that time is no longer offered for another class at the same time |
| `test_permissions` | A teacher may mark their own leave but not a colleague's; HOD yes, other department's HOD no; only department staff create overrides; students never |

### 11.8 `tests/test_core_optimise.py`: optimised real CSE timetable (3)
| Test | What it checks · edge case |
|---|---|
| `test_same_lessons_only_times_change` | The same lessons with the same number and length of sessions; every room is of the kind the lesson needs; **pinned sessions (M.Tech, PhD, mentoring) are exactly where the college put them** |
| `test_no_clashes_and_never_worse` | Checked per real student type: 0 clashes; **never worse** on 8 measures (waiting periods, no-lunch days for students and teachers, teacher streak days, late sessions, long days, single-lecture days, same lab for two groups on one day); strictly better on waiting periods; **the numbers saved in the file are honest** (they equal a fresh measurement) |
| `test_a_teachers_lab_for_two_groups_stays_on_two_days` | *(added in `becb48e`, after a student's report)* Every lab pair the college keeps on different days stays on different days after optimising; **SC Lab A1 / A2 is a known pair** (the case the student pointed out). Edge case: pairs the college itself has on one day may stay, so "never worse" still holds |

(All three skip cleanly if no optimised timetable has been saved yet.)

### 11.8b `tests/test_core_rules.py`: college rules (7, added in `32f1b45`)
| Test | What it checks · edge case |
|---|---|
| `test_rules_load_and_match` | All 6 GNDEC rules load with a known type and plain-English text; selectors work by **code** (JPAL matches nothing-after-jpal), **teacher** (JPAL has no CSE teacher, so it's "run with another department") and **year** (an M.Tech class is postgraduate; CV is not) |
| `test_what_stays_where_the_college_put_it` | Mentoring, `TBA-` (other-department) and M.Tech/PhD lessons are never movable; an ordinary elective (CV) is |
| `test_college_timetable_against_its_rules` | The college's own timetable: real-class-every-day **0** breaks; nothing-after-jpal **exactly 1** (D4 CS C mentoring, Wed 15:30); lab pairs on one day **12** |
| `test_a_day_with_only_open_elective_and_project_is_caught` | The project owner's example: remove D4 CS A's real Friday classes, leaving only open elective/project/mentoring/JPAL, and the checker flags "no real class on Fri" for D4 CS A |
| `test_a_class_after_jpal_is_caught` | Moving CV to Thu 15:30, right after JPAL, is flagged as a class after JPAL |
| `test_optimised_timetable_obeys_the_rules` | For every rule, the optimised timetable breaks it **no more often than the college**; a **must** rule the college keeps (0 breaks) stays at 0; **the break counts saved in the file are honest** (equal a fresh count) |
| `test_publish_refuses_a_timetable_that_breaks_the_rules` | A clash-free timetable with a class after JPAL is **refused with 409** ("JPAL" in the message) and is not published. Edge case: clash-free is not enough; it must also respect the college's rules (state is written to a temp file) |

### 11.9 `tests/test_dashboards_api.py`: Lane B (14)
Runs against a freshly solved seed college, with state in a temp file.

| Test | What it checks · edge case |
|---|---|
| `test_student_view_shows_exactly_their_classes` | A student's view has exactly the classes their type attends, including whole-section and single-group classes; an unknown type gives 404 |
| `test_types_sharing_a_group_number_can_differ` | Two student types in one section see different weeks (group numbers are not students) |
| `test_section_year_and_dept_views_nest` | student ⊂ section ⊆ year ⊆ department ⊂ whole college |
| `test_every_department_has_a_view` | Every department, including **Applied Sciences with no sections of its own**, has a non-empty view |
| `test_teacher_and_room_views` | The teacher view has only that teacher's classes; the room view only that room's |
| `test_week_of_returns_monday_to_friday` | `week_of` a **Saturday** gives the **next** Mon–Fri (5 dates) |
| `test_free_slots_exclude_teaching_and_unavailable` | Free = all periods minus teaching minus unavailable, with nothing overlapping; a weekend date is flagged `weekend`; an unknown teacher gives 404 |
| `test_meeting_round_trip_and_permissions` | Asking for a **busy** period → 409; a **teacher** asking → 403; asking **twice** → 409; the teacher is notified and sees it pending; the **student can't reply, nor can another teacher** (403); after accepting, the student is notified and the slot shows `meeting` (no longer free); saved to the temp file, not `data/` |
| `test_now_card` | Now = the student's current class, Next is later; **before the day starts** (`period=-1`) Now is empty and Next is the first class; the admin (no timetable) gets `who: null` |
| `test_co_taught_labs_count_as_busy` | A co-teacher sees the lab in their view and is `teaching` (not free) in those periods |
| `test_leave_blocks_free_slots_and_now_card` | A **whole-day leave** (no periods given) makes every period `leave`, nothing free, and Now/Next empty |
| `test_substituted_class_names_both_teachers` | A substituted class shows the substitute and `regular_teacher_name` |
| `test_dashboards_need_sign_in` | `/api/dash/views` without sign-in gives 401 |
| `test_dean_is_read_only` | The Dean can view a teacher's week and free slots, but requesting a meeting gives 403 |

### 11.10 `tests/test_venues_approvals.py`: Lane C approvals (7)
| Test | What it checks · edge case |
|---|---|
| `test_club_request_advisor_then_hod_then_room_leaves_free_rooms` | The full chain. The hall is free, then the club requests it: the advisor is notified, the request is in the advisor's inbox but not yet the HOD's. **The HOD can't skip the advisor; the club can't approve itself.** The advisor endorses and the HOD is notified; **the advisor can't give final approval; another department's HOD can't.** The HOD approves, and **the hall leaves Free rooms** for both periods; the timeline ends "Booked". **The advisor can't cancel; the club can**, and the room is free again |
| `test_rejection_needs_a_reason_and_tells_the_club` | Reject without a note → 400; with a note, the club is told the reason; deciding an already-rejected request → 409 |
| `test_central_room_goes_to_admin_and_teacher_skips_advisor` | **A central hall's chain is advisor → admin**; a teacher's request goes **straight to the admin** (no advisor); a HOD can't approve a central room (403); the admin can |
| `test_final_approval_refused_if_room_was_taken_meanwhile` | Two requests for the same slot: the second gets a warning; after the first is approved, approving the second gives **409 "no longer free"**, and a fresh request for that slot is refused up front |
| `test_who_may_request` | A **student can't request** a venue (403); an unknown room gives 400 |
| `test_event_audience_hears_about_approval_and_cancellation` | An unknown audience group gives 400; the audience label is the section name; **students hear nothing until approval**, then every student of the batch gets "Event for your batch"; students outside the batch don't; everyone in the batch is told on cancel |
| `test_new_roles_and_sign_in` | A coordinator books with no advisor step (HOD only) and **can't approve**; the Dean **can't book** but may use the slot finder; signed out → 401 |

### 11.11 `tests/test_venues_ranking.py`: Lane C ranking (8)
| Test | What it checks · edge case |
|---|---|
| `test_fits_are_free_big_enough_and_closest_first` | Every offered venue seats ≥ 100, has projector + sound and is free in both periods; the reason line starts "Seats N for 100 people · has projector and sound"; **the smallest fitting room comes first**; near misses all have a reason |
| `test_room_with_a_class_is_not_offered` | A room with a class in P3–P4 is not offered for P3–P4 (near miss "Busy in P3–P4: class …") but is offered for P5 |
| `test_booking_override_takes_room_out` | After a booking override, the room is not offered and its near miss says "booked for Test event" |
| `test_too_small_and_missing_features_are_explained` | 5000 people with a stage: no venues, and near misses say "Too small" |
| `test_bad_input_gets_plain_400` ×4 | **Weekend date**, **periods not back to back** ([1, 3]), **unknown requirement** ("jacuzzi") and a **date in the past** each give a plain-English 400 |

### 11.12 `tests/test_venues_slots.py`: Lane C slot finder (6)
| Test | What it checks · edge case |
|---|---|
| `test_never_returns_a_slot_where_a_group_has_class` | Slots never overlap any audience group's class, but the rest of the day is offered; **a class for just one group still blocks the whole audience** |
| `test_cancelled_class_frees_the_slot` | A cancelled class frees its slot on that date |
| `test_slots_come_with_venues_and_lunch_warning` | A slot that uses **the only lunch period left** is warned about; other slots aren't; every venue fits 50 people with a projector; lunch-eating slots are ordered after the others |
| `test_real_timetable_dept_year` | Dept + year over a real Mon–Fri week: the audience covers every group of the section; no clashes |
| `test_permissions_and_bad_input` | A club may use it (200); a student can't (403); no audience → 400; unknown group → 400; duration 99 → 400 |
| `test_almost_free_slots_name_who_would_miss_class` | When the whole lunch window is already busy there is **no lunch warning** (nothing left to protect); "nearly free" times name the exact busy groups, the section and its classes, and whether the whole section is missing |

### 11.13 What the automated tests don't cover (honest gaps)
- **The chatbot** (`/api/chat`) has no automated test. This is on purpose: it would spend the limited Anthropic API credit. Its tools read the same `STORE` functions the tested endpoints use.
- **The HTML pages** (index, venues, compare, login, audit) have no browser tests. They were checked by hand during development.
- **`POST /api/generate` and `POST /api/compare/cse/run`** are only tested indirectly: the solver and optimiser output are tested, and the permission rules for generate are tested.
- **Optimiser runs** themselves are not run in tests (they take minutes); the tests check the saved result.

---

## 12. Timeline: how it was built
From `git log` (51 commits up to `32f1b45`, including 3 commits of this report). Commits per day: 21 Oct 15 · 22 Oct 14 · 26 Oct 22.

### Day 1: Wed 21 Oct, prototype (v0.1), demo at 4 PM
- Scaffold, `CLAUDE.md`, plan.
- Seeded college: 5 departments + Applied Sciences, 20 sections, 39 teachers, 38 rooms, 394 sessions.
- CP-SAT solver, independent validator, API and UI.
- Validator mutation tests and a solver golden test (12 tests).
- Read-only Claude assistant with 4 tools.
- Flexible lunch (a free hour anywhere in 11:30–2:30).
- Print / Save as PDF.
- `PLAN.md`, `docs/DESIGN.md`; Day 1 progress report (PDF, one-page and detailed).

### Day 2: Thu 22 Oct, v2 foundation and the three lanes
- **Lane A:** shared store with `effective(date)`, demo accounts and permissions, per-lane routers, shared top bar, API contract; **import of GNDEC's real CSE timetable from FET** (the generator now fills only the other departments).
- **Lane B:** `/api/dash` views, teacher free slots, meeting requests and replies, Now/Next; role-aware home with all filters, find a teacher, free rooms by building and floor with near-me; tests.
- **Lane C:** venue ranking with reasons and near misses; booking requests with advisor → HOD/admin approvals; event slot finder; mobile-first venues page; tests.

### Fri 23 – Sun 25 Oct
- No commits on these days (from `git log`).

### Mon 26 Oct: real-data depth, substitutions, optimiser, access control
- **Lane A:**
  - substitutions and date-aware chatbot tools
  - importer fixes
  - **optimiser for the real CSE timetable**
  - **student types** from the distribution lists
  - Elective-IV labs per lab group
  - two 15-minute re-optimisations
  - **role-based access** (sign-in, permission table, capabilities, audit log, propose/publish)
- **Lane B:**
  - leave and substitutions screen
  - real-vs-generated panel
  - student timetables by student type
  - no lunch labels
  - `TW.can` throughout
- **Lane C:**
  - clubs get the slot finder
  - events booked for a batch notify its students
  - `TW.can` and sign-in
- **Lane A, last:** the FET groups page (open elective OE-II, the two-room mentoring class; fixes ERP missing from students' timetables) and a 15-minute re-optimisation around it (`3acc154`). Then the lab-pair rule (SC Lab A1 / A2 stay on two days, reported by a student) and another 15-minute re-optimisation (`becb48e`). Last, **College rules**: 6 GNDEC rules written down in JSON, obeyed by the optimiser, counted by an independent checker, enforced on publish, plus 7 tests and a final 15-minute re-optimisation (`32f1b45`). This report was committed alongside.

### Cross-lane requests (`docs/REQUESTS.md`)
11 entries:
- 9 ticked done
- 2 not ticked:
  - **Role-based access:** both lanes report their part done (Lane B in the entry itself, Lane C in a separate entry), but the box is not ticked.
  - **Open:** a `leave_board` capability, so the Dean's read-only Substitutions tab doesn't need a role check.

---

## 13. How the team worked (3 parallel lanes)
- Three Claude Code sessions worked **in the same folder**, with no branches and no merging. Each lane edits **only the files it owns**.

| Lane | Owns | Dev server port |
|---|---|---|
| **A. Core and data** | models, store, auth, solver, validator, optimiser, college rules, importers, substitutions, chat, core API, shell.js, login/compare/audit pages, shared docs | 8001 |
| **B. Dashboards UI** | `index.html`, `dashboards.js`, `/api/dash` | 8011 |
| **C. Venues and events** | `venues.html`, `venues.js`, `app/venues/*`, `/api/venues` | 8012 |

- **Cross-lane changes** go through `docs/REQUESTS.md`; the contract is `docs/API.md`.
- **Commits:** each lane stages only its own paths and commits after every working step. **The tests stay green** and the app always imports cleanly.

---

## 14. How to run it
(From `CLAUDE.md`, Windows.)

Setup:
```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
```

Run the app (then open http://localhost:8001):
```bash
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8001
```

Run the tests:
```bash
.venv/Scripts/python -m pytest -q
```

Solve the seeded college from the command line:
```bash
.venv/Scripts/python -m app.solver
```

- **Optional:** copy `.env.example` to `.env` and add `ANTHROPIC_API_KEY` for the assistant (never commit `.env`).
- **Demo mode** is on by default (`TIMEWEAVE_DEMO=1`). Sign in at `/login.html` by picking an account.
- **Re-import:** `python -m app.importers.fet` (FET HTML → `data/gndec/cse.json`) and `python -m app.importers.gndec_students` (needs the private lists). Re-optimise with `python -m app.optimise <seconds>`; it takes minutes.
- **Requirements:** FastAPI, OR-Tools, the Anthropic SDK, pypdf, and the rest of `requirements.txt`.

---

## 15. Demo script
Suggested, about 5 minutes. Built only from features listed above.

1. **The problem** (30 s): hand-made timetables take weeks, still have problems, and students wait between classes. The real GNDEC CSE timetable has 0 clashes but 44 student-days with no midday break and 280 days over 6 periods.
2. **Sign in as a student** (`/login.html`): pick a D4 CS A student type (e.g. "A2 · CV · SC A1 group · TA A3").
   - My timetable shows only *their* electives and *their* lab group.
   - Explain the FET re-used-group problem and student types.
   - Show the **Now/Next** card and **Free rooms → Right now** by building and floor.
3. **Find a teacher → Request meeting** in a free period. Switch to that teacher, accept, and the student gets a 🔔.
4. **Teacher marks leave.** As the CSE HOD, open **Substitutions**: ranked substitutes with reasons. Assign one; the student's timetable shows the substitute for that date only.
5. **Venues as the Digital Marketing Club:**
   - Book a venue for 100 people with projector + sound: ranked rooms with reasons.
   - Request → faculty advisor endorses → HOD approves → the hall disappears from Free rooms.
6. **Event slot finder as T&P:** D4 CS for a 2-hour talk: slots where every group is free, venues attached, lunch protected, and "nearly free" times showing who would miss which class. **Book this** notifies the batch.
7. **Optimised CSE timetable** (`/compare.html`, as the CSE HOD): college vs optimised, side by side.
   - Same lessons, times only.
   - Student waiting periods 181 → 75, no-lunch days 44 → 0, teacher waiting periods 314 → 100, 0 clashes.
   - Scroll to **"GNDEC's timetable rules"**: each college habit in plain words, and how often each version breaks it. Tell the story: the previous optimised timetable left 6 D4 Fridays with only project + open elective; writing the rule down fixed it (6 → 0).
   - Point out that publishing is refused if a rule is broken more often than in the college's own timetable.
   - **Propose**, then as the admin **Publish**; the validator re-checks it.
8. **Trust:** the independent validator, the independent college-rules check, 95 automated tests, and the audit log (`/audit.html` as the Dean) showing a refused action.
9. **Ask TimeWeave** (optional, uses API credit): "Will G17 be free at 12:30 on Friday?"

---

## 16. Known limitations and future work
**Not built yet** (designed in `PLAN.md` / `docs/DESIGN.md`):
- **Data in and out:**
  - Excel/CSV import with row-level errors
  - "check my existing timetable" upload
  - Excel export
  - calendar feed (.ics)
- **Editing:**
  - manual drag-and-drop editor with live clash warnings
  - **minimal-change repair** with a diff preview
  - a general change engine for all edits (today the only "apply" paths are overrides, substitutions, bookings and propose/publish)
- **Chatbot propose tools:** it is read-only today.
- **Persistence:** in memory + JSON files, not SQLite/Postgres; no optimistic locking for two editors.
- **Real sign-in:** Google sign-in restricted to the college domain is not built (demo mode only). It also needs a staff/student directory to map college emails to roles and student types.
- **Hosting and alerts:** deployment (Render + Neon), room door QR page, live updates (SSE), PWA/push, email/WhatsApp notifications.

**Data gaps:**
- "Self Study · Library" slots on the groups page are deliberately not imported (they are not classes).
- Only CSE is real; the other departments are synthetic.
- Real CSE teachers' unavailability isn't known (none is assumed).
- Elective-IV lab days rely on one student's confirmation.

**Optimiser:**
- Built for CSE (the `/api/compare/cse` routes are CSE-specific).
- 7 classes in the 4:30–5:30 slot stay (pinned mentoring).
- Days over 6 periods improve only partly (280 → 253), because D3 groups have 36 periods a week.
- 9 lab pairs stay on one day, because the college itself schedules them that way (12 in the college's version), mostly in 2nd year. The rule only keeps apart pairs the college already splits.
- Three fixed 8:30 open-elective classes a week for all of D4 limit how far waiting periods can drop (181 → 75).
- Teacher days with no midday hour: 5 → 3. The optimiser removes most, but not all.
- One class after JPAL remains: the college's own pinned D4 CS C mentoring, Wed 3:30.

**College rules:**
- Only rules the college has confirmed are written down. A guessed rule ("project only in the morning") was dropped, because the college itself has a project hour at Mon 3:30.
- `real-class-every-day` excludes D1, because 1st-year subjects are in Applied Sciences' timetable, not CSE's.
- A new rule *type* needs code: a check in `rules.breaks()` and a constraint in `optimise.py`. New rules of the 5 existing types need only JSON.

**Open cross-lane request:** a `leave_board` capability for the Dean.

**Security notes:**
- The session secret has a development default; set `TIMEWEAVE_SECRET` in production.
- Demo mode (`X-User` header) must be turned off (`TIMEWEAVE_DEMO=0`) for real use.

**Scale:** about 46 s to generate the seeded departments; the optimiser needs about 15 minutes for its best result.

---

## 17. Key numbers for slides
| Number | What |
|---|---|
| **0** | clashes, proven by an independent validator that shares no code with the solver |
| **853** | weekly sessions in the whole college (537 real GNDEC CSE + 316 generated) |
| **~46 s** | to generate all seeded departments around the real CSE timetable |
| **150 / 48** | D4 students / real elective combinations modelled |
| **340 / 57** | D3 students / real elective combinations modelled |
| **164** | student types, so every real student's timetable is exact |
| **44 → 0** | CSE student-days with no midday break: college vs optimised |
| **181 → 75** | CSE student waiting periods per week (−59%), same lessons, 0 clashes |
| **314 → 100** | CSE teacher waiting periods per week (−68%) |
| **5 → 1** | CSE teacher-days with 4+ lectures in a row |
| **6** | GNDEC timetable rules written down; every one kept at least as well as the college does |
| **6 → 0** | D4 Fridays with only project + open elective (previous run vs final), fixed by writing the rule down |
| **1.34 → 0.00** | idle periods per day in generated departments (first feasible vs optimised) |
| **8** | roles, with a deny-by-default permission table and an audit log |
| **35** | API routes |
| **95 / 95** | automated tests passing |
| **3** | parallel build lanes, 51 commits |

---

## 18. Sources
**Files read:**
- `CLAUDE.md`, `PLAN.md`, `README.md`
- `docs/DESIGN.md` (headings), `docs/API.md`, `docs/REQUESTS.md`
- `docs/progress/report.html` (Day 1 report)
- `app/auth.py`, `app/models.py`, `app/store.py`, `app/solver.py`, `app/validator.py`, `app/optimise.py`, `app/substitutions.py`, `app/chat.py`, `app/seed.py`, `app/main.py`
- `app/importers/fet.py`, `app/importers/gndec_students.py`
- `app/api/core.py` (routes, compare/publish), route lists of `app/api/dashboards.py` and `app/api/venues.py`
- `app/static/*.html` and `js/shell.js` (labels and tabs)
- every file in `tests/`

**Data:**
- `data/gndec/cse.json`, `data/gndec/students.json`, `data/gndec/rules.json`, `data/gndec/cse_optimised.json` (current, and earlier versions via `git show <commit>:`), `data/solution.json` (through `STORE.result`)
- **Not read:** `data/private/`

**Commands (26 Oct 2026):**
- `pytest -q` on commit `32f1b45`: **95 passed** (final)
- `pytest -q` on commit `becb48e`: 88 passed
- `rules.breaks()` on the `becb48e` optimised timetable (`git show becb48e:data/gndec/cse_optimised.json`): real-class-every-day broken 6 times
- read `app/rules.py`, `data/gndec/rules.json`, the rule constraints in `app/optimise.py`, and the `32f1b45` changes to `app/api/core.py` and `CLAUDE.md`
- `pytest -q` on commit `3acc154`: 87 passed
- a Python check of `College.lab_pairs()` (86 pairs, 54 in CSE) and of the SC/ACC lab days in the optimised file
- earlier: `pytest -q -rA` on the working tree before the re-run (85 passed, 2 failed as expected) and on a clean checkout of `aac5df1` (84 passed)
- `pytest --collect-only -q` (87 tests at `3acc154`; 88 at `becb48e`; 95 at `32f1b45`)
- a Python check printing college counts, metrics and `compare` from `app.store.STORE`
- `git log`, `git log --stat`, `git diff --stat`, `git status`

**Deliberately not run:** `python -m app.optimise` (Lane A ran the 15-minute re-run) and `/api/chat` (limited API credit).

**From Lane A's session:** the background of the groups-page import (the student who noticed ERP was missing). The resulting numbers were checked here against the committed `data/gndec/cse_optimised.json` and `data/gndec/cse.json`.

---

## 19. Pending
**Resolved on 26 Oct** (after commit `32f1b45`):
- Final test totals: **95 / 95 pass** (re-run here; Lane A 60, B 14, C 21).
- College-rule break counts: checked against `cse_optimised.json` and `rules.report()`.
- Final optimised CSE numbers (§10.3, §17): checked against the committed `data/gndec/cse_optimised.json`.
- College counts (§4, §7.1): these were measured on data that already included the open-elective import. They match the committed `data/gndec/cse.json` (41 rooms, 62 teachers, 26 sections, 318 lessons, 537 sessions).
- The 3 groups-page tests are committed.

**Still not verified:**
- UI behaviour was described from page source (labels, tabs, `x-show` rules), not from clicking through every screen in a browser.

# TimeWeave: complete project documentation (hackathon report source)

> **What this file is:** the complete, checked record of what TimeWeave is, what was built, how it works, the real GNDEC data it uses, the numbers, and every automated test with the edge case it covers. Use it as the source for the submission report (submission: **Tuesday 27 Oct 2026**).
>
> **Live demo:** **https://timeweave-3y2g.onrender.com**. It runs on a free server: if it has been idle, the first visit takes about a minute to wake it. Sign in as any role; no password.
>
> **How it was checked:** every claim comes from the repository (code, docs, git history), the test suite, or a command run on **26–27 Oct 2026**. Nothing is from memory. The commands are listed under [Sources](#18-sources). Anything that could not be confirmed yet is listed under [Pending](#19-pending).
>
> **State of the repo when this was written:**
> - Final numbers are from commit `2ac1a85` (27 Oct 2026), after deployment (`5a6a9bc`, `a557f04`, `2ac1a85`). Before that came Lane A's full browser run-through of every role (`d3e1a9d`). The last data changes were `89254d8` (two same-named teachers kept apart: 5 teacher clashes in the published data) and `53e1f7f` (**first year linked across departments**).
> - Before it:
>   - `39212e3` imported and optimised the **real timetables of all six departments** (CSE, IT, ME, CE, ECE, EE)
>   - `32f1b45` added College rules
>   - `becb48e` added the lab-pair rule
>   - `3acc154` imported D4's open elective from the FET *groups* page
> - **All 123 tests pass** on `2ac1a85`.

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

**TimeWeave** is a web app for a whole college's **time and space**. It runs on **GNDEC Ludhiana's real timetables of all six departments** (CSE, IT, ME, CE, ECE, EE): 2,579 weekly classes, imported from the FET pages each department publishes. First-year students see the classes other departments teach them. It is built to work for any college through a college profile plus importers.

What it does:

| Area | What it does |
|---|---|
| **Clash-free timetables** | Generates timetables with Google OR-Tools **CP-SAT**. Every timetable (generated, imported, optimised or edited) is checked by an **independent validator** that shares no code with the solver. |
| **Optimised real timetables, every department** | Re-optimises each department's own timetable. It keeps the same lessons, teachers, groups and rooms, changes only the times, is never worse than the college's version on any measure, and **adds no clash anywhere in the college** (teachers and rooms are shared between departments). Each department proposes its own; the timetable office publishes. |
| **College rules** | Each college writes down its own timetable habits (e.g. "a teacher's lab for two groups goes on two days", "nothing after JPAL", "a real class every working day") in a JSON file. The optimiser obeys them, an independent checker counts every break, and publishing is refused if a rule is broken more often than in the college's own timetable. |
| **Real students** | Models students as real **combinations of choices** ("student types", built from CSE's elective distribution lists; elsewhere one per lab group, guarded against electives that may share students), so no real student ever gets two classes at once. |
| **Everyday campus problems** | Free rooms to sit in (by building and floor), find a teacher's free slots and request a meeting, Now/Next card, leave with ranked substitutes, venue booking with approvals, an event slot finder for a whole batch. |
| **Roles** | 8 roles with sign-in, a server-side permission table (deny by default) and an audit log. |
| **AI assistant** | A read-only Claude assistant answering timetable questions from live data through 5 tools. It can never change anything. |

**Stack:**
- **Backend:** Python 3.12+, FastAPI, OR-Tools CP-SAT.
- **Frontend:** plain HTML with Tailwind and Alpine.js from a CDN. No build step; mobile-first.
- **State:** in memory, persisted to JSON files.
- **Chatbot:** Anthropic SDK, model `claude-opus-5-5` at low effort.

**Live demo:** https://timeweave-3y2g.onrender.com (Render, free tier; see §14.1).

**Tests:** **123 automated tests, all 123 pass** (commit `2ac1a85`; see [11](#11-testing-every-test-and-the-edge-case-it-covers)).

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
   │                     leave + substitutions, compare/{dept} + propose/publish, students, chat, audit   Lane A
   ├─ /api/dash/*        dashboards: views, teacher free slots, meetings, now/next              Lane B
   └─ /api/venues/*      venue ranking, booking requests + approvals, event slot finder        Lane C
        │
   app/auth.py      PERMISSIONS table (deny by default) + capabilities + audit
   app/store.py     STORE: the one shared state; effective(date) = base ⊕ that date's overrides
   app/solver.py    CP-SAT generator (for colleges without a timetable; tested on a synthetic college) + prechecks
   app/validator.py independent checker (no OR-Tools import) + quality metrics
   app/optimise.py  re-optimises each department's REAL timetable (never worse, no new clash in the college)
   app/rules.py     college rules (data/gndec/rules.json): who stays put, labs apart, nothing after JPAL,
                    a real class daily; counts every break (no solver code), also turned into optimiser constraints
   app/importers/   fet.py (CSE's FET pages → model), fet_dept.py (every other department's FET pages),
                    gndec_students.py (distribution lists → student types)
   app/seed.py      build_college(): merges the six departments into one college (+ central halls)
   app/substitutions.py  leave → ranked substitutes
   app/venues/      ranking.py, requests.py (approval chain), slots.py (slot finder), common.py
   app/chat.py      read-only Claude assistant (5 tools)
Storage: data/solution.json (base timetable), data/gndec/<dept>.json (imported), <dept>_optimised.json,
         rules.json, students.json,
         data/state.json (overrides, requests, notifications, audit; runtime only, git-ignored)
```

### 3.2 How a timetable is made and trusted
```
FET pages of 6 departments ──► fet.py (CSE) + fet_dept.py (IT, ME, CE, ECE, EE)
                                   │  real lessons + placements (fixed)
Distribution lists (CSE) ──► student types        seed.py: central halls only
                                   │
              build_college(): ONE college (shared classrooms, a class listed twice kept once,
                               one person with two records merged, first year linked across
                               departments, other-department hours as placeholders)
                                   │
              INDEPENDENT VALIDATOR ──► clashes + quality notes + metrics (whole college)
              COLLEGE RULES CHECK (app/rules.py) ──► how often each of the college's own rules is broken
                                   │
              per department: optimiser (same lessons, new times; rules; never worse;
                              no new clash anywhere in the college) → propose → publish
                                   │
   (a college without a timetable: prechecks → CP-SAT generator → the same validator)
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
- **Section** and its **groups**. `Section.kind` is `section`, or `elective` for an audience that mixes students of several sections (electives, minor courses, other departments' first years).
- **Lesson:** a teaching assignment (subject + teacher + co-teachers + groups + sessions per week + duration + room kind). `fixed=True` means it was imported, and the generator never moves it.
- **Entry:** a placed session.
- **StudentType:** a real combination of choices and the exact lessons it attends. It also has `guards`: electives of the same year that may share its students. The validator and optimiser never put its classes at the same time as a guard.
- **Override:** a one-date change: cancel, substitute, room change, booking or leave.
- **Requests and people:** `User`, `Club`, `BookingRequest` + `ApprovalStep`, `MeetingRequest`, `Notification`.
- **Occupancy:** what happens in a room for a block of periods on one day. This is what `week()` and `effective()` return.
- **College.rules:** the college's own timetable rules, loaded from `data/gndec/rules.json` by `app/rules.py` (see [6.3b](#63b-college-rules-apprulespy-datagndecrulesjson)).

---

## 4. Real GNDEC data

### 4.1 Source
- **Timetables:** the **Jul–Dec 2026** timetables of all six departments, each generated by the department with **FET** (free desktop timetabling software) and published on its website.
  - CSE (w.e.f. 19/08/2026): cse.gndec.ac.in
  - IT, ME, CE, ECE, EE: it/me/ce/ece/ee.gndec.ac.in/?q=node/5 (URLs as given by Lane A)
- **Raw copies** (committed): every department has a rooms page (one table per room), a groups page (one table per group) and a teachers page.
  - CSE: `data/gndec/raw/`
  - the others: `data/gndec/raw/<dept>/`
- **Importers:**
  - `app/importers/fet.py` turns CSE's pages into `data/gndec/cse.json`
  - `app/importers/fet_dept.py` turns the other five into `data/gndec/<dept>.json` (see 4.4)
- **Elective distribution lists:** for 3rd year (2024–2028 batch) and 4th year (2023–2027 batch). They contain student names and roll numbers, so they stay in the git-ignored `data/private/`. Only **anonymous combinations with counts** are written to `data/gndec/students.json`, and a test checks that no 7-digit roll numbers leak into it.

### 4.2 CSE in detail (`data/gndec/cse.json`, measured 26 Oct)
| Item | Count |
|---|---|
| Rooms | 41 (includes one placeholder, "APPLIED SCIENCES", for the open elective taught in another department) |
| Teachers | 63 (incl. Applied Sciences and other-department teachers who teach CSE classes) |
| Sections | 26: D1–D3 CS A–F, D4 CS A–E, M1-CS, M3-CS, PHD-CS |
| Lessons | 318 in the file (320 after Elective-IV labs are split per lab group) |
| Placed weekly sessions | 537 |
| Lab sessions | 146 (all 2-period blocks) |
| Lessons with 2–3 teachers (co-taught) | 47 (labs mostly; measured before the six-department merge) |

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
- **Other sections:** D1, D2, M.Tech and PhD get one student type per group, because there the groups really are lab groups. CSE has **132 student types** in all.
- **Other departments** have no distribution lists, so they get one student type per lab group. Each type has `guards`: electives of the same year that may share its students, which are never put at the same time as its classes. The whole college has **241 student types**: CSE 132, IT 31, ME 25, ECE 22, CE 17, EE 14; 39 of them have guards.
- **Elective-IV labs per lab group** (commit `81eba30`): Soft Computing and ACC labs run twice a week, but FET lists both sessions under one activity. A student confirmed which is which: the A1 groups go on **Thursday** and the A2 groups on **Friday**. The importer splits them into "SC Lab A1" / "SC Lab A2", so each student sees only their own lab.

### 4.4 The other five departments: IT, ME, CE, ECE, EE (commit `39212e3`)
**Why:** the point of TimeWeave is optimising the *college's* timetables, so every branch, not only CSE (the project owner's words, via Lane A).

**One tolerant reader** (`app/importers/fet_dept.py`). The departments use different FET versions and settings, so it accepts:
- the room or group name in the table caption, or in the first header cell
- times as "08:30-09:30", "8:30", "8.30 AM (1ST)" or 12-hour "01:30-02:30"
- days written "Monday" or M/T/W/TH/F
- cells as `<br>`-separated lines (older FET) or labelled spans/divs (newer FET)
- combined cells listing parallel labs
- 2-hour labs written as one tall cell or as two rows
- group names like "D2IT_C1", "D2A" (EE) or "D2 CE B2"

Two more import rules:
- **Elective audiences:** names that don't follow the department's section pattern (electives such as "D4E.1", minor courses such as "D2CEMC1") become `elective` audiences. Other departments' first years used to land here too; since `53e1f7f` they are linked to their real sections (see 4.5).
- **Other departments' rooms:** hours a group spends there (seen only on the groups page) become fixed placeholders in room `OTHER DEPARTMENT`, so nothing is ever moved onto them. That room is never shown as free or as a venue.

**Teacher names:**
- Full names come from each department's teachers page, because cells often show only initials.
- CE publishes initials only, so **35 of the 203 real teachers** keep a name like "CE teacher (HVS)".
- **People with the same name are kept apart:** records that are both on a department's own teacher list are never merged (`89254d8`). ECE has a Dr. and a Pf. Harminder Kaur, who are different people.
- **One person written two ways is merged:** a teacher written by full name in one cell is merged with their own-list record (e.g. ME-DRHARPUN → ME-HPS, `dce71d3`).

**What was imported** (`data/gndec/<dept>.json`; lessons and sessions as used in the merged college):

| Department | Lessons | Weekly sessions | Rooms in its export | Teachers in its export | Group audiences in its export |
|---|---|---|---|---|---|
| CSE | 320 | 537 | 41 | 63 | 26 |
| IT | 344 | 454 | 18 | 38 | 31 |
| ME | 449 | 553 | 44 | 57 | 64 |
| CE | 272 | 396 | 49 | 52 | 56 |
| ECE | 278 | 359 | 37 | 42 | 37 |
| EE | 202 | 280 | 32 | 54 | 66 |
| **College** | **1,865** | **2,579** | 153 rooms in the merged college | **203** real teachers (286 teacher records incl. 83 placeholders) | 231 audiences: 68 real sections + 163 elective audiences |

ECE and EE shrank in `53e1f7f`, when first year was linked across departments. Classes written in two departments' timetables are now kept once, and placeholders are dropped where a linked class shows what really happens.

**One college** (`seed.build_college()`):
- **Shared classrooms:** numbered classrooms are one room across departments (IT's and CE's "S-213" is CSE's S213).
- **Separate labs:** labs and halls with the same name stay separate ("DBMS LAB" of CSE vs IT's "DBMSLAB").
- **A class listed by two departments is kept once:** e.g. CSE's ERP, taught by an ME teacher, appears in both exports.
- **One person with two records is merged:** named in full by one department and by initials in their own.
- **Every class in the college now comes from a real published timetable;** nothing is generated.
- **Rooms still from the synthetic seed:** the Auditorium (600), the MBA Seminar Hall, lecture theatres LT-1/LT-2 (bookable), and a library reading room. No class uses them. The real WS Seminar Hall comes from CSE's export.

**Merged college** (measured 26 Oct):

| Item | Count |
|---|---|
| Departments | 6 + Applied Sciences (teachers only) |
| Rooms | 153 (71 classrooms, 53 department labs, 13 computer labs, 6 seminar halls, …; only numbered classrooms are offered to sit in or book (`d3e1a9d`): 64 sittable, 77 bookable) |
| Teachers | **203 real people** (CSE 44, ME 41, IT 28, EE 27, CE 25, ECE 24, Applied Sciences 14), plus 83 placeholder records (`TBA-…`: "Taught in another department", "Major Project (staff)", "JPAL (staff)", open electives taught elsewhere) that hold fixed hours but are not people |
| Real sections / their lab groups | 68 / 197 |
| Lessons | 1,865, all imported |
| Weekly sessions | **2,579** |
| Student types | 241 (CSE 132, IT 31, ME 25, ECE 22, CE 17, EE 14; 39 with guards) |
| Demo accounts | 464 |
| Teacher lab pairs (`lab_pairs()`) | 169 |

**The published data has errors of its own.** Put together, the six published timetables have:
- **0** student double-bookings and **0** room double-bookings
- **5 teacher double-bookings** (the validator's whole-college count since `89254d8`)

Of the 5:
- **4 are combined classes listed by two departments:** CSE's and ME's M.Tech students taught together by one teacher; both departments list the class, each with its own room.
- **1 is one CE teacher** double-booked inside CE's own export.

How the count came down:
- **32 → 12:** linking first year across departments (`53e1f7f`) counted classes written in two timetables only once.
- **12 → 5:** a merge fix (`89254d8`). ECE has two different teachers called Harminder Kaur (a Dr. and a Pf., with different initials). The "one person, two records" merge ignored titles and joined them, which created 7 false clashes. Records that are both on a department's own teacher list are now never merged.

**What `/api/timetable` reports** (since `89254d8`):
- `issues`: only clashes TimeWeave itself would cause. It is empty.
- `published_issues`: the 5 above, which are in the college's own data.
- `status`: "IMPORTED", because every department is real. The old generated demo's `baseline`, `objective`, `seconds` and `compare` are no longer sent.

TimeWeave never makes this worse: no optimised department may add a clash anywhere in the college, and a test checks that for every department.

### 4.5 First year linked across departments (commit `53e1f7f`)
**The problem:** first-year students are taught by several departments:
- ME: workshop and drawing
- ECE and EE: BEEE
- their own department: PPS etc.

Each department's timetable names the groups its own way:
- "D1 CS A" (CSE)
- "D1IT_A" (IT)
- "D1 CE A1" (in ME's timetable)
- "D1CSA1" / "D1ITA" (in EE's and ECE's)

So a CSE first-year student's timetable was missing the classes ECE, EE and ME teach them.

**The fix** (`seed._link_first_year`):
- **Linking:** every group name that says D1 is linked to the owning department's section and lab group.
- **Left alone:** ME's "CSE A" … "CSE F" (one subject, "EP&S", no year written) are left as they are rather than guessed. A test checks that.

**Duplicates removed at the same time:**
- **One class in two timetables** (same teacher, same students, same time) is kept once.
- **"Taught in another department" placeholders** now count only for the students' own department, and only where no linked class shows what actually happens.

**Results** (checked here):
- **94 first-year sessions** taught by ME (23), ECE (22) and EE (49) now appear in those students' own timetables.
- **Example:** CSE D1 A, lab group A1, goes from **5 to 11 hours** a week of classes (ECE's BEEE lectures and lab now show). Verified on the previous and the current commit.
- **Clashes:** still **0 student clashes** college-wide; **teacher clashes 32 → 12** (and 12 → 5 after the merge fix in `89254d8`; see 4.4).
- **Optimised timetables:** the optimised timetables were refreshed for the changed fixed classes (`optimise.refresh_pins`), without a re-solve. Moved counts and run times are the same. Measured on the refreshed files, IT's, ECE's and EE's numbers changed slightly; §10.3 shows the current values.

**Still missing:** Applied Sciences (maths, physics, chemistry, English) doesn't publish a timetable, so those hours are missing for every first-year group (see §16).

---

## 5. Feature list (everything built)
Status as of commit `53e1f7f`. ✅ built and committed · ⬜ designed, not built.

### 5.1 Core and data (Lane A)
| # | Feature | Status |
|---|---|---|
| A1 | Synthetic GNDEC-style college (buildings, floors, room features, sittable/bookable flags), used to test the generator and for central halls | ✅ |
| A2 | CP-SAT generator with hard rules and soft goals; plain-English prechecks for impossible inputs (for colleges without a timetable; the live GNDEC college is fully imported) | ✅ |
| A3 | Flexible lunch: a free hour anywhere in 11:30–14:30 per batch and teacher | ✅ |
| A4 | Independent validator: hard clashes vs quality notes, and quality metrics | ✅ |
| A5 | FET importer for GNDEC's real CSE timetable (rooms page), re-checked by the validator | ✅ |
| A5b | FET groups page: open elective OE-II and a two-room class | ✅ |
| A5c | **All six departments:** tolerant FET reader for IT, ME, CE, ECE, EE (`fet_dept.py`), full teacher names from teachers pages, merged into one college (shared classrooms, duplicates kept once, people merged, other-department hours as placeholders) | ✅ |
| A5d | **First year linked across departments:** every "D1…" group name in another department's timetable is linked to the owning section and lab group, so first-year students see the ME, ECE and EE classes they take (94 sessions); duplicates removed; teacher clashes in the published data 32 → 12 | ✅ |
| A6 | Student types from the elective distribution lists (privacy-safe) | ✅ |
| A7 | Elective-IV labs split per lab group (A1 Thursday, A2 Friday) | ✅ |
| A8 | Shared store: `effective(date)` = base ⊕ that date's overrides (cancel / substitute / room change / booking / leave) | ✅ |
| A9 | Free-room finder: by day or real date, building, floor, sittable-only, capacity; "free until"; booking-aware | ✅ |
| A10 | Leave and ranked substitutes, with notifications to the substitute, the absent teacher and the students | ✅ |
| A11 | Optimiser for each department's real timetable: same lessons, never worse, no new clash anywhere in the college, large-neighbourhood search | ✅ |
| A11b | Rule: a teacher's lab for two groups of one class stays on two different days (e.g. SC Lab A1 / A2); `lab_same_day` metric; card on the compare page | ✅ |
| A11c | **College rules:** 10 GNDEC rules in `data/gndec/rules.json` (5 rule types, must/prefer); the optimiser obeys them; an independent checker counts breaks; "GNDEC's timetable rules" section on the compare page; publishing refused if a rule is broken more often than in the college's timetable | ✅ |
| A12 | Propose (department) → publish / unpublish (timetable office), **per department**; publishing re-validates the whole college and is refused if it adds a clash | ✅ |
| A13 | Sign-in (session cookie; demo sign-in with **four roles**: Student, Teacher, HOD, Timetable office, with club lead / coordinator / Dean / T&P / visitor as extra duties inside them; students choose department → year → section → their group and subjects, `84f400e`), 8 permission roles, PERMISSIONS table, capabilities, audit log | ✅ |
| A14 | In-app notifications (🔔 in the shared top bar) | ✅ |
| A15 | Read-only Claude assistant with 5 date-aware tools; tools tested on the real data without calling the API (`dce71d3`) | ✅ |
| A16 | Pages: sign-in, compare (college vs optimised, with a **department picker**: HODs see their own department, the Dean sees all), audit log; shared top bar | ✅ |
| A17 | Demo reset (admin) | ✅ |
| A18 | **Deployed** at https://timeweave-3y2g.onrender.com (Render, Docker). Hosted mode switches off the paid AI assistant and optimiser re-runs, with a friendly message, and hides their buttons via `TW.can` (`5a6a9bc`, `2ac1a85`) | ✅ |

### 5.2 Dashboards (Lane B, `index.html`, `/api/dash`)
| # | Feature | Status |
|---|---|---|
| B1 | Role-aware home: students see their student type, teachers their week, HOD/coordinator/Dean/admin a department | ✅ |
| B2 | Timetable views by department → year → section → student (group + electives), teacher, room; weekly, one date, or a dated week. Pickers list real sections only (no elective audiences) and no "Other department" placeholder rooms (`e2795e7`) | ✅ |
| B3 | Find a teacher: day view with each period's state (teaching / free / unavailable / leave / meeting) | ✅ |
| B4 | Meeting requests: students ask for a free period, the teacher accepts or declines, both are notified | ✅ |
| B5 | Now / Next / next-free card | ✅ |
| B6 | Free rooms by building and floor, "near me", "Right now" | ✅ |
| B7 | Mark leave (teacher for themself; HOD/coordinator/admin for their department) | ✅ |
| B8 | Substitutions board: next 6 school days, state chips, ranked candidates with reasons, Assign, Cancel class | ✅ |
| B9 | Substituted classes marked in timetables and Now/Next (names both teachers) | ✅ |
| B10 | Honest numbers (`6c59dbc`): the validator card counts only TimeWeave's own clashes (0); the college's published clashes are shown separately to staff; a Data card instead of a solver card for imported timetables. Panel comparing the real and generated timetables, shown only when some departments are generated. Since `dee7b1e` / `cabdf9e` every department is real, so the page shows the data source and a link to the optimised timetables instead, and no Generate button; a timetable-issues badge for staff only, worded as teacher double-bookings in the published data (`286e3f8`); teacher-load bars; classroom and lab use | ✅ |
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
| C8 | All-department data: elective audiences and student types also rule slots out (an elective class blocks the whole year's sections); dept + year counts only real sections; the "Other department" placeholder is never a venue (`49004bb`) | ✅ |

---

## 6. How the main parts work

### 6.1 CP-SAT generator (`app/solver.py`)
**Role today:** builds a timetable from scratch for a college that has none. GNDEC's live college is now fully imported, so there is nothing left to generate there:
- `POST /api/generate` answers 409, "Every department's timetable is imported … nothing to generate", since `dee7b1e`
- `python -m app.solver` demonstrates generation on the fully synthetic college (`seed._build_seed`), which is also what the tests use

**Variables:** one boolean `x[session, day, start, room]` for every valid start of every session that can move. Imported (fixed) lessons stay where they are.

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

**Guards:** a student type's class may never be at the same time as one of its `guards` (an elective of the same year that may share its students, in departments without elective lists). Such a clash is reported as `CLASH Students … (elective that may share students)`. Guards never conflict with each other.

**Placeholders:** the `OTHER DEPARTMENT` placeholder room stands for many real rooms, so it never counts as a room double-booking.

**Metrics:**

| Group | Metrics |
|---|---|
| Students | idle periods (total, per day, worst gap), single-lecture days, days with no lunch, days over 6 periods |
| Teachers | streak days (4+ in a row), no-lunch days, idle periods, load |
| Rooms and late classes | late sessions (P9), classroom and lab utilisation |
| Lab pairs | `lab_same_day`: how often a teacher's lab for two groups of one class falls on the same day |

### 6.3 Optimising each department's real timetable (`app/optimise.py`, page `/compare.html`)
- **One department at a time:** CSE, IT, ME, CE, ECE or EE, from the page or the CLI (`python -m app.optimise <seconds> IT ME`, or `ALL`). The result goes to `data/gndec/<dept>_optimised.json`.
- **The rest of the college stays fixed:** every other department's classes count as fixed for shared teachers and rooms.

**Kept exactly as the college decided:**
- every lesson's teacher(s), including co-teachers
- groups, including cross-section electives and A1/A2 lab groups
- weekly hours and durations (2-hour labs)
- the kind of room

**What changes:** only *when* each session happens, and which room of the right kind it uses. Rooms come only from those the college already uses for these classes, so the comparison is fair.

**Pinned (never moved):** this comes from the college's `keep_as_published` rules (see 6.3b), not hard-coded checks. Classes in the `OTHER DEPARTMENT` placeholder are also pinned.
- first year (taught by several departments: ME workshop/drawing, Applied Sciences)
- mentoring (MC)
- M.Tech, PhD and other programmes
- classes run with other departments (teacher `TBA-…`: open electives, JPAL)
- classes taught by **another department's teacher**
- in IT, ME, CE, ECE and EE, which have no elective lists:
  - **electives and minor courses**
  - **3rd/4th-year group classes**

  (2nd-year and whole-section classes move.)

Pinned sessions occupy teachers, groups and rooms as constants.

**Why so much is pinned:** without elective lists we can't tell which students sit in which elective or group class. Keeping those classes as published is the safe choice: it guarantees no real student gets a new clash. It also means less can move, so the gains are smaller than they could be with full lists (see §10.3).

**No new clash anywhere in the college:** a department's optimised timetable, dropped into the whole college, may not create any clash the published timetables don't already have. A test checks this for all six departments.

**Lab pairs on different days** (commit `becb48e`; a student reported it):
- **The problem:** in an earlier optimised run, Soft Computing lab A1 and A2 were both on Friday with the same teacher.
- **Lab pairs:** `College.lab_pairs()` in `app/models.py` finds pairs of labs one teacher gives to two groups of the same class, e.g. "SC Lab A1" / "SC Lab A2", or D2 CS B's OOP Lab for B1 and for B2. There are 169 pairs in the six-department college (after first-year linking), 54 of them in CSE.
- **The rule:** wherever the college already keeps a pair on different days, the optimiser forbids putting both on one day (a hard constraint). This is the college rule `labs-on-different-days`, now for every department.
- **Existing same-day pairs:** CSE itself has 12 same-day pairs (mostly 2nd year, e.g. D2 CS B's OOP lab with both groups on Friday). Those may stay, so the college's own timetable is still a valid starting point.
- **Result for CSE** (final run, `39212e3`):
  - SC Lab A1 Fri 10:30 and A2 Thu 10:30 (teacher DN): two different days
  - ACC Lab A1 Thu 10:30 and A2 Tue 12:30
  - same-day pairs: CSE 12 → 11, IT 7 → 4, CE 2 → 2, EE 1 → 1, ME and ECE 0 → 0

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

**Output:** `data/gndec/<dept>_optimised.json` with before/after metrics, clash counts and college-rule break counts. It is re-validated by tests. A department can re-run it from the page (`POST /api/compare/{dept}/run`, background thread, one run at a time).

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
  - a `match` that selects lessons by:
    - department(s)
    - subject code prefix
    - year
    - teacher prefix
    - "taught by another department's teacher"
    - audience (`whole` section, `subgroup` or `mixed` elective)
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

**The 10 GNDEC rules** (6 since `32f1b45`, 4 more added in `39212e3` for the other departments). Breaks per department are counted on that department's own timetable, college → optimised:

| Rule | Strength | Means | Breaks (college → optimised) |
|---|---|---|---|
| `keep-first-year` | must | First-year classes stay exactly where the college has them (taught by several departments) | 0 → 0 everywhere |
| `keep-mentoring` | must | Mentoring stays exactly where the college has it | 0 → 0 everywhere |
| `keep-postgraduate` | must | M.Tech, PhD and other programmes (Architecture, BCA, …) stay put | 0 → 0 everywhere |
| `keep-other-departments` | must | Classes run with other departments (open electives, JPAL, classes in their rooms) stay where they are | 0 → 0 everywhere |
| `keep-other-teachers` | must | Classes taught by another department's teacher stay where they are | 0 → 0 everywhere |
| `keep-electives-without-lists` | must | Electives and minor courses of IT, ME, CE, ECE and EE stay where they are | 0 → 0 everywhere |
| `keep-3rd-4th-year-groups-without-lists` | must | 3rd/4th-year group classes of IT, ME, CE, ECE and EE stay; whole-section classes may move | 0 → 0 everywhere |
| `labs-on-different-days` | must | A teacher's lab for two groups of one class is on two different days | CSE 12 → **11**, IT 7 → **4**, CE 2 → 2, EE 1 → 1, ME/ECE 0 → 0 |
| `nothing-after-jpal` | prefer | (CSE) No class for the whole section after JPAL that day. Only about 20 of 150 D4 students take JPAL, so a class after it makes everyone else wait. | CSE 1 → 1 (the college's own D4 CS C mentoring, Wed 3:30, which is pinned) |
| `real-class-every-day` | must | Every weekday has at least one real lecture or lab for D2–D4, not just the open elective, major project, mentoring or JPAL | CSE, IT, EE 0 → 0; **ME 9 → 9, CE 5 → 5, ECE 16 → 16** (already in the published timetables; never made worse) |

**Notes on the rules:**
- **real-class-every-day** was the project owner's own example. CSE's optimised timetable from `becb48e` broke it **6 times**: D4 student types whose Friday had only the major project and the open elective (verified here with `rules.breaks()`). Every run since breaks it 0 times in CSE.
- **ME, CE and ECE's published timetables already break it** (9, 5 and 16 times). Their optimised versions keep the same count; they don't fix it, because the classes that would fix it are pinned (no elective lists).
- **D1 is excluded** from real-class-every-day, because 1st-year subjects are taught by Applied Sciences and are not in CSE's timetable.
- **Only confirmed rules are added.** A guessed rule ("project only in the morning") was dropped, because the college itself has a project hour at Mon 3:30.

**Where the rules are used:**
- `rules.report()` gives each rule with its break counts for the college and the optimised timetable, plus up to 5 examples. It is shown on the compare page ("GNDEC's timetable rules") and saved in each `<dept>_optimised.json`.
- **Publishing is refused (409)** if any rule is broken more often than in the college's own timetable, or if publishing would add a clash anywhere in the college.
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
- **Audience:** dept + year (real sections only), sections, or groups. A class blocks a group if the group or its section is in the class's batches.
- **Electives** (`49004bb`): elective audiences mix students of several sections, so a class of an elective of the same year also rules a slot out, and "nearly free" names the elective as the reason.
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

**Tested without spending API credit** (`dce71d3`): `tests/test_core_chat_tools.py` calls every tool directly on the real data. Days accept "Mon" or "Monday". Room search understands other departments' spellings ("S-213" = S213) and never offers the stand-in rooms.

---

## 7. Roles, sign-in and permissions

### 7.1 Sign-in
- **Session:** a signed session cookie `tw_session` (Starlette SessionMiddleware, 7 days), set by `/login.html`.
- **Demo mode** (`TIMEWEAVE_DEMO=1`, the default):
  - anyone can sign in as any demo account without a password
  - API clients and tests may send `X-User: <account id>`
- **No sign-in → 401** on every `/api/*` route except `/api/auth/*`. There is no default account.
- **The sign-in page shows four roles** (first grouped in `39212e3`, redesigned at the project owner's request in `84f400e`):

| Role on the sign-in page | Who | Extra duties inside it |
|---|---|---|
| Student | students | club lead (quick links under the student form) |
| Teacher | teachers | timetable coordinator |
| HOD | HODs | |
| Timetable office | the timetable office (admin) | the Dean, the T&P cell, visiting organisations |

  - **Permissions are unchanged:** the 8 roles of §7.2 still exist in `app/auth.py`. The page only groups them.
  - **The top bar** shows "<name> · Switch" in demo mode, a button that opens this four-role sign-in page (`958cd5d`; it used to be a dropdown of about 550 accounts).
  - **Teachers, HODs and the timetable office** search a list by name or department.
- **Student sign-in flow** (`84f400e`):
  1. Choose **department → year** (1st–4th, M.Tech, PhD) **→ section**.
  2. "Your group and subjects" appear as dropdowns:
     - **for CSE D4 sections:** actual group, Elective-III, Elective-IV (with its lab group) and Technical Aptitude lab
     - **for sections without distribution lists:** just the lab group
  3. The dropdowns are **pre-filled with the most common combination** in that section.
  4. Each dropdown offers **only choices that really exist together with the ones above it**. Changing one keeps the others valid, again preferring the most common combination.
  5. **"Show my timetable"** signs in as that student type and opens its exact timetable.

  Example (checked in the browser by Lane A): CSE → 4th year → D4 CS A → A2, CV, SC (A1 group), TA A3 signs in as `D4-CS-A:A2:CV:SCA1:TA3`.
- **API:** `GET /api/auth/demo-accounts` now also gives each student account its `year`, `section_name`, `details` (their choices) and `count` (how many students share that combination).
- **Demo accounts (464):**

| Role | Accounts | Notes |
|---|---|---|
| student | 241 | one per student type |
| teacher | 203 | every real teacher of the six departments + Applied Sciences; placeholder "teachers" get no account (`958cd5d`) |
| hod | 7 | one per department with teachers (incl. Applied Sciences) |
| coordinator | 6 | one per department with sections |
| club | 3 | DMC, CODE, ROBO, each with a faculty advisor |
| org | 2 | T&P cell, a visiting organisation |
| admin | 1 | |
| dean | 1 | |

### 7.2 The 8 roles and what they can do
(From `PERMISSIONS` and `capabilities()` in `app/auth.py`. The admin may do everything; anything not listed is denied. On the sign-in page these 8 appear as four roles with extra duties; see 7.1.)

| Role | Can | Cannot |
|---|---|---|
| **Student** | view timetables, My timetable (their student type), free rooms, find a teacher, request a meeting, Now/Next, ask the assistant | book venues, use the slot finder, see the optimised timetable, approve anything |
| **Teacher** | My timetable, reply to their own meeting requests, mark their own leave, request venues (no advisor step), slot finder, cancel own bookings | mark a colleague's leave, change classes, approve venues |
| **Coordinator** (department timetable) | everything for **their own** department: substitutions (`override.create`), mark leave for department teachers, view / re-run / **propose** their department's optimised timetable, insights; books like a teacher | approve venues, publish, see or act on other departments |
| **HOD** | same as the coordinator, plus **approve bookings of rooms their department owns** | publish, regenerate, approve central halls, act on other departments |
| **Dean** (read-only) | every department's timetable, **every department's** optimised view, insights, leave board, **audit log**, slot finder | change anything: propose, override, publish, book, request meetings |
| **Club lead** | request venues (goes to the faculty advisor first), slot finder, cancel own requests | endorse or approve its own request |
| **Org** (visitor / T&P) | request venues (no advisor step), slot finder, book for a batch audience | approve |
| **Admin** (timetable office) | everything: **regenerate**, **publish/unpublish**, approve **central halls**, see all accounts, demo reset, audit log | (none) |

- **Faculty advisor** is not a role: it is a teacher named as a club's advisor (`booking.endorse`).
- **Who approves a booking** depends on the room: its owning department's HOD, or the admin for central rooms.

### 7.3 Propose → publish flow (per department)
1. A department's HOD or coordinator opens `/compare.html` and picks their department; they can see only their own. They compare the two timetables and press **Propose to the timetable office**. Status → `proposed`; admins are notified.
2. The admin presses **Publish to everyone**:
   - It is refused (409) if the optimised version has more clashes than the department's published one ("no new clashes").
   - It is refused (409) if it breaks any college rule more often than the college's own timetable does; the message names the rule.
   - After installing it, the **independent validator re-checks the whole college**. If the college now has more clashes than before, publishing is undone (409).
   - Every student and teacher of that department is notified.
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
| `/login.html` | everyone | Demo sign-in ("no password, for judging") with four roles: Student, Teacher, HOD, Timetable office. Extra duties (club lead, coordinator, Dean, T&P, visitor) are shown next to names. Students choose department → year → section → group and subjects (pre-filled, only real combinations) → **Show my timetable**; club leads have quick links. Others search by name or department. |
| `/` (`index.html`, Lane B) | everyone signed in | **Timetable** tab: views and filters, week / dated week, Print / Save PDF. When every department is imported (today), it shows the data source and **"See the optimised timetables →"** instead of the real-vs-generated panel and the **Regenerate** button (`cabdf9e`); both appear only for a college with generated departments. **Find a teacher** (`#teacher`): day view, Request meeting. **Free rooms** (`#rooms`): Right now, building/floor, near me. **Meetings** (`#meetings`). **Substitutions** (`#subs`): leave board, candidates, Assign, Cancel class. **Teacher load** (`#load`). **Ask** (`#ask`, chatbot). **Mark leave**. **Now/Next** card. Phone layout with day tabs. |
| `/venues.html` (Lane C) | staff, clubs, orgs (by capability) | `#book` Book a venue (requirement form → ranked venues → request), `#requests` My requests with timeline, `#inbox` Approvals (endorse/approve/reject), `#slots` Event slot finder ("Find common free time", "Nearly free", "Book this") |
| `/compare.html` (Lane A; "Optimised timetables" in the top bar) | each department's HOD/coordinator (their own department), Dean and admin (all six) | **Department picker**; college vs optimised timetable by section, student (group and electives) or teacher; before/after numbers (incl. "Same lab for two groups on one day"); **"GNDEC's timetable rules"**: each rule in plain words, must/prefer, and how often each version breaks it; Propose / Publish / Go back |
| `/audit.html` (Lane A) | admin, Dean | Audit log, newest first |
| Shared top bar (`shell.js`) | every page | Logo, navigation (hides what you can't use), "<name> · Switch" (demo mode; opens the sign-in page, `958cd5d`), 🔔 notifications |

---

## 9. API summary
Full contract: `docs/API.md`. The app has **40 API routes**:

| Group | Routes | Paths |
|---|---|---|
| Auth (`/api/auth/*`) | 3 | demo-accounts (students with year, section name, choices and count), demo-login, logout |
| Core (`/api/*`) | 23 | meta, me, users, audit, timetable, effective, generate, free-rooms, notifications (+read), demo/reset, chat, leave (POST/GET), substitutions, **compare** (departments I may compare), **compare/{dept}** (+run, propose, publish, unpublish), students/types, students/{type}/timetable |
| Dashboards (`/api/dash/*`) | 7 | ping, views, teacher/{id}/free, meetings (POST/GET), meetings/{id}/reply, now |
| Venues (`/api/venues/*`) | 7 | list, rank, requests (POST/GET), requests/{id}/decide, requests/{id}/cancel, slot-finder |

Errors are always `{"detail": "plain-English message"}` with status 400, 401, 403, 404 or 409.

---

## 10. Results and numbers

### 10.1 The generator (synthetic college)
The live GNDEC college is now fully imported, so the generator has nothing to place there. These numbers come from the stage when CSE was real and the other departments were generated:
- the generator's saved result in `data/solution.json` (status FEASIBLE, 45.9 s; since `89254d8` the live app no longer reports these old solver fields), and
- the Day 1 progress report.

The generator itself is still tested on the fully synthetic college (§11.2).

Generated part, first feasible solution ("baseline") vs optimised:

| Measure | Baseline | Optimised |
|---|---|---|
| Idle periods per student-group day | 1.34 | **0.00** |
| Idle periods (total) | 214 | **0** |
| Single-lecture days | 5 | **0** |
| Days with no lunch break | 0 | 0 |
| Days over 6 periods | 0 | 0 |

(Day 1, before the real CSE import, the progress report showed **1.2 → 0.07** idle periods per day for 394 sessions in 20 sections.)

### 10.2 GNDEC's six published timetables, put together
Measured by the independent validator on the merged college: 2,579 weekly sessions, with first year linked (`53e1f7f`).

| Measure | Whole college as published |
|---|---|
| Student double-bookings | **0** |
| Room double-bookings | **0** |
| Teacher double-bookings | **5**: 4 combined CSE/ME M.Tech classes listed by both departments, 1 in CE's own export (was 32, then 12; see 4.4) |
| Student waiting periods per week (per student type) | 339 |
| Student-type days with **no free hour 11:30–2:30** | **44** (all in CSE) |
| Student-type days **over 6 periods** | 463 |
| Teacher waiting periods per week | 1,011 |
| Teacher days with 4+ lectures in a row | 88 |
| Teacher days with no free hour 11:30–2:30 | 60 |
| Same lab for two groups on one day | 22 |
| Classes in the 4:30–5:30 slot | 7 |

### 10.3 Optimised timetables, every department (same lessons, better times)
**Final result:**
- **Runs:** from `39212e3`; files refreshed for the linked first year in `53e1f7f`, and ECE's re-measured after the merge fix in `89254d8` (`data/gndec/<dept>_optimised.json`). Every run status IMPROVED.
- **Set-up:** each department is optimised with the rest of the college fixed, with all 10 college rules.
- **Clashes:** every optimised department adds **0 new clashes anywhere in the college** (tested).

| Dept | Run | Moved / pinned | Student waiting / week | Teacher waiting / week | Teacher 4+-in-a-row days | Teacher no-break days | Group-days over 6 | Same-day lab pairs |
|---|---|---|---|---|---|---|---|---|
| CSE | 596 s | 174 / 177 | 181 → **153** | 314 → **200** | 5 → 5 | 5 → **1** | 280 → **245** | 12 → 11 |
| IT | 236 s | 94 / 306 | 15 → **11** | 151 → **96** | 30 → **21** | 15 → **13** | 103 → 103 | 7 → **4** |
| ME | 235 s | 68 / 460 | 21 → **18** | 172 → **118** | 23 → **21** | 16 → 16 | 33 → 33 | 0 → 0 |
| CE | 236 s | 83 / 289 | 6 → 6 | 136 → **72** | 8 → 8 | 5 → 5 | 39 → **33** | 2 → 2 |
| ECE | 235 s | 67 / 275 | 15 → **0** | 105 → **52** | 15 → 15 | 17 → **16** | 6 → **3** | 0 → 0 |
| EE | 238 s | 83 / 184 | 25 → **0** | 129 → **62** | 6 → **0** | 2 → **1** | 2 → 2 | 1 → 1 |
| **All six** | | **569 moved** | **263 → 188** (−29%) | **1,007 → 600** (−40%) | 87 → 70 | 60 → 52 | 463 → 419 | 22 → 18 |

The "All six" row is the sum of the department rows; each department is measured on its own classes. The whole-college figures in §10.2 count all of a student's or teacher's classes together, across departments. That explains why §10.2 shows:
- 339 student waiting periods (first-year students have classes from several departments)
- 1,011 teacher waiting periods
- 88 streak days

**Values changed since the first runs:**
- **First-year refresh** (`53e1f7f`):
  - IT student waiting periods (was 18 → 14)
  - ECE pinned / teacher numbers (was 286 pinned, 98 → 45, 19 → 18, 21 → 20)
  - EE pinned / teacher numbers (was 248 pinned, 137 → 70, 9 → 3, 4 → 3)
- **Merge fix** (`89254d8`): with the two Harminder Kaurs now separate, ECE's teacher numbers are 105 → 52 waiting periods (was 99 → 46), 15 → 15 streak days (was 17 → 16) and 17 → 16 no-break days (was 19 → 18).

The moved counts are unchanged. The table above is what the current files contain.

**More facts:**
- **CSE students:** days with no free hour 11:30–2:30 go **44 → 0**. No other department has any (0 → 0).
- **Single-lecture days:** unchanged in every department (CSE 11, IT 7, ME 12, CE 9, ECE 4, EE 0).
- **Classes after 4:30:** CSE 7 → 7 (pinned mentoring); 0 elsewhere.
- **Clashes inside a department's own timetable** (department-only check):
  - CE: 1 → **0** (the teacher CE's export double-books)
  - CSE, IT, ME, ECE, EE: 0 → 0. ECE showed 7 → 6 until `89254d8`; those were the false clashes from merging two different teachers named Harminder Kaur.

**Honest note on CSE (the numbers went down from the previous run):**
- **Previous run** (`32f1b45`, CSE alone): student waiting periods 181 → **75**, teacher waiting periods 314 → 100.
- **This run:** 181 → **153** and 314 → **200**.
- **Why:** to be safe in a six-department college, these now stay as published:
  - CSE's first year (taught by several departments)
  - classes taught by other departments' teachers
  - every other department's classes, for shared teachers and rooms

  So 177 CSE sessions are pinned instead of 69.
- **What the trade buys:** the earlier run could, in principle, have created clashes with other departments, because it didn't know their timetables. This version **guarantees** it doesn't: a test drops each optimised department into the whole college and checks that no clash appears that the published timetables don't already have.

**History of CSE runs:**
- **`aac5df1`:** waiting periods 181 → 16, measured **without** the open elective (three fixed 8:30 classes a week for all of D4).
- **`3acc154`:** put SC Lab A1 and A2 on the same day (a student reported it). The lab-pair rule (`becb48e`) fixed it: 81 / 109.
- **`becb48e`:** left 6 D4 Fridays with only project + open elective. College rules (`32f1b45`) fixed it: real-class-every-day 6 → 0, with 75 / 100.
- **`39212e3`:** six departments, safe pinning: **153 / 200**, 0 new clashes anywhere. Unchanged by the first-year refresh (`53e1f7f`).

**Publishing is guarded.** While a CSE re-run was going on, the saved optimised file briefly had 1 clash (a moved class overlapping the newly pinned OE-II), and publishing was correctly refused with 409.

---

## 11. Testing: every test and the edge case it covers

### 11.1 Totals
Commands: `.venv/Scripts/python -m pytest -q -rA` and `pytest --collect-only -q`, run 26 Oct 2026.

| Code state | Tests | Passed | Failed | Time |
|---|---|---|---|---|
| **Final: commit `2ac1a85`** | 123 | **123** | **0** | 55 s |
| Earlier: commit `d3e1a9d` (before the hosted-mode test) | 122 | 122 | 0 | 27 s |
| Earlier: commit `7a33645` (before the 4 assistant-tool tests) | 118 | 118 | 0 | 23 s |
| Earlier: commits `53e1f7f` to `89254d8` | 117 | 117 | 0 | 23–36 s |
| Earlier: commit `39212e3` (before the first-year test) | 116 | 116 | 0 | 28 s |
| Earlier: commit `32f1b45` (before the six-department and new slot-finder tests) | 95 | 95 | 0 | 58 s |
| Earlier: commit `becb48e` (before the 7 college-rules tests) | 88 | 88 | 0 | 67 s |
| Earlier: commit `3acc154` (before the lab-pair test) | 87 | 87 | 0 | 28 s |
| Earlier: commit `aac5df1` (before the 3 groups-page tests) | 84 | 84 | 0 | 64 s |

| File | Lane | Tests | Pass |
|---|---|---|---|
| `tests/test_validator.py` | A | 12 | 12 |
| `tests/test_core_permissions.py` | A | 19 (incl. 5 parametrised; 1 added in `7a33645`, 1 in `5a6a9bc`) | 19 |
| `tests/test_core_fet.py` | A | 7 (3 added in `3acc154`) | 7 |
| `tests/test_core_students.py` | A | 6 | 6 |
| `tests/test_core_store.py` | A | 4 | 4 |
| `tests/test_core_substitutions.py` | A | 4 | 4 |
| `tests/test_core_optimise.py` | A | 3 (1 added in `becb48e`) | 3 |
| `tests/test_core_rules.py` | A | 7 (added in `32f1b45`) | 7 |
| `tests/test_core_departments.py` | A | 19 (18 added in `39212e3`, incl. 5 + 6 parametrised; 1 in `53e1f7f`) | 19 |
| `tests/test_core_chat_tools.py` | A | 4 (added in `dce71d3`) | 4 |
| **Lane A total** | | **85** | **85** |
| `tests/test_dashboards_api.py` | B | **14** | 14 |
| `tests/test_venues_approvals.py` | C | 7 | 7 |
| `tests/test_venues_ranking.py` | C | 8 (incl. 4 parametrised) | 8 |
| `tests/test_venues_slots.py` | C | 9 (3 added in `49004bb`) | 9 |
| **Lane C total** | | **24** | 24 |
| **Overall** | | **123** | **123** |

**Note:** while the optimiser re-run was in progress, 2 tests failed as expected:
- `test_core_optimise.py::test_no_clashes_and_never_worse`
- `test_core_permissions.py::test_propose_publish_unpublish_keeps_zero_clashes`

The saved optimised timetable didn't yet fit around the newly pinned open elective, and publishing was refused with 409. Both pass from `3acc154` on. This shows the tests catch a stale optimised timetable.

**Tests changed in `39212e3`** (because the college is now six real departments):
- `test_validator.py`: runs on the **fully synthetic college** (`_build_seed(SEED_DEPTS)`). The real college has nothing left to generate, so the generator and its mutation tests use synthetic data.
- `test_core_permissions.py`: the publish test is now `test_propose_publish_unpublish_adds_no_clash`. The published data already has teacher double-bookings (32 then; 5 now), so the check is "no clash that wasn't there before", not "0 issues". Also, an ME HOD now sees ME's own optimised timetable, never CSE's.
- `test_core_students.py`: also checks that every class of a regular section in the other departments has a student type.
- `test_core_fet.py`: teacher ids from another department now carry its prefix (`CE-JDS`).
- `test_core_rules.py`: adjusted to the per-department API.

**Test hygiene (applies to all files):**
- **Tests never write to `data/`:** every test that changes state monkeypatches `app.store.STATE` to a pytest temp folder. One dashboards test checks this (`STATE.exists()` in the temp path). The permissions tests also restore the published state, audit log and notifications after each test.
- **Fresh data:** most tests build their own fresh college and store, or reset overrides, bookings, meetings and notifications, so they don't depend on demo state.
  - The store, substitution and dashboard tests use `build_college()`: since `39212e3` that is the real six-department college, with nothing left to generate.
  - The validator tests use the fully synthetic college.
- **No hard-coded ids:** tests pick accounts dynamically (e.g. "a HOD of another department"), because ids changed when the real GNDEC data arrived.
- **Sign-in:** tests sign in with `X-User` (demo mode) or through `/api/auth/demo-login`.

### 11.2 `tests/test_validator.py`: proving the "0 clashes" claim (12)
These are "testing the tester": mutation tests inject each kind of mistake and check that the validator catches it. Since `39212e3` they run on the fully synthetic college, where the solver generates every department.

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

### 11.3 `tests/test_core_permissions.py`: role-based access (19)
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
| `test_capabilities_follow_the_table` | `/api/me.can` matches the table: a student can request meetings but not publish or approve; the admin has everything except the teacher-only items; HOD CSE can propose and substitute but not publish; the ME HOD sees **ME's own** optimised timetable but never CSE's |
| `test_endpoint_refusals` | Real HTTP calls: student → 403 on compare, users, audit, demo reset; ME HOD → 403 on the CSE compare; CSE HOD → 403 on publish; Dean → 403 on propose but 200 on view; a student can read their own timetable |
| `test_timetable_route_reports_published_clashes_apart` | *(added in `7a33645`)* `/api/timetable` (as the CSE HOD) answers 200 with entries; **`issues` is empty** (no clash caused by TimeWeave), and every entry of `published_issues` is a teacher clash from the college's own data |
| `test_public_demo_switches_off_the_assistant_and_optimiser_runs` | *(added in `5a6a9bc`)* With `TIMEWEAVE_HOSTED=1` (the public link): `/api/me.can` has **no `chat` and no `optimised_run`**, but `optimised_propose` stays; `/api/chat` answers "switched off" **without calling the paid API**; re-running the optimiser gives **409**; the saved optimised comparison is still available |
| `test_refusals_are_audited` | A refused demo reset by a student lands in the audit log with `allowed: false`, and the Dean sees it first in `/api/audit` |
| `test_propose_publish_unpublish_adds_no_clash` | (renamed in `39212e3`) Coordinator proposes → admin notified → admin publishes → the independent validator finds **no clash anywhere in the college that wasn't already in the published data** → unpublish → exactly the published clashes again. Edge case seen for real: while the saved optimised file had 1 clash (during a CSE re-run), publish was refused with 409 |

### 11.4 `tests/test_core_fet.py`: importing GNDEC's real timetable (7)
| Test | What it checks · edge case |
|---|---|
| `test_matches_published_room_page` | Matches the published page: room **G17 is busy in exactly 30 of 45 slots**; G17, S218, SL-I LAB and WS SEMINAR HALL exist |
| `test_sections_groups_and_labs` | D2 CS A has groups A1/A2; D3 CS A has **6 elective sub-groups**; every lab is a 2-period block; some lessons have 2–3 co-teachers |
| `test_real_timetable_has_no_clashes` | GNDEC's real timetable has **0 hard clashes**; the only notes are `NO LUNCH` and `LONG DAY` quality notes |
| `test_cell_parsers` | Parsing of group lists ("D3 CS A1, D3 CS B1"), a whole section with no sub-group ("D2 CS D"), teacher tags that are departments ("(App. Sci.)" → AS, "(JDS-CE)" → CE teacher `CE-JDS`), lab vs lecture codes, elective names |
| `test_groups_page_adds_open_elective_and_two_room_class` | *(added in `3acc154`)* The rooms page can't show OE-II; the groups page adds exactly 4 classes and **skips "Self Study"**; OE-II covers all D4 groups, 3 sessions, pinned, Mon/Wed/Fri 8:30 in the other-department room; the **two-room class** (S202 + S203) is added once; still 0 clashes |
| `test_open_elective_is_pinned_and_in_d4_timetables` | *(added in `3acc154`)* The optimiser may not move OE-II; **every D4 student type** has it in its timetable |
| `test_outside_room_is_never_a_free_room` | *(added in `3acc154`)* The "other department" placeholder room never shows up as a free room |

### 11.5 `tests/test_core_students.py`: real students (6)
| Test | What it checks · edge case |
|---|---|
| `test_saved_combinations_hold_no_personal_data` | **Privacy:** `students.json` has no 7-digit roll numbers and only the allowed anonymous fields; D4 adds up to **150** students and D3 to **340** |
| `test_every_class_has_its_students` | Every real CSE D3/D4 class is attended by at least one student type (no orphan classes); in the other departments, every class of a regular section has a student type |
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
| `test_rules_load_and_match` | All GNDEC rules (6 then, 10 now) load with a known type and plain-English text; selectors work by **code** (JPAL matches nothing-after-jpal), **teacher** (JPAL has no CSE teacher, so it's "run with another department") and **year** (an M.Tech class is postgraduate; CV is not) |
| `test_what_stays_where_the_college_put_it` | Mentoring, `TBA-` (other-department) and M.Tech/PhD lessons are never movable; an ordinary elective (CV) is |
| `test_college_timetable_against_its_rules` | The college's own timetable: real-class-every-day **0** breaks; nothing-after-jpal **exactly 1** (D4 CS C mentoring, Wed 15:30); lab pairs on one day **12** |
| `test_a_day_with_only_open_elective_and_project_is_caught` | The project owner's example: remove D4 CS A's real Friday classes, leaving only open elective/project/mentoring/JPAL, and the checker flags "no real class on Fri" for D4 CS A |
| `test_a_class_after_jpal_is_caught` | Moving CV to Thu 15:30, right after JPAL, is flagged as a class after JPAL |
| `test_optimised_timetable_obeys_the_rules` | For every rule, the optimised timetable breaks it **no more often than the college**; a **must** rule the college keeps (0 breaks) stays at 0; **the break counts saved in the file are honest** (equal a fresh count) |
| `test_publish_refuses_a_timetable_that_breaks_the_rules` | A clash-free timetable with a class after JPAL is **refused with 409** ("JPAL" in the message) and is not published. Edge case: clash-free is not enough; it must also respect the college's rules (state is written to a temp file) |

### 11.8c `tests/test_core_departments.py`: all six departments (19: 18 added in `39212e3`, 1 in `53e1f7f`)
| Test | What it checks · edge case |
|---|---|
| `test_every_department_is_imported` | IT, ME, CE, ECE and EE are all imported next to CSE, each with more than 200 lessons |
| `test_reader_handles_every_fet_flavour` | The tolerant reader handles every export flavour: "08:30-09:30", "8:30", "8.30 AM (1ST)" and **12-hour "01:30-02:30" = P6 (afternoon)**; room names "S-213" → S213 and "G10 (MPE Dept.)" → G10; groups "D2IT_C1" (section C, group 1), "D2IT_C" (whole section), **"D4E.1" is an elective, not section E**, EE's "D2A", minor course "D2MC"; teachers "Dr. Randeep Kaur-RDK", "SWJ (AppSc)" → Applied Sciences, "Dr. Narwant Singh Grewal (NSG)" |
| `test_the_whole_college_fits_together` | All six published timetables together: **no student group or room is double-booked**; the only clashes are teacher double-bookings, **at most 32** (today 5: four combined CSE/ME M.Tech classes listed by both departments, and one teacher CE's own export double-books) |
| `test_first_year_is_linked_across_departments` | *(added in `53e1f7f`)* "D1CSA2" in ECE's timetable is CSE's D1 CS A, group A2: **CSE's D1-CS-A-A1 gets classes from CSE and ECE**, and **IT's D1-IT-A-A1 from IT and EE**. The other departments' names ("D1CSA", "D1CSA1", "D1ITA", "D1 CE A1") are gone as separate audiences. **ME's "CSE A" (no year written) is left as it is, not guessed.** Still **no student clash anywhere**, also across departments |
| `test_shared_rooms_are_one_room_labs_are_not` | IT's and CE's "S-213" **is** CSE's S213 (one room); CSE's "DBMS LAB" and IT's "DBMSLAB" are **different** labs; the `OTHER DEPARTMENT` placeholder is not bookable |
| `test_a_class_taught_across_departments_is_not_counted_twice` | No real room has two classes at the same time after the merge: e.g. CSE's ERP, taught by an ME teacher and listed in both exports, is kept once |
| `test_what_may_move` | Every department has something to move; **no first-year class moves**; in IT/ME/CE/ECE/EE no elective/mixed class moves, and in 3rd/4th year only whole-section classes move |
| `test_optimised_department_is_never_worse` ×5 (IT, ME, CE, ECE, EE) | Same lessons and lengths; **clashes inside the department not more** than in the published version; never worse on 8 measures; every college rule broken no more often; pinned classes exactly where the college put them |
| `test_optimised_department_adds_no_clash_anywhere_in_the_college` ×6 (all six) | Each optimised department dropped into the **whole college** creates **no clash that the published timetables don't already have** (shared teachers and rooms) |
| `test_each_hod_compares_their_own_department` | The IT HOD lists **only IT** in `/api/compare`; the Dean sees all six; IT HOD → 200 on `/compare/it`, **403 on `/compare/cse`**, **404 on an unknown department**, 403 on publish (the timetable office publishes) |

### 11.8d `tests/test_core_chat_tools.py`: the assistant's tools on real data (4, added in `dce71d3`)
The tools are called directly, so no call to the Claude API and no credit is used.

| Test | What it checks · edge case |
|---|---|
| `test_search_finds_people_sections_and_rooms_in_any_spelling` | "Harpuneet" finds **one** record (`ME-HPS`; the duplicate record written by full name is merged); "D2IT" finds section D2-IT-C; **"S-213" (IT's spelling) finds CSE's S213** |
| `test_schedules_for_students_sections_teachers_rooms` | D4 CS A student type on "Monday": first class 8:30 is the **open elective**; **CSE first year (D1-CS-A-A1) on "Tue" includes ECE's BEEE** (linked across departments); section, teacher and room schedules work; G17 on Thu 10:45 is **not free** |
| `test_free_rooms_and_teacher_slots` | Free rooms on Mon 12:30 exist and **never include the stand-ins** ("OTHER DEPARTMENT", "APPLIED SCIENCES"); an IT teacher has free periods on Wednesday |
| `test_bad_input_is_reported_not_crashing` | **"Sunday"** and an **unknown room** come back as an error message to the model, not a crash |

### 11.9 `tests/test_dashboards_api.py`: Lane B (14)
Runs against a fresh `build_college()` store (since `39212e3`, the real six-department college), with state in a temp file.

| Test | What it checks · edge case |
|---|---|
| `test_student_view_shows_exactly_their_classes` | A student's view has exactly the classes their type attends, including whole-section and single-group classes; an unknown type gives 404 |
| `test_types_sharing_a_group_number_can_differ` | Two student types in one section see different weeks (group numbers are not students) |
| `test_section_year_and_dept_views_nest` | student ⊂ section ⊆ year ⊆ department ⊂ whole college |
| `test_every_department_has_a_view` | Every department, including **Applied Sciences with no sections of its own**, has a non-empty view |
| `test_teacher_and_room_views` | The teacher view has only that teacher's classes, **including labs they co-teach** (relaxed in `e2795e7` for the real all-department data); the room view only that room's |
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

### 11.12 `tests/test_venues_slots.py`: Lane C slot finder (9)
| Test | What it checks · edge case |
|---|---|
| `test_never_returns_a_slot_where_a_group_has_class` | Slots never overlap any audience group's class, but the rest of the day is offered; **a class for just one group still blocks the whole audience** |
| `test_cancelled_class_frees_the_slot` | A cancelled class frees its slot on that date |
| `test_slots_come_with_venues_and_lunch_warning` | A slot that uses **the only lunch period left** is warned about; other slots aren't; every venue fits 50 people with a projector; lunch-eating slots are ordered after the others |
| `test_real_timetable_dept_year` | Dept + year over a real Mon–Fri week: the audience covers every group of the section; no clashes |
| `test_permissions_and_bad_input` | A club may use it (200); a student can't (403); no audience → 400; unknown group → 400; duration 99 → 400 |
| `test_almost_free_slots_name_who_would_miss_class` | When the whole lunch window is already busy there is **no lunch warning** (nothing left to protect); "nearly free" times name the exact busy groups, the section and its classes, and whether the whole section is missing |
| `test_electives_of_the_same_year_block_a_section_audience` | *(added in `49004bb`)* An elective mixes students of several sections, so a class of an elective of the same year **blocks a whole-section audience**; the elective is listed in the audience, its periods are not offered, and "nearly free" names the elective as the reason |
| `test_dept_year_counts_only_real_sections` | *(added in `49004bb`)* Dept + year counts only **real sections** (not elective audiences), and attendees are the sum of their sizes |
| `test_other_department_stand_in_is_never_a_venue` | *(added in `49004bb`)* The `OTHER DEPARTMENT` placeholder never appears as a venue or a near miss |

### 11.13 What the automated tests don't cover (honest gaps)
- **The chatbot conversation** (`/api/chat`, the call to Claude) has no automated test. This is on purpose: it would spend the limited Anthropic API credit. Since `dce71d3`, **all 5 of its tools are tested** directly on the real data (§11.8d).
- **The HTML pages** (index, venues, compare, login, audit) have no automated browser tests. **Lane A did a full browser run-through of every role on 26 Oct**, before `dce71d3` / `d3e1a9d`, with no server errors (500s) during the whole run. Reported results:
  - **Student** (D4 CS A, the project owner's own combination): own week including OE-II at 8:30, free rooms, find a teacher.
  - **Teacher** (an IT teacher): own week, venue search.
  - **HOD IT:**
    - dashboard with the green "0 clashes" card, the amber "5 teacher double-bookings as published" badge and the Data card
    - an IT-only comparison with Propose
  - **Timetable office:** the six-department picker with Propose and Publish; the audit log.
  - **Dean:** a read-only comparison (no buttons).
  - **CSE coordinator:** the substitutions board with ranked substitutes.
  - **Club lead (DMC):** venue search for 100 people.
    - MBA Seminar Hall is the best fit, then LT-1/2.
    - IT's T&P seminar hall goes to the IT HOD for approval.
  - **T&P:** the slot finder for all of D4 CSE gives 13 common 2-hour slots in two weeks, with the Auditorium.

  This run-through is Lane A's report; I did not repeat it here.
- **`POST /api/generate` and `POST /api/compare/{dept}/run`** are only tested indirectly: the solver and optimiser output are tested, and the permission rules for generate are tested.
- **Optimiser runs** themselves are not run in tests (they take minutes); the tests check the saved result.

---

## 12. Timeline: how it was built
From `git log` (77 commits up to `2ac1a85`; 11 of them are this report). Commits per day: 21 Oct 15 · 22 Oct 14 · 26 Oct 45 · 27 Oct 3.

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
- **Lane A, last:** the FET groups page (open elective OE-II, the two-room mentoring class; fixes ERP missing from students' timetables) and a 15-minute re-optimisation around it (`3acc154`). Then the lab-pair rule (SC Lab A1 / A2 stay on two days, reported by a student) and another 15-minute re-optimisation (`becb48e`). Last, **College rules**: 6 GNDEC rules written down in JSON, obeyed by the optimiser, counted by an independent checker, enforced on publish, plus 7 tests and a 15-minute re-optimisation (`32f1b45`).
- **Lane A, final:** **every department's real timetable**:
  - the tolerant FET reader for IT, ME, CE, ECE and EE
  - one merged college
  - 4 new safety rules for departments without elective lists
  - the per-department compare/propose/publish API and page
  - sign-in in four groups (redesigned in `84f400e`: four roles, and a student flow of department → year → section → group and subjects); the top bar's account dropdown replaced by a Switch button, and placeholder "teachers" get no demo account (`958cd5d`)
  - all six departments re-optimised, and 18 new tests (`39212e3`)
- **Lane A, after that:**
  - **first year linked across departments** (`53e1f7f`): 94 sessions from ME, ECE and EE now in first-year timetables; teacher clashes in the published data 32 → 12
  - **dashboard truth** (`89254d8`):
    - two different teachers named Harminder Kaur are no longer merged (12 → 5 teacher clashes)
    - `/api/timetable` separates `issues` (none caused by TimeWeave) from `published_issues` (the college's own 5)
    - status "IMPORTED", with no stale solver fields
  - a tidy-up (`dee7b1e`):
    - only the seed's central venues kept
    - `/api/timetable` says every department is real
    - `POST /api/generate` explains there is nothing to generate
    - `python -m app.solver` demonstrates generation on the synthetic college
- **Lane B, final:**
  - pickers list real sections only, no "Other department" rooms (`e2795e7`)
  - a timetable-issues badge for staff only, worded as teacher double-bookings in the published data (`286e3f8`)
  - honest dashboard numbers (`6c59dbc`): the validator card counts only TimeWeave's own clashes, the college's published clashes are shown separately to staff, a Data card replaces the solver card for imported timetables, and the grid shows even if `/api/timetable` fails
  - no Generate button when every department is imported; the data source and a link to the optimised timetables instead (`cabdf9e`)
- **Lane A, last before submission:**
  - **a full browser run-through of every role**, with no server errors (500s) (see §11.13)
  - **fixes from it, part 1** (`dce71d3`):
    - the assistant's tools tested on real data (4 tests)
    - "Mon"/"Monday" and "S-213" understood
    - one teacher record per person (ME-DRHARPUN merged into ME-HPS)
  - **fixes from it, part 2** (`d3e1a9d`):
    - only numbered classrooms offered to sit in or book: vague names from other departments' exports ("A (other Deptt)", "Arc Dept 5", "Teach Office") stay in the timetable only
    - "taught elsewhere" placeholders show the subject (e.g. "Outside: PPS")
    - EE building named
    - rule wording made department-neutral
    - a favicon
    - PLAN.md section 0 brought up to date
- **Lane C, final:** elective audiences and student types also rule slot-finder times out; 3 new tests (`49004bb`).
- This report was committed alongside.

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

Re-import IT, ME, CE, ECE and EE from `data/gndec/raw/<dept>/`:
```bash
.venv/Scripts/python -m app.importers.fet_dept ALL
```

Optimise departments (here 300 s each for IT and ME; or `ALL`), writing `data/gndec/<dept>_optimised.json`:
```bash
.venv/Scripts/python -m app.optimise 300 IT ME
```

- **Optional:** copy `.env.example` to `.env` and add `ANTHROPIC_API_KEY` for the assistant (never commit `.env`).
- **Demo mode** is on by default (`TIMEWEAVE_DEMO=1`). Sign in at `/login.html` by picking an account.
- **Re-import CSE:** `python -m app.importers.fet` (FET HTML → `data/gndec/cse.json`) and `python -m app.importers.gndec_students` (needs the private lists).
- **Generator demo:** `python -m app.solver` generates the synthetic seeded college from scratch and prints the status and the validator's result (since `dee7b1e`). The live GNDEC college has nothing to generate, because every class is imported.
- **Requirements:** FastAPI, OR-Tools, the Anthropic SDK, pypdf, and the rest of `requirements.txt`.

### 14.1 The live demo (deployed)
- **Link:** **https://timeweave-3y2g.onrender.com**
- **Host:** Render, free tier (0.1 CPU, 512 MB). Built from the repo's `Dockerfile` (Python 3.12) with `TIMEWEAVE_HOSTED=1` and `TIMEWEAVE_DEMO=1`. The app uses about 150 MB and starts in about 7 s locally (figures from Lane A).
- **Sleep:** the free server sleeps after 15 minutes idle, so the first visit then takes about a minute. **Open it a few minutes before judging.**
- **Hosted mode:**
  - The AI assistant (paid API) and optimiser re-runs (minutes of full CPU) are switched off. Both give a friendly message, and their buttons and links are hidden via `TW.can`.
  - Everything else works, including demo sign-in for every role.
  - A random session secret is used when `TIMEWEAVE_SECRET` isn't set, so sign-ins end on a restart.
  - Demo changes (bookings, leave, meetings) reset when the server restarts.
- **Checked here on 27 Oct (read-only requests):**
  - `/`, `/login.html` and the demo account list answer 200
  - `/api/me` without sign-in answers 401
  - 464 demo accounts
  - `/api/timetable`: `IMPORTED`, 0 issues, 5 published issues, 2,579 sessions
  - HOD IT: no assistant, no re-run, can propose
  - the timetable office sees all 6 departments
- **Checked by Lane A on the live site:**
  - a student's week has 22 classes
  - a student gets 403 on the comparison
  - 105 free rooms at Mon P5
  - HOD IT sees only IT (student waiting 15 → 11); a re-run gives 409
  - the CSE comparison page renders
- **How we got there:** Hugging Face Spaces was tried first, but Docker Spaces now need a paid plan, so Render was used. `deploy/push_to_space.sh` (publishes to a Space without the binary files in `docs/progress`) is kept but unused.

---

## 15. Demo script
Suggested, about 5 minutes. Built only from features listed above.

**Where to run it:**
- **Live link:** https://timeweave-3y2g.onrender.com. Open it a few minutes early to wake the free server. On the live link the AI assistant and optimiser re-runs are off; everything else works.
- **Locally:** run it locally (§14) to show the assistant (step 9) or an optimiser re-run.

1. **The problem** (30 s): hand-made timetables take weeks, still have problems, and students and teachers wait between classes. GNDEC's six real published timetables (2,579 classes a week) have:
   - about 1,000 teacher waiting periods a week
   - 44 CSE student-days with no midday break
   - 5 teacher double-bookings when put together (and 0 caused by TimeWeave)
2. **Sign in as a student** (`/login.html`):
   - Point out the four roles (Student, Teacher, HOD, Timetable office).
   - Choose **Student → CSE → 4th year → D4 CS A**. The group and subjects are pre-filled with the most common combination; set **A2, CV, SC (A1 group), TA A3** and press **Show my timetable**.
   - My timetable shows only *their* electives and *their* lab group.
   - Explain the FET re-used-group problem and student types.
   - **For a first-year student** (e.g. CSE D1 A, group A1), show that the week now includes ECE's BEEE lectures and lab: 11 hours instead of 5, because first year is linked across departments.
   - Show the **Now/Next** card and **Free rooms → Right now** by building and floor.
3. **Find a teacher → Request meeting** in a free period. Switch to that teacher, accept, and the student gets a 🔔.
4. **Teacher marks leave.** As the CSE HOD, open **Substitutions**: ranked substitutes with reasons. Assign one; the student's timetable shows the substitute for that date only.
5. **Venues as the Digital Marketing Club:**
   - Book a venue for 100 people with projector + sound: ranked rooms with reasons.
   - Request → faculty advisor endorses → HOD approves → the hall disappears from Free rooms.
6. **Event slot finder as T&P:** D4 CS for a 2-hour talk: slots where every group is free, venues attached, lunch protected, and "nearly free" times showing who would miss which class. **Book this** notifies the batch.
7. **Optimised timetables, every department** (`/compare.html`):
   - **As the Dean:** the department picker lists all six. Show EE (student waiting periods 25 → 0, teacher waiting periods 129 → 62) and ECE (15 → 0, 105 → 52).
   - **As the IT HOD:** only IT is listed.
   - **The whole college:** teacher waiting periods 1,007 → 600 (−40%), student waiting periods 263 → 188, with **no new clash anywhere in the college**. Same lessons, times only.
   - **CSE:** no-lunch days 44 → 0. Be honest: CSE's gain is smaller than in the CSE-only run, because CSE's first year and classes by other departments' teachers are now kept as published, so other departments are never hurt.
   - **Rules:** scroll to **"GNDEC's timetable rules"**: each college habit in plain words, and how often each version breaks it. Tell the story: an earlier CSE run left 6 D4 Fridays with only project + open elective; writing the rule down fixed it (6 → 0).
   - **Publishing:** it is refused if a rule is broken more often, or if a clash appears anywhere in the college. **Propose** as the HOD, then **Publish** as the admin; the validator re-checks the whole college.
8. **Trust:** the independent validator, the independent college-rules check, 122 automated tests, and the audit log (`/audit.html` as the Dean) showing a refused action.
9. **Ask TimeWeave** (optional; locally only, uses API credit; switched off on the live link): "Will G17 be free at 12:30 on Friday?"

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
- **Alerts and extras:** room door QR page, live updates (SSE), PWA/push, email/WhatsApp notifications.
- **Deployment: done** (see §14.1). Still open: a database instead of JSON files (demo changes reset on restart), a paid or always-on server (the free one sleeps), and the AI assistant and optimiser re-runs on the hosted demo (switched off there).

**Data gaps:**
- **First-year weeks are still incomplete:** first year is now linked across departments (`53e1f7f`), so ME's, ECE's and EE's classes show up. But Applied Sciences (maths, physics, chemistry, English) doesn't publish a timetable, so those hours are missing for every first-year group. (From Lane A.)
- **ME's "CSE A" … "CSE F"** (one subject, "EP&S", no year written) are left unlinked rather than guessed.
- **No elective distribution lists for IT, ME, CE, ECE and EE.** Their electives and 3rd/4th-year group classes therefore stay as published, and their students are one type per lab group, guarded against same-year electives.
- **Initials only:** 35 of 203 real teachers (CE publishes initials only) keep a name like "CE teacher (HVS)".
- **Published errors:** the published timetables themselves contain 5 teacher double-bookings when put together (4 combined CSE/ME M.Tech classes listed by both departments, and 1 in CE's own export). The API lists them as `published_issues`. TimeWeave reports them and never adds to them, but can't fix them without knowing which listing is right.
- **Same-name teachers:** teachers are merged across departments by name and initials, except when both records are on one department's own list. A same-named pair that appears in two different departments could still be merged wrongly; none is known.
- "Self Study · Library" slots are deliberately not imported (they are free periods, not classes).
- Teachers' unavailability isn't known (none is assumed).
- Elective-IV lab days rely on one student's confirmation.
- **Synthetic central venues:** the Auditorium, the MBA Seminar Hall, LT-1/LT-2 and a library reading room come from the synthetic seed (the made-up computer labs and department labs were removed in `dee7b1e`). No class uses them; they serve as bookable venues in the demo.

**Optimiser:**
- **Safety over gains:** with six real departments, CSE's first year, classes by other departments' teachers and other departments' classes are fixed. CSE's gains are therefore smaller than in the CSE-only run (student waiting periods 181 → 153 instead of → 75), in exchange for a guarantee of no new clash anywhere in the college.
- **Runs are short:** 4–10 minutes per department; longer runs may improve further.
- 7 classes in the 4:30–5:30 slot stay (pinned CSE mentoring).
- Days over 6 periods improve only partly (CSE 280 → 245; IT and ME unchanged), because D3 groups have 36 periods a week.
- Same-day lab pairs that the college itself schedules may stay (CSE 11, IT 4, CE 2, EE 1 remain).
- Three fixed 8:30 open-elective classes a week for all of D4 limit CSE's waiting periods.
- `real-class-every-day` is already broken in ME (9), CE (5) and ECE (16) as published. The optimiser keeps those counts but can't fix them, because the classes involved are pinned.
- One class after JPAL remains: the college's own pinned D4 CS C mentoring, Wed 3:30.

**College rules:**
- Only rules the college has confirmed are written down. A guessed rule ("project only in the morning") was dropped, because the college itself has a project hour at Mon 3:30.
- `real-class-every-day` excludes D1, because 1st-year subjects are in Applied Sciences' timetable, not CSE's.
- A new rule *type* needs code: a check in `rules.breaks()` and a constraint in `optimise.py`. New rules of the 5 existing types need only JSON.

**Open cross-lane request:** a `leave_board` capability for the Dean.

**Security notes:**
- The session secret has a development default locally. When hosted without `TIMEWEAVE_SECRET`, a random secret is generated (`5a6a9bc`). Set `TIMEWEAVE_SECRET` for a permanent deployment.
- Demo mode (no password; the `X-User` header) is on in the public demo on purpose, for judging. It must be turned off (`TIMEWEAVE_DEMO=0`) for real use.

**Scale:** the six departments' final runs took 235–596 s each; the generator needed about 46 s for the seeded departments.

---

## 17. Key numbers for slides
| Number | What |
|---|---|
| **Live** | https://timeweave-3y2g.onrender.com (sign in as any role) |
| **6** | real GNDEC department timetables imported and optimised (CSE, IT, ME, CE, ECE, EE) |
| **2,579** | real weekly classes; 1,865 lessons; 203 teachers; 153 rooms |
| **0** | new clashes anywhere in the college from any optimised department (proven by an independent validator that shares no code with the solver) |
| **1,007 → 600** | teacher waiting periods per week, all six departments (−40%) |
| **263 → 188** | student waiting periods per week, all six departments (−29%) |
| **25 → 0 / 15 → 0** | student waiting periods in EE / ECE |
| **44 → 0** | CSE student-days with no midday break |
| **94** | first-year sessions taught by ME, ECE and EE, now linked into the students' own timetables (CSE D1 A1: 5 → 11 hours) |
| **32 → 5** | teacher double-bookings in the published timetables put together, after linking first year and keeping same-named teachers apart (0 student, 0 room); TimeWeave causes **0** |
| **150 / 48** | CSE D4 students / real elective combinations modelled |
| **340 / 57** | CSE D3 students / real elective combinations modelled |
| **241** | student types across the college |
| **10** | GNDEC timetable rules written down; every one kept at least as well as the college does |
| **6 → 0** | D4 Fridays with only project + open elective (an earlier CSE run vs now), fixed by writing the rule down |
| **8** | roles, with a deny-by-default permission table and an audit log |
| **40** | API routes |
| **123 / 123** | automated tests passing |
| **3** | parallel build lanes, 77 commits |

---

## 18. Sources
**Files read:**
- `CLAUDE.md`, `PLAN.md`, `README.md`
- `docs/DESIGN.md` (headings), `docs/API.md`, `docs/REQUESTS.md`
- `docs/progress/report.html` (Day 1 report)
- `app/auth.py`, `app/models.py`, `app/store.py`, `app/solver.py`, `app/validator.py`, `app/optimise.py`, `app/substitutions.py`, `app/chat.py`, `app/seed.py`, `app/main.py`
- `app/importers/fet.py`, `app/importers/fet_dept.py` (header and functions), `app/importers/gndec_students.py`, `app/rules.py`
- `app/api/core.py` (routes, compare/propose/publish per department), route lists of `app/api/dashboards.py` and `app/api/venues.py`
- the `39212e3` diffs of `app/auth.py`, `app/validator.py`, `app/store.py`, `app/models.py`, `login.html`, `shell.js`, `docs/API.md` and the changed tests; the `49004bb` and `e2795e7` test changes
- `app/static/*.html` and `js/shell.js` (labels and tabs)
- every file in `tests/`

**Data:**
- `data/gndec/<dept>.json` and `data/gndec/<dept>_optimised.json` for all six departments; `cse_optimised.json` also at earlier commits via `git show <commit>:`
- `data/gndec/students.json`, `data/gndec/rules.json`, `data/solution.json` (through `STORE.result`)
- **Not read:** `data/private/`

**Commands (26 Oct 2026):**
- `pytest -q` on `2ac1a85`: **123 passed** (final); on `d3e1a9d`: 122; on `7a33645`: 118; on `89254d8`: 117; on `53e1f7f` + `dee7b1e`: 117; `test_first_year_is_linked_across_departments` passes on its own
- first-year checks:
  - 94 linked sessions (ME 23, ECE 22, EE 49)
  - CSE D1-CS-A-A1: 5 hours at `39212e3` (temporary checkout) → 11 now
  - whole college: 12 teacher clashes then, **5 after `89254d8`**, 0 student/room
- the six refreshed `<dept>_optimised.json` files, re-read after `53e1f7f` and `dee7b1e`
- `pytest -q -rA` on commit `39212e3`: 116 passed, with per-file counts
- a Python check of the merged college (rooms, teachers, sections, lessons, sessions, student types, accounts, rules, lab pairs, whole-college clashes and metrics), of which rooms come from the seed, and of each department's own clashes before/after (`department_college`)
- `pytest -q` on commit `32f1b45`: 95 passed
- `pytest -q` on commit `becb48e`: 88 passed
- `rules.breaks()` on the `becb48e` optimised timetable (`git show becb48e:data/gndec/cse_optimised.json`): real-class-every-day broken 6 times
- read `app/rules.py`, `data/gndec/rules.json`, the rule constraints in `app/optimise.py`, and the `32f1b45` changes to `app/api/core.py` and `CLAUDE.md`
- `pytest -q` on commit `3acc154`: 87 passed
- a Python check of `College.lab_pairs()` (86 pairs, 54 in CSE) and of the SC/ACC lab days in the optimised file
- earlier: `pytest -q -rA` on the working tree before the re-run (85 passed, 2 failed as expected) and on a clean checkout of `aac5df1` (84 passed)
- `pytest --collect-only -q` (87 tests at `3acc154`; 88 at `becb48e`; 95 at `32f1b45`; 116 at `39212e3`; 117 at `53e1f7f`; 118 at `7a33645`; 122 at `d3e1a9d`; 123 at `2ac1a85`)
- a Python check printing college counts, metrics and `compare` from `app.store.STORE`
- `git log`, `git log --stat`, `git diff --stat`, `git status`

**Deliberately not run:** `python -m app.optimise` (Lane A ran the optimiser) and `/api/chat` (limited API credit).

**From Lane A's session, not checked independently here:**
- the background of the groups-page import (the student who noticed ERP was missing)
- the department websites' URLs
- the reason for the six-department work (the project owner's wish to optimise every branch)
- that Applied Sciences publishes no timetable (why first-year weeks are still incomplete)
- what first-year subjects ME, ECE and EE teach (workshop/drawing, BEEE)

All numbers were checked here against the committed data files.

---

## 19. Pending
**Resolved on 26–27 Oct:**
- Final test totals: **123 / 123 pass** (re-run here on `2ac1a85`; Lane A 85, B 14, C 24).
- The live deployment: answered and matched the local numbers (see §14.1).
- Counts after the re-import in `d3e1a9d` (203 real teachers, 464 accounts, 64 sittable / 77 bookable rooms) and unchanged optimised results: checked here.
- **The UI in a browser: verified by Lane A** in a full run-through of every role on 26 Oct (see §11.13). I did not click through it myself.
- Clash counts after `89254d8` (5 teacher, 0 student, 0 room), the `/api/timetable` fields, and ECE's re-measured numbers: checked here.
- First-year linking: checked independently (see Sources).
- Per-department optimised numbers (§10.3, §17): every value checked against the six committed `<dept>_optimised.json` files, and the "All six" sums added up by hand and matched against the whole-college metrics.
- College-rule break counts: from each optimised file.
- Merged college counts (§4.4, §7.1): measured with `app.store.STORE`.

**Still not verified independently here:**
- Nothing in the data or tests.
- My own descriptions of the UI come from the page source (labels, tabs, `x-show` rules). The browser behaviour of every role was verified by Lane A (above and §11.13).

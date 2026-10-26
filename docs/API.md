# TimeWeave API contract (v2)

Every lane codes against this file. **Lane A owns the "Core" and "Shared building blocks" sections.** Lanes B and C own their own sections below and keep them up to date as they build. To change something you don't own, add a note to `docs/REQUESTS.md`.

## Conventions
- **JSON everywhere.** Errors come back as `{"detail": "plain-English message"}` with status 400, 401, 403, 404 or 409.
- **Who is calling:** every request sends the demo account id in the `X-User` header. `TW.api()` in `static/js/shell.js` does this for you. With no header, the caller is `admin`.
- **Days and periods:** `day` is 0–4 (Mon–Fri). `period` is an index into `/api/meta.periods`. Real dates are ISO strings (`2026-10-23`).
- **Permissions:** checked on the server with `app.auth.require(user, action, resource)`. Hiding things in the UI is cosmetic only.

## Shared building blocks (Python, owned by Lane A)
| Thing | Where | Use it for |
|---|---|---|
| `STORE` | `app/store.py` | The one shared state. Never keep your own globals. |
| `STORE.college` | | Rooms, teachers, sections, lessons, buildings. Lookups: `room_by_id`, `teacher_by_id`, `section_by_id`, `lesson_by_id`, `building_by_id`. |
| `STORE.week()` | | `list[Occupancy]` for the base weekly timetable (all days). |
| `STORE.effective(date)` | | `list[Occupancy]` on a real date: classes after cancellations, substitutions and room changes, plus bookings. |
| `STORE.busy_rooms(occupancies, period)` | | `{room_id: Occupancy}` busy in that period. |
| `STORE.add_override(Override)` | | Create a date-specific change, e.g. an approved booking (`kind="booking"`). Saves automatically. |
| `STORE.bookings` / `STORE.meetings` | | Lists of `BookingRequest` / `MeetingRequest`. After changing them, call `STORE.save()` while holding `STORE.lock`. |
| `STORE.notify(user_id, text, link)` | | In-app notification; shows in the 🔔 of every page. |
| `STORE.users` / `STORE.clubs` | | Demo accounts and clubs (built in `app/auth.py`). |
| `new_id(prefix)`, `now_iso()` | `app/store.py` | Ids and timestamps. |
| `current_user` | `app/auth.py` | FastAPI dependency: `user: User = Depends(current_user)`. |
| `require(user, action, resource)` | `app/auth.py` | Raises 403. Actions and rules live only in `authorize()`. |

**`Occupancy`** (`co_teachers` lists extra teachers, e.g. for labs) has these fields:
- `key`, `kind` (`"class"` or `"booking"`), `day`, `start`, `duration`, `slots`
- `room`, `teacher`, `batches`, `lesson`, `title`
- `status` (`normal`, `substituted` or `room_changed`)

**Domain types** are in `app/models.py`: `Room` (with `building`, `floor`, `features`, `sittable`, `bookable`), `Building`, `Override`, `User`, `Club`, `BookingRequest`, `ApprovalStep`, `MeetingRequest`, `Notification` and `FEATURES`.

**Permission actions that already exist:**
`timetable.view`, `timetable.generate`, `override.create`, `booking.request`, `booking.cancel`, `booking.endorse`, `booking.approve`, `slotfinder.use`, `meeting.request`, `meeting.reply`, `leave.mark` (the teacher themself, or their HOD), `leave.view`, `demo.reset`, `rooms.view`, `chat.ask`

`slotfinder.use` also allows clubs. `BookingRequest.audience` (group ids) exists for events booked for a batch.

**Demo accounts** (ids):
- `admin`
- `hod-<DEPT>`
- `t-<TeacherId>` (teachers)
- `s-<group>` (students, e.g. `s-CSE-3A-G1`)
- `club-DMC`, `club-CODE`, `club-ROBO`
- `org-TNP`, `org-visitor`

## Core: Lane A (`app/api/core.py`)
| Method + path | Returns |
|---|---|
| `GET /api/meta` | days, periods, lunch window, departments, **buildings**, **features**, sections (with batches), teachers, rooms, counts |
| `GET /api/me` | the calling `User` |
| `GET /api/users` | `{roles: {role: [{id, name, dept}]}, clubs: [...]}` for the account switcher |
| `GET /api/timetable` | base timetable: `{ready, status, seconds, issues, notes, metrics, compare, baseline, source, entries:[entry view]}`. `issues` = hard clashes (must be empty); `notes` = quality notes (`NO LUNCH …`, `LONG DAY …`) that only imported data may have; `compare` = `{real, generated}` metrics |
| `GET /api/effective?on=YYYY-MM-DD` | `{date, weekday, items:[occupancy view]}` |
| `POST /api/generate?time_limit=30` | regenerate (needs `timetable.generate`) |
| `GET /api/free-rooms` | free rooms (see below) |
| `GET /api/notifications` | `{items, unread}` for the caller |
| `POST /api/notifications/read` | marks all of the caller's notifications read |
| `POST /api/chat` | `{answer, tools_used}` |
| `POST /api/demo/reset` | clears overrides, requests and notifications (admin only) |
| `POST /api/leave` | `{teacher, date, periods?, reason?}` (needs `leave.mark`): creates `Override(kind="leave")`, notifies the teacher's HOD, and returns `{leave, classes}`. Each class has `{key, time, code, subject, section, room, batches, state: open/covered/substituted/cancelled, by_name?, candidates?}` |
| `GET /api/leave?on=YYYY-MM-DD&dept=` | `{date, leaves:[{leave, teacher_name, dept, classes}]}`. HODs see their department, teachers see themselves, admin sees all |
| `POST /api/substitutions` | `{date, entry_key, teacher}` or `{date, entry_key, cancel:true}` (needs `override.create` for the class's department). Re-checks that the substitute is free (409 if not), replaces any earlier decision, and notifies the substitute, the absent teacher and the students. Returns `{override, message}` |

**Substitute ranking** (`app/substitutions.py`):
- **Hard filters:** free for the whole class on that date, including labs they co-teach; on campus; not on leave; under their daily limit.
- **Score:** +40 teaches the same subject, +20 same department, +15 already teaches these students, +5 has a class right next to it, −8 for each substitution this month, −4 for each period already taught that day.
- Every candidate comes with `reasons` (plain-English strings).
- A class someone else co-teaches is `covered` and needs no substitute.

**Chatbot tools** (`app/chat.py`, read-only, all through `STORE`):
- `search`
- `get_schedule(kind: section|group|teacher|room, id, date?|day?)`
- `free_rooms(date?|day?, time?, building?, floor?, sittable_only=true, min_seats?)`, grouped by building and floor
- `room_status(room, date?|day?, time?)`: answers "will G17 be empty at 12:30 on Friday?"
- `teacher_free_slots(teacher_id, date?|day?)`: counts co-taught labs and leave

**`/api/free-rooms` parameters:**
- `period` (required)
- either `day` (0–4, weekly template) or `on` (YYYY-MM-DD, includes bookings and cancellations)
- optional filters: `min_capacity`, `kind`, `sittable_only=true`, `building`, `floor`
- Each returned room has all `Room` fields plus `free_until`. Rooms come sorted by building, then floor (ground first), then classrooms first.

## Lane B: Dashboards (`app/api/dashboards.py`, prefix `/api/dash`)
Owned by the Dashboards session. Built and tested in `tests/test_dashboards_api.py`.

| Method + path | Returns |
|---|---|
| `GET /api/dash/views` | filtered timetable `{mode, dates, items, filters}` (needs `timetable.view`) |
| `GET /api/dash/teacher/{teacher_id}/free?on=` | a teacher's day, period by period (default: today) |
| `POST /api/dash/meetings` | `{teacher, date, period, note}` → the new meeting (needs `meeting.request`: students) |
| `GET /api/dash/meetings` | `{sent, received, pending}`: meetings I asked for, and meetings asked of me (teacher or HOD) |
| `POST /api/dash/meetings/{id}/reply` | `{status: accepted\|declined, reply}` → the meeting (needs `meeting.reply`: only that teacher) |
| `GET /api/dash/now?on=&period=` | the caller's now / next / next-free card |

**`/views` filters** (combine with AND; leave all empty for everything):
- `group` (one lab group, e.g. `D3-CS-A-A1`): whole-section classes + that group's labs + electives it is in.
- `section`: every class with at least one of the section's groups.
- `dept` + `year`: all sections of that year. `dept` alone: the whole department. A department with no sections (e.g. Applied Sciences) shows what its teachers teach.
- `teacher` (main teacher or co-teacher, so co-taught labs show up), `room`.
- Dates: none = base weekly timetable (`mode: "week"`). `on=YYYY-MM-DD` = that date via `effective()` (`mode: "date"`). `week_of=YYYY-MM-DD` = Mon–Fri of that date's week (a weekend means the coming week), each via `effective()` (`mode: "week_of"`, `dates` lists the 5 days).
- Each item is an `Occupancy` plus `date`, `code`, `name`, `lesson_kind` (`theory`/`lab`/`booking`), `dept`, `section`, `teacher_name`, `co_teacher_names`, `regular_teacher_name` (set when `status` is `substituted`: whose class the substitute took), `until` (end time). Bookings come back with `kind: "booking"` and their title.

**`/teacher/{id}/free`** → `{teacher, name, dept, date, day, weekend, periods, free}`. Each period has `period, label, start, end, state, what`, where `state` is `leave` (a leave override that date), `teaching` (main or co-teacher), `unavailable` (`Teacher.unavailable`), `meeting` (an accepted meeting) or `free`. Substitutions on that date count.

**Meetings:**
- A request must be for a weekday, today or later, in a period the teacher is `free`; otherwise 400 or 409. Asking twice for the same slot is 409.
- Requests notify every account of that teacher (`t-<id>`, and `hod-<dept>` if they are HOD), linking to `/#meetings`. Replies notify the student, linking to `/#teacher`.
- Meeting views add `teacher_name`, `student_name`, `day` and `slot {period, label, start, end}`.

**`/now`**: `period` is the current period index (`-1` before the day starts, `len(periods)` after it ends). Students get their group's day, teachers and HODs their own. Returns `{date, day, who: group|teacher|null, weekend, now, next, free: {period, label, start, until, periods, now}, meetings, leave, today}`. Accepted meetings and leave count as busy; `leave` lists the periods the teacher is on leave, and classes inside their leave are left out of `now` / `next`.

**Page deep links** (`/`, index.html): `#teacher`, `#rooms`, `#meetings`, `#subs` (HOD/admin), `#load`, `#ask`.

**Leave and substitutions UI** uses the Core endpoints (`POST /api/leave`, `GET /api/leave?on=`, `POST /api/substitutions`): teachers get a "Mark leave" button; HODs and admin get the Substitutions tab with the next 6 school days, each absent teacher's classes, state chips, ranked candidates with reasons, Assign and Cancel class.

## Lane C: Venues and events (`app/api/venues.py`, prefix `/api/venues`)
Owned by the Venues session. Logic lives in `app/venues/` (`ranking.py`, `requests.py`, `slots.py`, `common.py`); the page is `/venues.html` with tabs `#book`, `#requests`, `#inbox`, `#slots`.

**Common rules**
- `date` is `YYYY-MM-DD`, Mon–Fri only, not in the past (400 otherwise). `periods` are indexes into `/api/meta.periods` and must be back to back (e.g. `[4, 5]` = P5–P6).
- `needs` is a subset of `/api/meta.features` (400 for unknown ones).
- "Free" always means free in `STORE.effective(date)`: after cancellations, substitutions and room changes, and counting approved bookings.

| Method + path | Who | Body / query | Returns |
|---|---|---|---|
| `GET /api/venues` | anyone | | `{venues: [venue]}`, every bookable room, biggest first |
| `POST /api/venues/rank` | anyone | `{date, periods, attendees, needs}` | `{date, periods, attendees, needs, venues: [venue + fit], near_misses: [venue + miss]}` |
| `POST /api/venues/requests` | `booking.request` | `{title, purpose?, club?, attendees, needs, date, periods, room, audience?}` | `{request: request view, warnings: [str]}`. 409 if the room is already taken then. |
| `GET /api/venues/requests` | anyone | `?mine=1` (default) · `?inbox=1` · `?all=1` (admin) | `{items: [request view]}`, newest first |
| `POST /api/venues/requests/{id}/decide` | the current step's approver | `{decision: "approved"\|"rejected", note}` | `{request: request view}`. 403 wrong approver, 400 reject without a note, 409 already decided or room no longer free |
| `POST /api/venues/requests/{id}/cancel` | the requester (`booking.cancel`) | | `{request: request view}`; removes the booking override, so the room is free again |
| `POST /api/venues/slot-finder` | `slotfinder.use` (org, HOD, teacher, club, admin) | `{dept+year \| sections \| groups, duration, from?, to?, attendees?, needs}` | see below |

**venue** = `{id, kind, capacity, dept, building, building_name, floor, features, place}` (`place` = "Workshop Block, ground floor").
- In `venues`: `fits: true`, `reason` ("Seats 120 for 100 people · has projector and sound · also ac · MBA Block (CSE & IT), first floor"), `warnings` (other pending requests for the same slot, much bigger than needed), `pending_requests`. Order: no competing request first, then smallest capacity ≥ attendees, then more features, then building/floor.
- In `near_misses` (up to 6, fewest problems first): `fits: false`, `reason` ("Busy in P5: class TOC · D3 CS A · Too small: seats 75, you need 100 · No sound").

**Approval chain** (built when the request is made):
- A club lead's request goes to the club's faculty advisor (`STORE.clubs[club].advisor`, action `booking.endorse`), then the room's owner.
- Teacher, HOD, org and admin requests skip the advisor.
- The room's owner is `hod-<room.dept>` (`booking.approve`), or `admin` for central rooms (`dept=None`).
- If the requester *is* an approver, that step is pre-approved. For example, HOD CSE booking a CSE room is booked at once.
- Status: `pending` → `endorsed` (advisor said yes) → `approved`, or `rejected` / `cancelled`.
- The room is re-checked before the final approval.
- Final approval adds `Override(kind="booking", date, periods, room, title="<club>: <title>", ref=<request id>)`.
- Notifications (🔔):
  - the next approver gets one linking to `/venues.html#inbox`
  - the requester hears about endorse / approve / reject, linking to `/venues.html#requests`
  - the final approver hears when an approved booking is cancelled
  - if the request has an `audience` (group ids, filled by the slot finder's "Book this"), every student in those groups is told when it is approved ("📣 Event for your batch …") and if it is later cancelled. Unknown group ids get a 400.

**request view** = every `BookingRequest` field plus:
- `room_info` (venue), `requester_name`, `when` ("Fri 23 Oct, P5–P6 (12:30–2:30)")
- `waiting_for` ("Faculty advisor · Dr. X" / "HOD CSE (Dr. Y)"), `step_role` (`advisor|hod|admin|null`)
- `timeline`: `[{label, at, note?, state: done|current|todo|rejected}]`
- `can_decide`, `can_cancel`, `assigned_to_me`
- `competing`: ids of other waiting requests for the same room and time
- `audience_label`: e.g. "D4 CS A, D4 CS B (B1, B2)": whole sections by name, otherwise the section plus group letters. Empty when there is no audience.

**Slot finder**
- Audience: `dept` + `year` (every section of that year), `sections` (ids), or `groups` (atomic group ids). A class blocks a group if the group, or its section id, is in the class's `batches`.
- `duration` is 1–9 periods. `from` defaults to today and `to` to `from` + 13 days (at most 31 days). Weekends are skipped, and so are periods already started today.
- `attendees` defaults to the audience size (section sizes, or a share of one for single groups).

Returns:
- `audience`: `{label, groups, sections, attendees}`, plus `duration`, `from`, `to`, `needs`, `total`
- `slots` (up to 40): `[{date, day, periods, when, venues: [up to 3 fitting venues], warnings}]`
  - Every group in the audience is free for the whole block.
  - Order: by date; slots with a venue first; slots that don't take a lunch break first; then earliest.
  - `warnings` can include "Uses the only lunch break left for …" (only when it takes a group's last free period in the lunch window) and "No free venue fits".
- `almost` (up to 6, only when there are fewer than 10 exact slots): nearly-free times, fewest sections and groups busy first. Same fields, plus `missing: [{section, groups, whole, classes}]` (who would miss which class) and a warning like "20 of 36 groups in 6 sections have class then".
- `days_without_slot`: `["Thu 22 Oct", …]`

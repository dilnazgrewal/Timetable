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

**`Occupancy`** has these fields:
- `key`, `kind` (`"class"` or `"booking"`), `day`, `start`, `duration`, `slots`
- `room`, `teacher`, `batches`, `lesson`, `title`
- `status` (`normal`, `substituted` or `room_changed`)

**Domain types** are in `app/models.py`: `Room` (with `building`, `floor`, `features`, `sittable`, `bookable`), `Building`, `Override`, `User`, `Club`, `BookingRequest`, `ApprovalStep`, `MeetingRequest`, `Notification` and `FEATURES`.

**Permission actions that already exist:**
`timetable.view`, `timetable.generate`, `override.create`, `booking.request`, `booking.cancel`, `booking.endorse`, `booking.approve`, `slotfinder.use`, `meeting.request`, `meeting.reply`, `demo.reset`, `rooms.view`, `chat.ask`

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
| `GET /api/timetable` | base timetable: `{ready, status, seconds, issues, metrics, baseline, entries:[entry view]}` |
| `GET /api/effective?on=YYYY-MM-DD` | `{date, weekday, items:[occupancy view]}` |
| `POST /api/generate?time_limit=30` | regenerate (needs `timetable.generate`) |
| `GET /api/free-rooms` | free rooms (see below) |
| `GET /api/notifications` | `{items, unread}` for the caller |
| `POST /api/notifications/read` | marks all of the caller's notifications read |
| `POST /api/chat` | `{answer, tools_used}` |
| `POST /api/demo/reset` | clears overrides, requests and notifications (admin only) |

**`/api/free-rooms` parameters:**
- `period` (required)
- either `day` (0–4, weekly template) or `on` (YYYY-MM-DD, includes bookings and cancellations)
- optional filters: `min_capacity`, `kind`, `sittable_only=true`, `building`, `floor`
- Each returned room has all `Room` fields plus `free_until`. Rooms come sorted by building, then floor (ground first), then classrooms first.

## Lane B: Dashboards (`app/api/dashboards.py`, prefix `/api/dash`)
Owned by the Dashboards session. These are the planned endpoints; document what you actually build here.
- `GET /api/dash/views?dept=&year=&section=&group=&teacher=&room=&on=` returns a filtered timetable (week or date).
- `GET /api/dash/teacher/{teacher_id}/free?on=` returns the teacher's free periods (not teaching, available).
- `POST /api/dash/meetings` with `{teacher, date, period, note}` (needs `meeting.request`).
- `GET /api/dash/meetings` returns the caller's meetings: sent if student, received if teacher.
- `POST /api/dash/meetings/{id}/reply` with `{status: accepted|declined, reply}` (needs `meeting.reply`). It notifies the student.
- `GET /api/dash/now?on=&period=` returns the caller's now / next card.

## Lane C: Venues and events (`app/api/venues.py`, prefix `/api/venues`)
Owned by the Venues session. These are the planned endpoints; document what you actually build here.
- `GET /api/venues` returns bookable rooms with features, building, floor and capacity.
- `POST /api/venues/rank` with `{date, periods, attendees, needs}` returns ranked free venues with reasons.
- `POST /api/venues/requests` with `{title, purpose, club, attendees, needs, date, periods, room}` (needs `booking.request`). It builds the approval steps (advisor → HOD, or → admin for central rooms) and notifies the first approver.
- `GET /api/venues/requests?mine=1|inbox=1` returns my requests, or the ones waiting for me.
- `POST /api/venues/requests/{id}/decide` with `{decision: approved|rejected, note}`. It checks `booking.endorse` or `booking.approve` for the current step. Final approval calls `STORE.add_override(kind="booking")` and notifies the requester.
- `POST /api/venues/requests/{id}/cancel` removes the booking override if one exists.
- `POST /api/venues/slot-finder` with `{groups|dept+year, duration, from, to, attendees, needs}` returns slots where every chosen group is free, plus venues that fit.

# Cross-lane requests

This file is append-only. If you need a change in a file another lane owns, add an entry here instead of editing their file. The owning lane picks it up, then marks it done.

Format: `- [ ] YYYY-MM-DD · from Lane X → Lane Y · file · what you need and why`

- [x] 2026-10-22 · from Lane A → all · foundation is in place: store, auth, routers, shell, API contract
- [x] 2026-10-22 · from Lane A → all · **Real GNDEC CSE timetable is live** (imported from FET): CSE sections are now `D1..D4-CS-<A-F>` (+ `M1-CS`, `M3-CS`, `PHD-CS`) with groups like `D3-CS-A-A1`; seed departments use `D2-IT-A`, `D3-ME-B` … with groups `…-A1/-A2`. Student accounts `s-<group>`; real CSE teachers have FET ids (e.g. `KD`, `DS`, `AS-Pragya`). 9 periods (P9 16:30–17:30). Real rooms: G12–G18, S202–S219, F105/F107, labs `SL-I LAB` …, central `WS SEMINAR HALL`. Don't hard-code ids in tests.
- [ ] 2026-10-22 · from Lane A → Lane B · `app/api/dashboards.py` · `Occupancy.co_teachers` now lists the other teachers in a room (labs have 2–3). Please treat a teacher as busy if `teacher == id or id in co_teachers` (teacher view, free slots, now/next).
- [ ] 2026-10-22 · from Lane A → Lane B · `index.html` · `/api/timetable` now also returns `notes` (quality notes: `NO LUNCH …`, `LONG DAY …`, kept separate from `issues`, which are hard clashes) and `compare` = `{real, generated}` metrics (`idle_per_day`, `lonely_days`, `no_lunch_days`, `long_days`, `group_days`). Pitch-worthy panel: "GNDEC's real CSE timetable: 0 clashes ✔ but 21 group-days without lunch and 133 days over 6 periods. Our generated timetable: 0 of each."

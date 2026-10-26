"""Single shared store: the base weekly timetable, date-specific overrides, people and requests.

Every lane reads and writes through STORE (never its own globals):
- STORE.week()            -> list[Occupancy] for the base weekly timetable (all days)
- STORE.effective(date)   -> list[Occupancy] for one real date = base ⊕ that date's overrides
- STORE.add_override(o)   -> e.g. an approved booking; it then shows up in effective(date)
- STORE.bookings / meetings / notifications / users / clubs, STORE.notify(...), STORE.save()

Persistence: data/solution.json (base timetable, written by generation/import) and
data/state.json (overrides, requests, notifications). Both are plain JSON.
"""
from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

from app.models import (DAYS, ApprovalStep, BookingRequest, Club, College, Entry, MeetingRequest,
                        Notification, Override, User)
from app.validator import metrics, split_issues, validate

ROOT = Path(__file__).resolve().parent.parent
SOLUTION = ROOT / "data" / "solution.json"
OPTIMISED = ROOT / "data" / "gndec" / "cse_optimised.json"
STATE = ROOT / "data" / "state.json"


@dataclass
class Occupancy:
    """One thing happening in one room for a block of periods on one day (a class or a booking)."""
    key: str  # entry key "<lesson>#<session>" or override id for bookings
    kind: str  # "class" | "booking"
    day: int
    start: int
    duration: int
    room: str
    teacher: str | None = None
    batches: list[str] = field(default_factory=list)
    lesson: str | None = None
    title: str = ""
    status: str = "normal"  # normal | substituted | room_changed
    co_teachers: list[str] = field(default_factory=list)  # other teachers in the room (labs)

    @property
    def slots(self) -> range:
        return range(self.start, self.start + self.duration)


def entry_key(e: Entry) -> str:
    return f"{e.lesson}#{e.session}"


def to_date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class Store:
    def __init__(self, college: College) -> None:
        self.college = college
        self.lock = threading.RLock()
        self.result: dict | None = None  # status, seconds, metrics, issues, baseline, ...
        self.entries: list[Entry] = []
        self.overrides: list[Override] = []
        self.bookings: list[BookingRequest] = []
        self.meetings: list[MeetingRequest] = []
        self.notifications: list[Notification] = []
        self.users: dict[str, User] = {}
        self.clubs: dict[str, Club] = {}
        self.audit: list[dict] = []  # privileged actions, allowed or refused (written by app.auth.require)
        self.published: dict[str, dict] = {}  # dept -> {status: proposed|published, by, at, ...}

    # --- base timetable ----------------------------------------------------------------------
    def publish(self, raw: dict) -> dict:
        """Install a base timetable. Always re-validated by the independent checker.
        Imported (real) placements always come from the import itself, never from the saved file, so a
        re-import can't leave stale or missing classes behind."""
        with self.lock:
            generated = [Entry(**e) for e in raw["entries"]
                         if (l := self.college.lesson_by_id.get(e["lesson"])) is not None and not l.fixed]
            entries = generated + self.imported_entries()
            raw["entries"] = [asdict(e) for e in entries]
            raw["issues"], raw["notes"] = split_issues(validate(self.college, entries))
            raw["metrics"] = metrics(self.college, entries)
            if any(l.fixed for l in self.college.lessons):  # real (imported) vs generated departments
                raw["compare"] = {k: {m: v for m, v in metrics(self.college, entries, fixed=f).items() if m != "teacher_load"}
                                  for k, f in (("real", True), ("generated", False))}
            self.result, self.entries = raw, entries
            return raw

    def save_solution(self, raw: dict) -> None:
        SOLUTION.parent.mkdir(exist_ok=True)
        SOLUTION.write_text(json.dumps(raw))
        self.publish(raw)

    def _occ(self, e: Entry) -> Occupancy:
        l = self.college.lesson_by_id[e.lesson]
        return Occupancy(entry_key(e), "class", e.day, e.start, e.duration, e.room, l.teacher,
                         list(l.batches), l.id, f"{l.code} · {l.section}", co_teachers=list(l.co_teachers))

    def week(self) -> list[Occupancy]:
        return [self._occ(e) for e in self.entries]

    def effective(self, on: str | date) -> list[Occupancy]:
        """What actually happens on a real date: base entries for that weekday ⊕ that date's overrides."""
        d = to_date(on)
        wd = d.weekday()
        if wd >= len(DAYS):
            return []
        occ = {o.key: o for o in (self._occ(e) for e in self.entries if e.day == wd)}
        for ov in (o for o in self.overrides if o.date == d.isoformat()):
            if ov.kind == "cancel":
                occ.pop(ov.entry_key or "", None)
            elif ov.kind == "substitute" and ov.entry_key in occ:
                occ[ov.entry_key].teacher, occ[ov.entry_key].status = ov.teacher, "substituted"
            elif ov.kind == "room_change" and ov.entry_key in occ and ov.room:
                occ[ov.entry_key].room, occ[ov.entry_key].status = ov.room, "room_changed"
            elif ov.kind == "booking" and ov.room and ov.periods:
                start = min(ov.periods)
                occ[ov.id] = Occupancy(ov.id, "booking", wd, start, max(ov.periods) - start + 1, ov.room,
                                       title=ov.title)
        return sorted(occ.values(), key=lambda o: (o.start, o.room))

    def attends(self, student_type: str, o: Occupancy) -> bool:
        """Does a student of this type sit in this class? (bookings: if their section is in the audience)"""
        t = self.college.type_by_id.get(student_type)
        if t is None:
            return False
        if o.lesson:
            return o.lesson in t.lesson_set
        return any(b.startswith(t.section + "-") for b in o.batches)

    def busy_rooms(self, occupancies: list[Occupancy], period: int) -> dict[str, Occupancy]:
        return {o.room: o for o in occupancies if period in o.slots}

    # --- date-specific changes, people and requests -------------------------------------------
    def add_override(self, ov: Override) -> Override:
        with self.lock:
            self.overrides.append(ov)
            self.save()
            return ov

    def notify(self, user: str, text: str, link: str = "") -> None:
        with self.lock:
            self.notifications.append(Notification(new_id("n"), user, text, link, now_iso()))
            self.save()

    # --- persistence -----------------------------------------------------------------------
    def save(self) -> None:
        with self.lock:
            STATE.parent.mkdir(exist_ok=True)
            STATE.write_text(json.dumps({
                "overrides": [asdict(o) for o in self.overrides],
                "bookings": [asdict(b) for b in self.bookings],
                "meetings": [asdict(m) for m in self.meetings],
                "notifications": [asdict(n) for n in self.notifications],
                "audit": self.audit,
                "published": self.published,
            }, indent=1))

    def load(self) -> None:
        if STATE.exists():  # first: which timetable is published decides what publish() installs
            try:
                raw = json.loads(STATE.read_text())
                self.audit = raw.get("audit", [])
                self.published = raw.get("published", {})
            except Exception:
                pass
        if SOLUTION.exists():
            try:
                self.publish(json.loads(SOLUTION.read_text()))
            except Exception:  # a broken cache must never stop the demo
                self.result, self.entries = None, []
        if STATE.exists():
            try:
                raw = json.loads(STATE.read_text())
                self.overrides = [Override(**o) for o in raw.get("overrides", [])]
                self.bookings = [BookingRequest(**{**b, "steps": [ApprovalStep(**s) for s in b.get("steps", [])]})
                                 for b in raw.get("bookings", [])]
                self.meetings = [MeetingRequest(**m) for m in raw.get("meetings", [])]
                self.notifications = [Notification(**n) for n in raw.get("notifications", [])]
            except Exception:
                pass

    # --- which version of an imported timetable is live -----------------------------------------
    def imported_entries(self) -> list[Entry]:
        """The college's own (imported) placements, with each department whose optimised version is published
        swapped in."""
        L = self.college.lesson_by_id
        entries = list(self.college.fixed_entries)
        for dept, info in self.published.items():
            if info.get("status") != "published":
                continue
            path = OPTIMISED.with_name(f"{dept.lower()}_optimised.json")
            try:
                new = [Entry(**e) for e in json.loads(path.read_text(encoding="utf-8"))["entries"]]
            except Exception:
                continue
            if all(e.lesson in L and L[e.lesson].dept == dept for e in new):
                entries = [e for e in entries if L[e.lesson].dept != dept] + new
        return entries

    def set_published(self, dept: str, info: dict | None) -> None:
        """Propose / publish / withdraw a department's optimised timetable, then re-install the base timetable."""
        with self.lock:
            if info is None:
                self.published.pop(dept, None)
            else:
                self.published[dept] = info
            if self.result:
                self.publish({k: v for k, v in self.result.items()})
            self.save()

    def reset_state(self) -> None:
        """Demo reset: drop all overrides, requests and notifications (keeps the base timetable)."""
        with self.lock:
            self.overrides, self.bookings, self.meetings, self.notifications = [], [], [], []
            self.save()


def build_store() -> Store:
    from app.auth import demo_people  # local import: auth builds users from the college
    from app.seed import build_college

    store = Store(build_college())
    store.users, store.clubs = demo_people(store.college)
    store.load()
    return store


STORE = build_store()

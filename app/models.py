"""Domain model (plain dataclasses). Shared by every lane; owned by Lane A."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
PERIODS = [
    ("P1", "08:30", "09:30"),
    ("P2", "09:30", "10:30"),
    ("P3", "10:30", "11:30"),
    ("P4", "11:30", "12:30"),
    ("P5", "12:30", "13:30"),
    ("P6", "13:30", "14:30"),
    ("P7", "14:30", "15:30"),
    ("P8", "15:30", "16:30"),
    ("P9", "16:30", "17:30"),  # GNDEC: mostly mentoring (MC); the generator does not use it
]
SOLVER_PERIODS = 8  # the generator only places classes in P1..P8 (8:30-4:30)
# Lunch is not a fixed slot: every batch and teacher gets at least one free period in this
# window each day (11:30–14:30), and the solver picks which one.
LUNCH_WINDOW = (3, 4, 5)
RUNS = [(0, len(PERIODS))]  # contiguous teaching runs [start, end); no fixed breaks
MAX_BATCH_PER_DAY = 6


def run_of(period: int) -> tuple[int, int] | None:
    for a, b in RUNS:
        if a <= period < b:
            return (a, b)
    return None


@dataclass
class Department:
    code: str
    name: str


@dataclass
class Building:
    id: str
    name: str
    floors: list[str]  # in order, e.g. ["Ground", "First", "Second"]


# Room.features vocabulary (used by venue ranking and filters)
FEATURES = ("projector", "ac", "sound", "computers", "smart_board", "stage")


@dataclass
class Room:
    id: str
    kind: str
    capacity: int
    dept: str | None = None  # None = owned centrally
    building: str = ""  # Building.id
    floor: str = ""  # one of Building.floors
    features: list[str] = field(default_factory=list)
    sittable: bool = True  # students may sit here in a free period (labs: False)
    bookable: bool = False  # can be requested for events (seminar halls, auditoriums, big rooms)


@dataclass
class Teacher:
    id: str
    name: str
    dept: str
    kind: str = "Regular"
    unavailable: list[tuple[int, int]] = field(default_factory=list)  # (day, period)
    max_per_day: int = 5


@dataclass
class Section:
    id: str  # GNDEC style: "D3-CS-A" (year D3, CSE, section A)
    dept: str
    year: int  # 1-4 = B.Tech D1-D4; 5 = M.Tech; 6 = PhD
    name: str  # display, e.g. "D3 CS A"
    size: int
    home_room: str
    groups: list[str] = field(default_factory=list)  # atomic student groups, e.g. "D3-CS-A-A1"
    kind: str = "section"  # "section", or "elective": an audience mixing students of several sections

    @property
    def batches(self) -> list[str]:
        return self.groups


@dataclass
class Lesson:
    """A teaching assignment: subject + teacher + audience, repeated `sessions` times a week."""
    id: str
    code: str
    name: str
    kind: str  # "theory" | "lab"
    dept: str
    teacher: str
    section: str
    batches: list[str]
    sessions: int
    duration: int
    room_kind: str
    rooms: list[str]  # candidate rooms
    size: int
    co_teachers: list[str] = field(default_factory=list)  # labs often have 2-3 teachers
    fixed: bool = False  # imported (e.g. from FET): the generator never moves it


@dataclass
class Entry:
    """A placed session."""
    lesson: str
    session: int
    day: int
    start: int
    duration: int
    room: str

    @property
    def slots(self) -> range:
        return range(self.start, self.start + self.duration)


@dataclass
class College:
    departments: list[Department]
    rooms: list[Room]
    teachers: list[Teacher]
    sections: list[Section]
    lessons: list[Lesson]
    buildings: list[Building] = field(default_factory=list)
    fixed_entries: list[Entry] = field(default_factory=list)  # placements of fixed (imported) lessons
    student_types: list["StudentType"] = field(default_factory=list)  # real combinations of students
    rules: list["Rule"] = field(default_factory=list)  # the college's own timetable rules (app/rules.py)

    def __post_init__(self) -> None:
        self.building_by_id = {b.id: b for b in self.buildings}
        self.room_by_id = {r.id: r for r in self.rooms}
        self.teacher_by_id = {t.id: t for t in self.teachers}
        self.section_by_id = {s.id: s for s in self.sections}
        self.lesson_by_id = {l.id: l for l in self.lessons}
        self.type_by_id = {t.id: t for t in self.student_types}

    def set_student_types(self, types: list["StudentType"]) -> None:
        self.student_types = types
        self.type_by_id = {t.id: t for t in types}

    def units(self) -> list[tuple[str, set[str]]]:
        """Who must never have two classes at once: every student type (real combination of choices).
        Without student types, every group is its own unit."""
        if self.student_types:
            return [(t.name, set(t.lessons)) for t in self.student_types]
        groups = sorted({b for l in self.lessons for b in l.batches})
        return [(g, {l.id for l in self.lessons if g in l.batches}) for g in groups]

    def guarded(self) -> list[tuple[str, set[str], set[str]]]:
        """(student type, its classes, electives that may share its students): a class of the type must never
        be at the same time as one of those electives (the electives themselves may run side by side)."""
        return [(t.name, set(t.lessons), set(t.guards)) for t in self.student_types if t.guards]

    def lab_pairs(self) -> list[tuple[str, str]]:
        """Pairs of labs one teacher gives to two groups of the same class: 'SC Lab A1' and 'SC Lab A2', or
        D2 CS B's OOP Lab for B1 and for B2. Teachers keep these on different days."""
        family: dict[tuple, list[str]] = {}
        for l in self.lessons:
            if l.kind == "lab":
                key = (l.teacher, re.sub(r"\s+[A-Z]\d$", "", l.code), frozenset(b.rsplit("-", 1)[0] for b in l.batches))
                family.setdefault(key, []).append(l.id)
        return [(a, b) for ids in family.values() for i, a in enumerate(ids) for b in ids[i + 1:]]


# --- date-specific layer, people and requests (v2) ---------------------------------------------
# Everything below is persisted by app/store.py. Dates are ISO strings ("2026-10-23").

@dataclass
class Override:
    """A one-off change for a single date. effective(date) = base timetable ⊕ that date's overrides."""
    id: str
    date: str
    kind: str  # "cancel" | "substitute" | "room_change" | "booking"
    periods: list[int] = field(default_factory=list)  # booking: periods occupied
    entry_key: str | None = None  # "<lesson>#<session>" for cancel / substitute / room_change
    room: str | None = None  # room_change: new room; booking: booked room
    teacher: str | None = None  # substitute: new teacher id
    title: str = ""  # shown in grids, e.g. "DMC: Digital Marketing Workshop"
    ref: str | None = None  # id of the BookingRequest / leave that created it
    created_by: str = ""


@dataclass
class User:
    """Demo account. role: student | teacher | hod | admin | club | org."""
    id: str
    name: str
    role: str
    dept: str | None = None
    group: str | None = None  # student: their actual group's id, e.g. "D4-CS-A-A2" (NOT enough to know their classes)
    teacher_id: str | None = None  # teacher / hod: their Teacher.id
    club: str | None = None  # club lead: Club.id
    student_type: str | None = None  # student: StudentType.id = their real combination; use this for "my timetable"
    section: str | None = None  # student: Section.id


@dataclass
class Club:
    id: str
    name: str
    advisor: str  # User.id of the faculty advisor
    dept: str | None = None


@dataclass
class ApprovalStep:
    role: str  # "advisor" | "hod" | "admin"
    approver: str  # User.id
    decision: str | None = None  # None (waiting) | "approved" | "rejected"
    note: str = ""
    at: str | None = None


@dataclass
class BookingRequest:
    id: str
    title: str
    requester: str  # User.id
    club: str | None
    attendees: int
    needs: list[str]  # subset of FEATURES
    date: str
    periods: list[int]
    room: str
    status: str = "pending"  # pending | endorsed | approved | rejected | cancelled
    steps: list[ApprovalStep] = field(default_factory=list)
    created_at: str = ""
    purpose: str = ""
    audience: list[str] = field(default_factory=list)  # group ids the event is for (e.g. from the slot finder)


@dataclass
class MeetingRequest:
    id: str
    student: str  # User.id
    teacher: str  # Teacher.id
    date: str
    period: int
    note: str = ""
    status: str = "pending"  # pending | accepted | declined
    reply: str = ""
    created_at: str = ""


@dataclass
class Notification:
    id: str
    user: str  # User.id
    text: str
    link: str = ""  # e.g. "/venues.html#requests"
    at: str = ""
    read: bool = False


@dataclass
class StudentType:
    """A combination of choices real students have (e.g. D4 CS A · A2 · CV · SC (A1 group) · TA A3) and the
    exact classes they attend. Built from the department's distribution lists where groups are not simply
    lab groups (GNDEC 3rd/4th year); elsewhere one type per group. count = students with this combination."""
    id: str
    section: str
    name: str
    lessons: list[str]
    count: int = 0
    details: dict = field(default_factory=dict)
    # classes that may share students with this type although we can't tell (an elective or minor course of the
    # same year with no student lists): never put at the same time, but not shown as "my" classes
    guards: list[str] = field(default_factory=list)

    @property
    def lesson_set(self) -> set[str]:
        return set(self.lessons)

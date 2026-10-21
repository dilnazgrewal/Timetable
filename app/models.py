"""Domain model for the P0 prototype (plain dataclasses; becomes SQLModel tables in P1)."""
from __future__ import annotations

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
]
# Lunch is not a fixed slot: every batch and teacher gets at least one free period in this
# window each day (11:30–14:30), and the solver picks which one.
LUNCH_WINDOW = (3, 4, 5)
RUNS = [(0, 8)]  # contiguous teaching runs [start, end); no fixed breaks
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
class Room:
    id: str
    kind: str
    capacity: int
    dept: str | None = None  # None = owned centrally


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
    id: str  # e.g. "CSE-3A"
    dept: str
    year: int
    name: str
    size: int
    home_room: str

    @property
    def batches(self) -> list[str]:
        return [f"{self.id}-G1", f"{self.id}-G2"]


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

    def __post_init__(self) -> None:
        self.room_by_id = {r.id: r for r in self.rooms}
        self.teacher_by_id = {t.id: t for t in self.teachers}
        self.section_by_id = {s.id: s for s in self.sections}
        self.lesson_by_id = {l.id: l for l in self.lessons}

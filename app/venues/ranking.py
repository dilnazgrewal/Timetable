"""Venue ranking: which bookable rooms are free for a block of periods on a date, and how well they fit."""
from __future__ import annotations

from datetime import date

from fastapi import HTTPException

from app.models import FEATURES, PERIODS, Room
from app.store import Occupancy
from app.venues.common import floor_rank, nice_list, place_label, room_view, store

ACTIVE = ("pending", "endorsed")  # requests still waiting for a decision
NEAR_MISSES = 6


def check_needs(needs: list[str]) -> list[str]:
    unknown = [n for n in needs if n not in FEATURES]
    if unknown:
        raise HTTPException(400, f"Unknown requirement {nice_list(unknown)}. Choose from {nice_list(list(FEATURES))}.")
    return list(dict.fromkeys(needs))


def conflicts(room: str, occ: list[Occupancy], periods: list[int]) -> list[Occupancy]:
    """Everything already in `room` during any of `periods` (classes after overrides, and bookings)."""
    s = store()
    found: dict[str, Occupancy] = {}
    for p in periods:
        o = s.busy_rooms(occ, p).get(room)
        if o:
            found.setdefault(o.key, o)
    return list(found.values())


def busy_reason(o: Occupancy) -> str:
    when = PERIODS[o.start][0] if o.duration == 1 else f"{PERIODS[o.start][0]}–{PERIODS[o.start + o.duration - 1][0]}"
    what = f"booked for {o.title}" if o.kind == "booking" else f"class {o.title}"
    return f"Busy in {when}: {what}"


def competing(room: str, on: str, periods: list[int], skip: str | None = None) -> list:
    """Other requests still waiting for approval that want the same room at an overlapping time."""
    return [b for b in store().bookings
            if b.status in ACTIVE and b.room == room and b.date == on and b.id != skip and set(b.periods) & set(periods)]


def fit_reason(room: Room, attendees: int, needs: list[str]) -> str:
    parts = [f"Seats {room.capacity} for {attendees} {'person' if attendees == 1 else 'people'}"]
    if needs:
        parts.append(f"has {nice_list(needs)}")
    extra = [f for f in room.features if f not in needs]
    if extra:
        parts.append(f"also {nice_list(extra)}")
    parts.append(place_label(room))
    return " · ".join(parts)


def rank(d: date, periods: list[int], attendees: int, needs: list[str], occ: list[Occupancy] | None = None) -> dict:
    """Free bookable rooms that fit, best first, plus the closest rooms that don't (and why)."""
    s = store()
    on = d.isoformat()
    occ = s.effective(d) if occ is None else occ
    fits, misses = [], []
    for room in s.college.rooms:
        if not room.bookable:
            continue
        busy = conflicts(room.id, occ, periods)
        missing = [n for n in needs if n not in room.features]
        small = room.capacity < attendees
        if not busy and not missing and not small:
            others = competing(room.id, on, periods)
            warnings = []
            if others:
                n = len(others)
                warnings.append(f"{n} other request{'s' if n > 1 else ''} for this room and time "
                                f"{'are' if n > 1 else 'is'} waiting for approval")
            if room.capacity >= 3 * max(attendees, 20):
                warnings.append(f"Much bigger than you need ({room.capacity} seats)")
            fits.append({**room_view(room), "fits": True, "reason": fit_reason(room, attendees, needs),
                         "warnings": warnings, "pending_requests": len(others),
                         "_key": (len(others) > 0, room.capacity - attendees, room.building, floor_rank(room), room.id)})
            continue
        why = [busy_reason(o) for o in busy]
        if small:
            why.append(f"Too small: seats {room.capacity}, you need {attendees}")
        if missing:
            why.append(f"No {nice_list(missing)}")
        problems = len(why)
        misses.append({**room_view(room), "fits": False, "reason": " · ".join(why),
                       "_key": (problems, abs(room.capacity - attendees), room.id)})
    fits.sort(key=lambda v: v["_key"])
    misses.sort(key=lambda v: v["_key"])
    for v in fits + misses:
        del v["_key"]
    return {"date": on, "periods": periods, "attendees": attendees, "needs": needs,
            "venues": fits, "near_misses": misses[:NEAR_MISSES]}

"""Small helpers shared by the venues lane: reading STORE, dates and plain-English labels."""
from __future__ import annotations

from datetime import date

from fastapi import HTTPException

import app.store as store_mod
from app.models import DAYS, PERIODS, Room
from app.store import Store


def store() -> Store:
    """The shared STORE, looked up at call time so tests can swap it."""
    return store_mod.STORE


def parse_date(value: str, allow_past: bool = False) -> date:
    try:
        d = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise HTTPException(400, f"'{value}' is not a date. Use YYYY-MM-DD, e.g. 2026-10-23.")
    if d.weekday() >= len(DAYS):
        raise HTTPException(400, f"{day_label(d)} is a weekend. Venues can be booked Monday to Friday.")
    if not allow_past and d < date.today():
        raise HTTPException(400, f"{day_label(d)} is in the past. Pick today or a later date.")
    return d


def check_periods(periods: list[int]) -> list[int]:
    """Periods must be valid and back to back (one continuous block)."""
    ps = sorted(set(periods))
    if not ps:
        raise HTTPException(400, "Pick at least one period.")
    if ps[0] < 0 or ps[-1] >= len(PERIODS):
        raise HTTPException(400, f"Periods must be between P1 and P{len(PERIODS)}.")
    if ps != list(range(ps[0], ps[-1] + 1)):
        raise HTTPException(400, "Pick periods that are back to back, e.g. P5 and P6.")
    return ps


def day_label(d: date | str) -> str:
    d = d if isinstance(d, date) else date.fromisoformat(d)
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"


def periods_label(periods: list[int]) -> str:
    a, b = min(periods), max(periods)
    name = PERIODS[a][0] if a == b else f"{PERIODS[a][0]}–{PERIODS[b][0]}"
    return f"{name} ({clock(PERIODS[a][1])}–{clock(PERIODS[b][2])})"


def clock(hhmm: str) -> str:
    """'13:30' -> '1:30', '08:30' -> '8:30' (college timetables use 12-hour times without am/pm)."""
    h, m = hhmm.split(":")
    h = int(h) % 12 or 12
    return f"{h}:{m}"


def nice_list(items: list[str]) -> str:
    items = [i.replace("_", " ") for i in items]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def place_label(room: Room) -> str:
    b = store().college.building_by_id.get(room.building)
    where = b.name if b else room.building
    return f"{where}, {room.floor.lower()} floor" if room.floor else where


def room_view(room: Room) -> dict:
    b = store().college.building_by_id.get(room.building)
    return {"id": room.id, "kind": room.kind, "capacity": room.capacity, "dept": room.dept,
            "building": room.building, "building_name": b.name if b else room.building, "floor": room.floor,
            "features": list(room.features), "place": place_label(room)}


def floor_rank(room: Room) -> int:
    b = store().college.building_by_id.get(room.building)
    return b.floors.index(room.floor) if b and room.floor in b.floors else 99

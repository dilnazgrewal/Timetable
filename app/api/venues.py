"""Lane C (Venues and events): venue ranking, booking requests, approvals, event slot finder.

Owned by the Venues session. Business logic lives in app/venues/*.py; this file only maps HTTP to it.
Keep every route under /api/venues. See docs/API.md (Lane C section).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import current_user, require
from app.models import User
from app.venues import ranking, requests, slots
from app.venues.common import check_periods, parse_date, room_view, store

router = APIRouter(prefix="/api/venues", tags=["venues"])


class RankBody(BaseModel):
    date: str
    periods: list[int]
    attendees: int = Field(ge=1)
    needs: list[str] = []


class RequestBody(BaseModel):
    title: str
    purpose: str = ""
    club: str | None = None
    attendees: int = Field(ge=1)
    needs: list[str] = []
    date: str
    periods: list[int]
    room: str


class SlotBody(BaseModel):
    dept: str | None = None
    year: int | None = None
    sections: list[str] = []
    groups: list[str] = []
    duration: int = 2
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    attendees: int | None = Field(default=None, ge=1)
    needs: list[str] = []


class DecideBody(BaseModel):
    decision: str  # approved | rejected
    note: str = ""


@router.get("")
def venues(user: User = Depends(current_user)) -> dict:
    """Every bookable room with capacity, features, building and floor."""
    rooms = [room_view(r) for r in store().college.rooms if r.bookable]
    rooms.sort(key=lambda r: (-r["capacity"], r["id"]))
    return {"venues": rooms}


@router.post("/rank")
def rank(body: RankBody, user: User = Depends(current_user)) -> dict:
    d = parse_date(body.date)
    return ranking.rank(d, check_periods(body.periods), body.attendees, ranking.check_needs(body.needs))


@router.post("/requests")
def create_request(body: RequestBody, user: User = Depends(current_user)) -> dict:
    d = parse_date(body.date)
    req, warnings = requests.create(user, body.title, body.purpose, body.club, body.attendees,
                                    ranking.check_needs(body.needs), d.isoformat(), check_periods(body.periods),
                                    body.room)
    return {"request": requests.view(req, user), "warnings": warnings}


@router.get("/requests")
def list_requests(inbox: int = 0, mine: int = 0, all: int = 0, user: User = Depends(current_user)) -> dict:
    """mine=1 (default): requests I made · inbox=1: waiting for my decision · all=1: everything (admin)."""
    reqs = requests.listing(user, inbox=bool(inbox), everything=bool(all))
    return {"items": [requests.view(r, user) for r in reqs]}


@router.post("/requests/{req_id}/decide")
def decide(req_id: str, body: DecideBody, user: User = Depends(current_user)) -> dict:
    return {"request": requests.view(requests.decide(user, req_id, body.decision, body.note), user)}


@router.post("/requests/{req_id}/cancel")
def cancel(req_id: str, user: User = Depends(current_user)) -> dict:
    return {"request": requests.view(requests.cancel(user, req_id), user)}


@router.post("/slot-finder")
def slot_finder(body: SlotBody, user: User = Depends(current_user)) -> dict:
    """Times when every group in the audience is free, earliest first, each with the best-fit free venues."""
    require(user, "slotfinder.use")
    aud = slots.audience(body.dept, body.year, body.sections, body.groups)
    return slots.find(aud, body.duration, body.from_, body.to, body.attendees, ranking.check_needs(body.needs))


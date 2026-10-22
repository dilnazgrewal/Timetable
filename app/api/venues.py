"""Lane C (Venues and events): venue ranking, booking requests, approvals, event slot finder.

Owned by the Venues session. Business logic lives in app/venues/*.py; this file only maps HTTP to it.
Keep every route under /api/venues. See docs/API.md (Lane C section).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import current_user
from app.models import User
from app.venues import ranking
from app.venues.common import check_periods, parse_date, room_view, store

router = APIRouter(prefix="/api/venues", tags=["venues"])


class RankBody(BaseModel):
    date: str
    periods: list[int]
    attendees: int = Field(ge=1)
    needs: list[str] = []


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


@router.get("/ping")
def ping(user: User = Depends(current_user)) -> dict:
    return {"lane": "venues", "user": user.id}

"""Lane C (Venues and events): venue ranking, booking requests, approvals, event slot finder.

Owned by the Venues session. Business logic goes in app/venues/*.py; this file only maps HTTP to it.
Read data through app.store.STORE, persist requests in STORE.bookings + STORE.save(), turn an approved
booking into an Override(kind="booking") with STORE.add_override(), notify with STORE.notify(), and
check permissions with app.auth.require(). Keep every route under /api/venues. See docs/API.md.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import current_user
from app.models import User

router = APIRouter(prefix="/api/venues", tags=["venues"])


@router.get("/ping")
def ping(user: User = Depends(current_user)) -> dict:
    return {"lane": "venues", "user": user.id}

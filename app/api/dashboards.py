"""Lane B (Dashboards UI): role dashboards, filtered views, teacher free slots, meeting requests.

Owned by the Dashboards session. Read data through app.store.STORE (week() / effective(date)),
check permissions with app.auth.require(), and keep every route under /api/dash.
See docs/API.md for the contract.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import current_user
from app.models import User

router = APIRouter(prefix="/api/dash", tags=["dashboards"])


@router.get("/ping")
def ping(user: User = Depends(current_user)) -> dict:
    return {"lane": "dashboards", "user": user.id}

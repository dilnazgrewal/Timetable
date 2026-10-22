"""Event slot finder: times when every group in an audience is free on real dates, each with venues that fit.

An audience is a department + year, a list of sections, or a list of atomic groups. A slot is a run of
`duration` periods on one weekday where no class (after cancellations, substitutions and room changes)
involves any of those groups.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import HTTPException

from app.models import LUNCH_WINDOW, PERIODS
from app.venues import ranking
from app.venues.common import day_label, periods_label, store

MAX_DAYS = 31
MAX_SLOTS = 40
VENUES_PER_SLOT = 3


def audience(dept: str | None, year: int | None, sections: list[str], groups: list[str]) -> dict:
    """Resolve the chosen audience to atomic groups (plus section ids, in case a class lists a whole section)."""
    c = store().college
    if groups:
        owner = {g: s for s in c.sections for g in s.batches}
        unknown = [g for g in groups if g not in owner]
        if unknown:
            raise HTTPException(400, f"Unknown group {', '.join(unknown)}")
        chosen = list(dict.fromkeys(groups))
        size = sum(owner[g].size / max(len(owner[g].batches), 1) for g in chosen)
        return {"label": ", ".join(chosen), "groups": chosen, "sections": [], "attendees": round(size)}
    if sections:
        unknown = [s for s in sections if s not in c.section_by_id]
        if unknown:
            raise HTTPException(400, f"Unknown section {', '.join(unknown)}")
        secs = [c.section_by_id[s] for s in dict.fromkeys(sections)]
        label = ", ".join(s.name for s in secs)
    elif dept and year:
        secs = [s for s in c.sections if s.dept == dept and s.year == year]
        if not secs:
            raise HTTPException(400, f"No {dept} sections in year {year}.")
        label = f"{dept} year {year} ({len(secs)} section{'s' if len(secs) > 1 else ''})"
    else:
        raise HTTPException(400, "Choose who the event is for: a department and year, sections, or groups.")
    return {"label": label, "groups": [g for s in secs for g in s.batches], "sections": [s.id for s in secs],
            "attendees": sum(s.size for s in secs)}


def as_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, f"'{value}' is not a date. Use YYYY-MM-DD, e.g. 2026-10-23.")


def busy_by_group(occ, members: set[str]) -> dict[str, set[int]]:
    """For each audience member (group or section id), the periods it has a class."""
    busy: dict[str, set[int]] = {m: set() for m in members}
    for o in occ:
        for b in o.batches:
            if b in busy:
                busy[b].update(o.slots)
    return busy


def lunch_warning(busy: dict[str, set[int]], groups: list[str], slot: set[int]) -> str | None:
    """Lunch is flexible: each group needs one free period in the lunch window. Don't eat the last one."""
    hungry = [g for g in groups if not (set(LUNCH_WINDOW) - busy.get(g, set()) - slot)]
    if not hungry:
        return None
    who = hungry[0] if len(hungry) == 1 else f"{len(hungry)} groups"
    return f"Uses the only lunch break left for {who}"


def find(aud: dict, duration: int, start: str, end: str, attendees: int | None, needs: list[str]) -> dict:
    if not 1 <= duration <= len(PERIODS):
        raise HTTPException(400, f"Duration must be 1 to {len(PERIODS)} periods.")
    first = max(as_date(start) or date.today(), date.today())
    last = as_date(end) or first + timedelta(days=13)
    if last < first:
        raise HTTPException(400, "The end date is before the start date (or in the past).")
    if (last - first).days >= MAX_DAYS:
        raise HTTPException(400, f"Search up to {MAX_DAYS} days at a time.")
    people = attendees or aud["attendees"]
    section_of = {g: s.id for s in store().college.sections for g in s.batches}
    owner = {g: section_of[g] for g in aud["groups"] if g in section_of}
    members = set(aud["groups"]) | set(owner.values())
    slots, days_without = [], []
    today, now = date.today(), datetime.now().strftime("%H:%M")
    d = first
    while d <= last:
        if d.weekday() < 5:
            occ = store().effective(d)
            busy = busy_by_group(occ, members)
            for g, sid in owner.items():  # a class for the whole section blocks each of its groups
                busy[g] |= busy.get(sid, set())
            taken = set().union(*busy.values()) if busy else set()
            found_today = False
            for p in range(len(PERIODS) - duration + 1):
                block = list(range(p, p + duration))
                if taken & set(block) or (d == today and PERIODS[p][1] <= now):
                    continue
                found_today = True
                venues = ranking.rank(d, block, people, needs, occ)["venues"][:VENUES_PER_SLOT]
                warn = lunch_warning(busy, aud["groups"], set(block))
                slots.append({"date": d.isoformat(), "day": day_label(d), "periods": block,
                              "when": f"{day_label(d)}, {periods_label(block)}", "venues": venues,
                              "warnings": [w for w in (warn,) if w] + ([] if venues else ["No free venue fits"]),
                              "_key": (d, not venues, bool(warn), p)})
            if not found_today:
                days_without.append(day_label(d))
        d += timedelta(days=1)
    slots.sort(key=lambda s: s["_key"])
    for s in slots:
        del s["_key"]
    return {"audience": {**aud, "attendees": people}, "duration": duration, "from": first.isoformat(),
            "to": last.isoformat(), "needs": needs, "total": len(slots), "slots": slots[:MAX_SLOTS],
            "days_without_slot": days_without}


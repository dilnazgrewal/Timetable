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
ALMOST = 6  # nearly-free times shown when few exact slots exist


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


def busy_by_group(occ, members: set[str]) -> dict[str, dict[int, str]]:
    """For each audience member (group or section id): period -> the class it has then."""
    busy: dict[str, dict[int, str]] = {m: {} for m in members}
    for o in occ:
        for b in o.batches:
            if b in busy:
                busy[b].update({p: o.title for p in o.slots})
    return busy


def lunch_warning(busy: dict[str, dict[int, str]], groups: list[str], slot: set[int]) -> str | None:
    """Lunch is flexible: each group needs one free period in the lunch window. Don't take its last one."""
    lunch = set(LUNCH_WINDOW)
    hungry = [g for g in groups if (lunch - busy[g].keys()) and not (lunch - busy[g].keys() - slot)]
    if not hungry:
        return None
    who = hungry[0] if len(hungry) == 1 else f"{len(hungry)} groups"
    return f"Uses the only lunch break left for {who}"


def by_section(clash: dict[str, list[str]]) -> list[dict]:
    """Who would miss class, folded by section: [{section, groups, whole, classes}], most groups first."""
    c = store().college
    out: dict[str, dict] = {}
    for g, classes in clash.items():
        sec = next((s for s in c.sections if g in s.batches), None)
        key = sec.id if sec else g
        row = out.setdefault(key, {"section": sec.name if sec else g, "groups": [], "classes": [],
                                   "size": len(sec.batches) if sec else 1})
        row["groups"].append(g)
        row["classes"] += [x for x in classes if x not in row["classes"]]
    for r in out.values():
        r["whole"] = len(r["groups"]) == r.pop("size")
    rows = list(out.values())
    return sorted(rows, key=lambda r: -len(r["groups"]))


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
    groups = aud["groups"]
    section_of = {g: s.id for s in store().college.sections for g in s.batches}
    owner = {g: section_of[g] for g in groups if g in section_of}
    members = set(groups) | set(owner.values())
    slots, almost, days_without = [], [], []
    occ_by_day = {}
    today, now = date.today(), datetime.now().strftime("%H:%M")
    d = first
    while d <= last:
        if d.weekday() < 5:
            occ_by_day[d] = occ = store().effective(d)
            busy = busy_by_group(occ, members)
            for g, sid in owner.items():  # a class for the whole section blocks each of its groups
                busy[g] = {**busy.get(sid, {}), **busy[g]}
            found_today = False
            for p in range(len(PERIODS) - duration + 1):
                block = list(range(p, p + duration))
                if d == today and PERIODS[p][1] <= now:
                    continue
                clash = {g: sorted({busy[g][q] for q in block if q in busy[g]}) for g in groups}
                clash = {g: c for g, c in clash.items() if c}
                slot = {"date": d.isoformat(), "day": day_label(d), "periods": block,
                        "when": f"{day_label(d)}, {periods_label(block)}"}
                if clash:
                    missing = by_section(clash)
                    almost.append({**slot, "missing": missing, "_key": (len(missing), len(clash), d, p)})
                    continue
                found_today = True
                venues = ranking.rank(d, block, people, needs, occ)["venues"][:VENUES_PER_SLOT]
                warn = lunch_warning(busy, groups, set(block))
                slots.append({**slot, "venues": venues,
                              "warnings": [w for w in (warn,) if w] + ([] if venues else ["No free venue fits"]),
                              "_key": (d, not venues, bool(warn), p)})
            if not found_today:
                days_without.append(day_label(d))
        d += timedelta(days=1)
    slots.sort(key=lambda s: s["_key"])
    almost.sort(key=lambda s: s["_key"])
    almost = almost[:ALMOST] if len(slots) < 10 else []
    for s in almost:  # nearly-free times: who would miss which class, and where it could happen
        s["venues"] = ranking.rank(s["_key"][2], s["periods"], people, needs,
                                   occ_by_day[s["_key"][2]])["venues"][:VENUES_PER_SLOT]
        n, total = s["_key"][1], len(groups)
        secs = f" in {len(s['missing'])} section{'s' if len(s['missing']) > 1 else ''}" if total > 1 else ""
        s["warnings"] = [f"{n} of {total} group{'s' if total > 1 else ''}{secs} {'has' if n == 1 else 'have'} class then"]
    for s in slots + almost:
        del s["_key"]
    return {"audience": {**aud, "attendees": people}, "duration": duration, "from": first.isoformat(),
            "to": last.isoformat(), "needs": needs, "total": len(slots), "slots": slots[:MAX_SLOTS],
            "almost": almost, "days_without_slot": days_without}

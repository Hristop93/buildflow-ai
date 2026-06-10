"""Section data extraction.

Section payloads come from the latest computed project_versions snapshot (the
recalc output already carries summary/route/fees/schedule/economics). The
journal is assembled live from the events log. This keeps section reads pure
(no recomputation, no mutation) — clients run POST /recalc to refresh.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models.app import ProjectVersion, Event


class NoComputedVersion(Exception):
    """The project has never been recalculated, so there is nothing to read."""


def latest_snapshot(db: Session, project_id: int) -> dict:
    snapshot = db.scalar(
        select(ProjectVersion.snapshot)
        .where(ProjectVersion.project_id == project_id)
        .order_by(ProjectVersion.version_no.desc())
        .limit(1)
    )
    if snapshot is None:
        raise NoComputedVersion(project_id)
    return snapshot


def build_section(db: Session, project_id: int, name: str) -> dict:
    """Return the data for one section. Caller has already checked tier access."""
    if name == "journal":
        return _journal(db, project_id)

    snapshot = latest_snapshot(db, project_id)
    # snapshot keys: summary, route, fees, schedule, economics, version_no, ...
    return {name: snapshot.get(name), "version_no": snapshot.get("version_no")}


def _journal(db: Session, project_id: int) -> dict:
    events = db.scalars(
        select(Event)
        .where(Event.project_id == project_id)
        .order_by(Event.created_at.asc())
    ).all()
    return {
        "journal": [
            {
                "event_type": e.event_type,
                "payload": e.payload,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ]
    }

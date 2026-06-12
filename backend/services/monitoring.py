"""'Актуалност' monitoring — when the regulatory data changes, recalc the
projects that subscribed to monitoring and notify them (SPEC 3 / 6 / 9).

Triggered synchronously from the admin revise endpoints. Email delivery is the
last mile (needs SMTP config) — for now the notification is an in-app event in
the project journal; see notify().
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models.app import Subscription, Project, Event, ProjectVersion
from backend.services.recalc import run_recalc

ACTIVE = "active"
PLAN = "aktualnost"


def notify(db: Session, *, project_id: int, user_id: int, event_type: str, payload: dict) -> None:
    """Record an in-app notification (journal event). TODO: also send an email
    once SMTP is configured (SPEC 3 'известия (имейл)')."""
    db.add(Event(project_id=project_id, event_type=event_type, payload=payload, created_by=user_id))


def _latest_snapshot(db: Session, project_id: int) -> dict | None:
    return db.scalar(
        select(ProjectVersion.snapshot)
        .where(ProjectVersion.project_id == project_id)
        .order_by(ProjectVersion.version_no.desc())
        .limit(1)
    )


def _active_subscriptions(db: Session):
    return db.scalars(
        select(Subscription)
        .where(Subscription.plan == PLAN)
        .where(Subscription.status == ACTIVE)
    ).all()


def propagate_tariff_change(db: Session, procedure_id: str, *, reason: str) -> int:
    """Recalc every subscribed project that uses `procedure_id`, and notify the
    ones whose total fees actually moved. Returns how many were notified."""
    notified = 0
    for sub in _active_subscriptions(db):
        snapshot = _latest_snapshot(db, sub.project_id)
        if snapshot is None:
            continue
        active_procs = {step["procedure_id"] for step in snapshot.get("route", [])}
        if procedure_id not in active_procs:
            continue

        before = snapshot.get("summary", {}).get("total_fees")
        result = run_recalc(db, sub.project_id, reason=reason)
        after = result["summary"]["total_fees"]
        if before is not None and round(after, 2) != round(before, 2):
            notify(
                db,
                project_id=sub.project_id,
                user_id=sub.user_id,
                event_type="subscription_recalc",
                payload={
                    "reason": reason,
                    "procedure_id": procedure_id,
                    "fees_before": before,
                    "fees_after": after,
                    "fees_delta": round(after - before, 2),
                    "version_no": result["version_no"],
                },
            )
            notified += 1
    if notified:
        db.commit()
    return notified

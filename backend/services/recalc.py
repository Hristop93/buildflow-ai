"""Recalc orchestration — the real-time contract from SPEC.md §4.5.

POST /projects/{id}/recalc runs: RuleEngine -> FeeEngine -> ScheduleEngine ->
EconEngine, then writes a new project_versions row and a 'recalc' event.

The backend ALWAYS computes everything (SPEC §6); tier-gating of which sections
are returned to the client happens at the read endpoints, not here.
"""
from __future__ import annotations

import json
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.db.models.app import Project, ProjectParam, ProjectVersion, Event
from backend.api.catalog import load_catalog
from backend.engines.rules import build_active_graph
from backend.engines.fees import compute_fees
from backend.engines.schedule import compute_schedule
from backend.engines.economics import evaluate


class ProjectNotFound(LookupError):
    pass


def _load_params(db: Session, project_id: int) -> dict:
    """Project params are stored JSON-encoded so types survive the round trip
    (power_mw stays int 5, degradation stays float 0.005, not strings)."""
    rows = db.scalars(
        select(ProjectParam).where(ProjectParam.project_id == project_id)
    ).all()
    out = {}
    for r in rows:
        try:
            out[r.param_name] = json.loads(r.value) if r.value is not None else None
        except (json.JSONDecodeError, TypeError):
            out[r.param_name] = r.value
    return out


def run_recalc(db: Session, project_id: int, *, reason: str = "recalc") -> dict:
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFound(project_id)

    params = _load_params(db, project_id)
    # The project_type column is authoritative over any stale param copy.
    params["project_type"] = project.project_type_id

    catalog = load_catalog(db)

    graph = build_active_graph(
        params,
        procedures=catalog.procedures,
        dependencies=catalog.dependencies,
        rules=catalog.rules,
        project_types=catalog.project_types,
    )
    fee_items, fee_total = compute_fees(
        graph["active"], params,
        fee_tariffs=catalog.fee_tariffs, acts=catalog.acts,
    )
    sched = compute_schedule(graph)
    econ = evaluate(params, total_fees=fee_total)

    result = _assemble(project, graph, fee_items, fee_total, sched, econ)

    # Persist a new immutable version + audit event.
    next_no = (
        db.scalar(
            select(func.coalesce(func.max(ProjectVersion.version_no), 0)).where(
                ProjectVersion.project_id == project_id
            )
        )
        or 0
    ) + 1
    result["version_no"] = next_no

    db.add(ProjectVersion(
        project_id=project_id,
        version_no=next_no,
        snapshot=result,
        reason=reason,
    ))
    db.add(Event(
        project_id=project_id,
        event_type="recalc",
        payload={
            "reason": reason,
            "version_no": next_no,
            "total_days": sched["total_days"],
            "total_fees": fee_total,
            "irr": econ["irr"],
            "verdict": econ["verdict"],
        },
    ))
    db.commit()

    return result


def _assemble(project, graph, fee_items, fee_total, sched, econ) -> dict:
    """Compose the section-shaped payload used by Резюме/Маршрут/Такси/График/Икономика."""
    procs = graph["procedures"]
    institution = graph["institution"]
    nodes = sched["nodes"]

    route = []
    for pid in sorted(graph["active"], key=lambda p: nodes[p]["start"]):
        route.append({
            "procedure_id": pid,
            "name": procs[pid]["name"],
            "institution": institution.get(pid),
            "act": procs[pid].get("act"),
            "start_day": nodes[pid]["start"],
            "end_day": nodes[pid]["end"],
            "duration_days": nodes[pid]["duration"],
            "is_critical": nodes[pid]["critical"],
        })

    # Enrich schedule nodes with the procedure name so the section is
    # self-sufficient for a Gantt (no need to cross-reference the route).
    schedule_nodes = {
        pid: {**n, "name": procs[pid]["name"]}
        for pid, n in nodes.items()
    }

    return {
        "project_id": project.id,
        "tier": project.tier,
        "summary": {
            "procedure_count": len(graph["active"]),
            "total_days": sched["total_days"],
            "total_fees": round(fee_total, 2),
        },
        "route": route,
        "fees": {"items": fee_items, "total": round(fee_total, 2)},
        "schedule": {"nodes": schedule_nodes, "total_days": sched["total_days"]},
        "economics": econ,
    }

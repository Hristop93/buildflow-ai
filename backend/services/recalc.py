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

from backend.db.models.app import Project, ProjectParam, ProjectVersion, Event, ProjectNode
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

    catalog = load_catalog(db, project.municipality_id)

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
        municipality_id=project.municipality_id,
    )

    # Per-node duration overrides (set by the schedule editor) feed the CPM;
    # absent override -> the statutory duration from the catalog.
    existing_nodes = {
        n.procedure_id: n
        for n in db.scalars(
            select(ProjectNode).where(ProjectNode.project_id == project_id)
        ).all()
    }
    overrides = {
        pid: n.planned_duration_days
        for pid, n in existing_nodes.items()
        if n.planned_duration_days is not None
    }

    sched = compute_schedule(graph, durations=overrides, edge_meta=catalog.edge_meta)

    # SPEC 4.4: only the DEVIATION from the statutory schedule shifts the
    # cashflows (the etalon prices the statutory baseline in). No overrides
    # means delay 0 — skip the second CPM pass.
    if overrides:
        statutory_total = compute_schedule(graph, edge_meta=catalog.edge_meta)["total_days"]
        delay_days = sched["total_days"] - statutory_total
    else:
        delay_days = 0

    econ = evaluate(params, total_fees=fee_total, delay_days=delay_days)

    statuses = _sync_nodes(db, project_id, graph, sched, existing_nodes)

    result = _assemble(project, graph, fee_items, fee_total, sched, econ, statuses,
                       documents=catalog.documents, procedure_inputs=catalog.procedure_inputs)

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


def _sync_nodes(db: Session, project_id: int, graph, sched, existing_nodes: dict) -> dict:
    """Upsert the instantiated project_nodes after a recalc: write the computed
    start/end/critical for every active node (preserving user overrides and
    status), and mark dropped procedures as excluded. Returns {pid: status}
    for the active nodes so the snapshot can carry it."""
    active = graph["active"]
    nodes = sched["nodes"]
    statuses = {}
    for pid in active:
        n = existing_nodes.get(pid)
        if n is None:
            n = ProjectNode(project_id=project_id, procedure_id=pid, status="pending")
            db.add(n)
        elif n.status == "excluded":
            n.status = "pending"  # a rule change re-included it
        n.computed_start_day = nodes[pid]["start"]
        n.computed_end_day = nodes[pid]["end"]
        n.is_critical = nodes[pid]["critical"]
        statuses[pid] = n.status

    for pid, n in existing_nodes.items():
        if pid not in active:
            n.status = "excluded"
            n.is_critical = False

    return statuses


def _assemble(project, graph, fee_items, fee_total, sched, econ, statuses=None,
              *, documents=None, procedure_inputs=None) -> dict:
    """Compose the section-shaped payload used by Резюме/Маршрут/Такси/График/Икономика."""
    procs = graph["procedures"]
    institution = graph["institution"]
    nodes = sched["nodes"]
    documents = documents or {}
    procedure_inputs = procedure_inputs or {}

    route = []
    for pid in sorted(graph["active"], key=lambda p: nodes[p]["start"]):
        out_doc = procs[pid].get("output_document")
        route.append({
            "procedure_id": pid,
            "name": procs[pid]["name"],
            "institution": institution.get(pid),
            "act": procs[pid].get("act"),
            "start_day": nodes[pid]["start"],
            "end_day": nodes[pid]["end"],
            "duration_days": nodes[pid]["duration"],
            "is_critical": nodes[pid]["critical"],
            "input_documents": [documents.get(d, d) for d in procedure_inputs.get(pid, [])],
            "output_document": documents.get(out_doc) if out_doc else None,
        })

    # Enrich schedule nodes with the procedure name and current status so the
    # section is self-sufficient for the Gantt editor.
    statuses = statuses or {}
    schedule_nodes = {
        pid: {**n, "name": procs[pid]["name"], "status": statuses.get(pid, "pending")}
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

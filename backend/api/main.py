"""Buildflow AI — FastAPI application.

Phase 1 surface: email/password auth (httpOnly JWT cookie), create a project
with params, run the recalc pipeline over the four engines, and read back
computed versions. Project endpoints require the caller to own the project.
"""
from __future__ import annotations

import json
from fastapi import FastAPI, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.base import get_db
from backend.db.models.app import (
    User, Project, ProjectParam, ProjectVersion, ProjectNode, Event, ValidationRequest,
)
from backend.db.models.core import ProjectType, Procedure, Municipality
from backend.api import schemas, tiers
from backend.api.auth import router as auth_router
from backend.api.admin import router as admin_router
from backend.api.deps import get_current_user, owned_project_or_404
from backend.services.recalc import run_recalc
from backend.services.sections import build_section, latest_snapshot, NoComputedVersion
from backend.services.export_xlsx import export_project_xlsx

app = FastAPI(title="Buildflow AI", version="0.1.0")
app.include_router(auth_router)
app.include_router(admin_router)


# --- Health & catalog --------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/catalog/project-types", response_model=list[schemas.ProjectTypeOut])
def project_types(db: Session = Depends(get_db)):
    return [
        schemas.ProjectTypeOut(id=pt.id, name=pt.name)
        for pt in db.scalars(select(ProjectType)).all()
    ]


@app.get("/catalog/municipalities", response_model=list[schemas.MunicipalityOut])
def municipalities(db: Session = Depends(get_db)):
    """Coverage status is shown honestly in the wizard (SPEC 5.2):
    verified = tariffs checked, partial = incomplete, none = no local data."""
    return db.scalars(select(Municipality).order_by(Municipality.name)).all()


# --- Projects (owner-scoped) -------------------------------------------------
@app.post("/projects", response_model=schemas.ProjectOut, status_code=201)
def create_project(
    payload: schemas.ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if db.get(ProjectType, payload.project_type_id) is None:
        raise HTTPException(400, f"unknown project_type_id: {payload.project_type_id}")
    if payload.municipality_id is not None and db.get(Municipality, payload.municipality_id) is None:
        raise HTTPException(400, f"unknown municipality_id: {payload.municipality_id}")

    project = Project(
        user_id=user.id,
        name=payload.name,
        project_type_id=payload.project_type_id,
        municipality_id=payload.municipality_id,
        tier=payload.tier,
        status="active",
    )
    db.add(project)
    db.flush()

    for name, value in payload.params.items():
        db.add(ProjectParam(
            project_id=project.id,
            param_name=name,
            value=json.dumps(value),
        ))
    db.commit()
    db.refresh(project)
    return project


@app.get("/projects", response_model=list[schemas.ProjectOut])
def list_projects(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return db.scalars(
        select(Project)
        .where(Project.user_id == user.id)
        .order_by(Project.created_at.desc())
    ).all()


@app.get("/projects/{project_id}", response_model=schemas.ProjectOut)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return owned_project_or_404(db, project_id, user)


@app.post("/projects/{project_id}/recalc")
def recalc(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    owned_project_or_404(db, project_id, user)
    return run_recalc(db, project_id)


NODE_STATUSES = {"pending", "active", "done", "delayed"}


@app.patch("/projects/{project_id}/nodes/{procedure_id}")
def patch_node(
    project_id: int,
    procedure_id: str,
    payload: schemas.NodePatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Edit one schedule node (duration override and/or status), then recalc.
    Returns the fresh result plus the delta against the previous version so the
    client can show "the change moved the deadline by +X days" (SPEC 5.2)."""
    project = owned_project_or_404(db, project_id, user)

    # Editing the schedule is a pro capability, same as reading it (SPEC 6).
    if not tiers.can_access(project.tier, "schedule"):
        raise HTTPException(403, {
            "error": "section_locked",
            "section": "schedule",
            "your_tier": project.tier,
            "required_tier": tiers.required_tier("schedule"),
        })
    if db.get(Procedure, procedure_id) is None:
        raise HTTPException(404, f"unknown procedure: {procedure_id}")
    if payload.status is not None and payload.status not in NODE_STATUSES:
        raise HTTPException(400, f"status must be one of {sorted(NODE_STATUSES)}")
    if payload.status == "delayed" and not (payload.reason and payload.reason.strip()):
        raise HTTPException(400, "reason is required when marking a node as delayed")

    changes: dict = {}
    if "planned_duration_days" in payload.model_fields_set:
        changes["planned_duration_days"] = payload.planned_duration_days
    if payload.status is not None:
        changes["status"] = payload.status
    if not changes:
        raise HTTPException(400, "nothing to change")

    node = db.scalar(
        select(ProjectNode).where(
            ProjectNode.project_id == project_id,
            ProjectNode.procedure_id == procedure_id,
        )
    )
    if node is None:
        node = ProjectNode(project_id=project_id, procedure_id=procedure_id, status="pending")
        db.add(node)
        db.flush()

    if "planned_duration_days" in changes:
        node.planned_duration_days = changes["planned_duration_days"]
    if "status" in changes:
        node.status = changes["status"]

    # Previous totals -> delta for the "change moved the deadline" banner.
    try:
        prev = latest_snapshot(db, project_id)
        prev_days = prev["summary"]["total_days"]
        prev_irr = prev["economics"]["irr"]
    except NoComputedVersion:
        prev_days = None
        prev_irr = None

    db.add(Event(
        project_id=project_id,
        node_id=node.id,
        event_type="node_changed",
        payload={"procedure_id": procedure_id, **changes, "reason": payload.reason},
        created_by=user.id,
    ))

    result = run_recalc(db, project_id, reason=f"node edit: {procedure_id}")

    new_days = result["summary"]["total_days"]
    new_irr = result["economics"]["irr"]
    return {
        "version_no": result["version_no"],
        "delta_days": (new_days - prev_days) if prev_days is not None else None,
        "delta_irr_pp": round((new_irr - prev_irr) * 100, 2) if prev_irr is not None else None,
        "result": result,
    }


@app.get("/projects/{project_id}/versions", response_model=list[schemas.VersionOut])
def list_versions(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    owned_project_or_404(db, project_id, user)
    return db.scalars(
        select(ProjectVersion)
        .where(ProjectVersion.project_id == project_id)
        .order_by(ProjectVersion.version_no.desc())
    ).all()


PENDING_VALIDATION = ("requested", "in_review")


@app.post("/projects/{project_id}/validation", response_model=schemas.ValidationRequestOut, status_code=201)
def request_validation(
    project_id: int,
    payload: schemas.ValidationRequestIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """A dd user requests expert validation of the project (SPEC 5.2)."""
    project = owned_project_or_404(db, project_id, user)
    if not tiers.can_access(project.tier, "export"):  # export == dd
        raise HTTPException(403, {
            "error": "tier_required", "required_tier": "dd", "your_tier": project.tier,
        })
    existing = db.scalar(
        select(ValidationRequest)
        .where(ValidationRequest.project_id == project_id)
        .where(ValidationRequest.status.in_(PENDING_VALIDATION))
    )
    if existing is not None:
        raise HTTPException(409, "a validation request is already pending for this project")

    req = ValidationRequest(
        project_id=project_id, user_id=user.id,
        status="requested", note=payload.note,
    )
    db.add(req)
    db.add(Event(
        project_id=project_id, event_type="validation_requested",
        payload={"note": payload.note}, created_by=user.id,
    ))
    db.commit()
    db.refresh(req)
    return req


@app.get("/projects/{project_id}/validation", response_model=schemas.ValidationRequestOut | None)
def get_validation(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    owned_project_or_404(db, project_id, user)
    return db.scalar(
        select(ValidationRequest)
        .where(ValidationRequest.project_id == project_id)
        .order_by(ValidationRequest.created_at.desc())
        .limit(1)
    )


XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@app.get("/projects/{project_id}/export/xlsx")
def export_xlsx(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Excel package of the computed sections (dd tier, SPEC 6)."""
    project = owned_project_or_404(db, project_id, user)
    if not tiers.can_access(project.tier, "export"):
        raise HTTPException(403, {
            "error": "section_locked",
            "section": "export",
            "your_tier": project.tier,
            "required_tier": tiers.required_tier("export"),
        })
    try:
        data = export_project_xlsx(db, project_id)
    except NoComputedVersion:
        raise HTTPException(409, "project has no computed version yet; run recalc first")

    filename = f"buildflow-project-{project_id}.xlsx"
    return Response(
        content=data,
        media_type=XLSX_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/projects/{project_id}/sections/{name}")
def get_section(
    project_id: int,
    name: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Tier-gated read of one project section. The server enforces access here;
    the UI lock is cosmetic (SPEC 6)."""
    project = owned_project_or_404(db, project_id, user)

    if not tiers.is_known_section(name):
        raise HTTPException(404, f"unknown section: {name}")
    if not tiers.can_access(project.tier, name):
        # Structured detail so the client can render the upgrade CTA.
        raise HTTPException(403, {
            "error": "section_locked",
            "section": name,
            "your_tier": project.tier,
            "required_tier": tiers.required_tier(name),
        })
    if name not in tiers.IMPLEMENTED_SECTIONS:
        raise HTTPException(501, f"section '{name}' is not available in this phase")

    try:
        data = build_section(db, project_id, name)
    except NoComputedVersion:
        raise HTTPException(409, "project has no computed version yet; run recalc first")

    return {
        "section": name,
        "your_tier": project.tier,
        "required_tier": tiers.required_tier(name),
        "data": data,
    }

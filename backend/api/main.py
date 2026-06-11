"""Buildflow AI — FastAPI application.

Phase 1 surface: email/password auth (httpOnly JWT cookie), create a project
with params, run the recalc pipeline over the four engines, and read back
computed versions. Project endpoints require the caller to own the project.
"""
from __future__ import annotations

import json
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.base import get_db
from backend.db.models.app import User, Project, ProjectParam, ProjectVersion
from backend.db.models.core import ProjectType
from backend.api import schemas, tiers
from backend.api.auth import router as auth_router
from backend.api.admin import router as admin_router
from backend.api.deps import get_current_user, owned_project_or_404
from backend.services.recalc import run_recalc
from backend.services.sections import build_section, NoComputedVersion

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


# --- Projects (owner-scoped) -------------------------------------------------
@app.post("/projects", response_model=schemas.ProjectOut, status_code=201)
def create_project(
    payload: schemas.ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if db.get(ProjectType, payload.project_type_id) is None:
        raise HTTPException(400, f"unknown project_type_id: {payload.project_type_id}")

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

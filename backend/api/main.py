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
from backend.api import schemas
from backend.api.auth import router as auth_router
from backend.api.deps import get_current_user, owned_project_or_404
from backend.services.recalc import run_recalc

app = FastAPI(title="Buildflow AI", version="0.1.0")
app.include_router(auth_router)


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

"""Pydantic request/response models for the API."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field, ConfigDict


class ProjectCreate(BaseModel):
    name: str
    project_type_id: str
    municipality_id: int | None = None
    tier: str = "free"
    params: dict[str, Any] = Field(default_factory=dict)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    project_type_id: str | None
    municipality_id: int | None
    tier: str
    status: str


class ProjectTypeOut(BaseModel):
    id: str
    name: str


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version_no: int
    reason: str | None
    created_at: Any

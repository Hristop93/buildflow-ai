"""Pydantic request/response models for the API."""
from __future__ import annotations

from typing import Any
from datetime import date
from pydantic import BaseModel, Field, ConfigDict, EmailStr


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str | None = None
    company: str | None = None
    gdpr_consent: bool = False


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str | None
    company: str | None
    role: str


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


class NodePatch(BaseModel):
    """Edit one schedule node: override its duration and/or set its status.
    Send planned_duration_days: null to clear the override (back to statutory)."""
    planned_duration_days: int | None = Field(default=None, ge=0)
    status: str | None = None
    reason: str | None = None  # mandatory when status='delayed' (SPEC 5.2)


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version_no: int
    reason: str | None
    created_at: Any


# --- Admin: normative acts ---------------------------------------------------
class ActCreate(BaseModel):
    title: str
    level: str = "state"            # state | municipal
    article: str | None = None
    valid_from: date
    act_type: str | None = None
    municipality_id: int | None = None
    source_url: str | None = None


class ActRevise(BaseModel):
    """Edits create a NEW superseding version (core data is append-only)."""
    valid_from: date               # the day the new version takes effect
    title: str | None = None
    article: str | None = None
    level: str | None = None
    source_url: str | None = None


class ActOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    level: str
    article: str | None
    valid_from: date
    valid_to: date | None
    supersedes_id: str | None
    source_url: str | None
    verified_at: date | None
    verified_by: str | None


# --- Admin: fee tariffs ------------------------------------------------------
class TariffCreate(BaseModel):
    procedure_id: str
    basis: str                     # fixed | per_sqm_rzp | pct_of_value | per_mw
    rate: float
    description: str | None = None
    municipality_id: int | None = None
    act_id: str | None = None
    valid_from: date | None = None


class TariffRevise(BaseModel):
    valid_from: date
    rate: float | None = None
    description: str | None = None
    act_id: str | None = None
    municipality_id: int | None = None


class TariffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    procedure_id: str
    description: str | None
    basis: str
    rate: float
    municipality_id: int | None
    act_id: str | None
    valid_from: date | None
    valid_to: date | None

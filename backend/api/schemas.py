"""Pydantic request/response models for the API."""
from __future__ import annotations

from typing import Any
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

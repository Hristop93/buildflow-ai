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


class MunicipalityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    region: str | None
    coverage_status: str  # verified | partial | none


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
class FeeTier(BaseModel):
    up_to: float | None = None     # None = no upper bound (last bracket)
    rate: float


class TariffCreate(BaseModel):
    procedure_id: str
    basis: str                     # fixed | per_sqm_rzp | pct_of_value | per_mw
    rate: float = 0.0              # ignored when tiers are given
    tiers: list[FeeTier] | None = None
    min_fee: float | None = None
    max_fee: float | None = None
    description: str | None = None
    municipality_id: int | None = None
    act_id: str | None = None
    valid_from: date | None = None


class TariffRevise(BaseModel):
    valid_from: date
    rate: float | None = None
    tiers: list[FeeTier] | None = None
    min_fee: float | None = None
    max_fee: float | None = None
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
    tiers: list[FeeTier] | None
    min_fee: float | None
    max_fee: float | None
    municipality_id: int | None
    act_id: str | None
    valid_from: date | None
    valid_to: date | None


# --- Admin: procedure graph (procedures / rules / dependencies) --------------
class ProcedureIn(BaseModel):
    id: str | None = None  # auto-generated if omitted
    name: str
    institution_id: str | None = None
    statutory_term_days: int | None = Field(default=None, ge=0)
    act_id: str | None = None
    municipality_id: int | None = None  # None = national step
    note: str | None = None


class ProcedureUpdate(BaseModel):
    name: str | None = None
    institution_id: str | None = None
    statutory_term_days: int | None = Field(default=None, ge=0)
    act_id: str | None = None
    output_document_id: str | None = None
    note: str | None = None


class ProcedureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    institution_id: str | None
    statutory_term_days: int | None
    act_id: str | None
    output_document_id: str | None
    municipality_id: int | None
    note: str | None


class DocumentIn(BaseModel):
    id: str | None = None
    name: str
    issuer_institution_id: str | None = None
    doc_type: str | None = None
    note: str | None = None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    issuer_institution_id: str | None
    doc_type: str | None
    note: str | None


class ProcedureInputIn(BaseModel):
    document_id: str


class RuleCondition(BaseModel):
    param: str
    op: str                  # = | != | >= | <= | < | > | in
    value: Any               # native JSON type (bool/number/string)


class RuleIn(BaseModel):
    """Either the legacy single triple (param_name/operator/value) or the
    compound `conditions` list (ALL must hold). One of the two is required."""
    id: str | None = None
    param_name: str | None = None
    operator: str | None = None   # = | != | >= | <= | < | > | in
    value: str | None = None
    conditions: list[RuleCondition] | None = None
    action: str                   # include | exclude | switch_institution
    target_procedure_id: str | None = None
    target_institution_id: str | None = None
    municipality_id: int | None = None
    explanation: str | None = None


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    param_name: str | None
    operator: str | None
    value: str | None
    conditions: list[RuleCondition] | None
    action: str
    target_procedure_id: str | None
    target_institution_id: str | None
    municipality_id: int | None
    explanation: str | None


class DependencyIn(BaseModel):
    successor_id: str
    predecessor_id: str
    municipality_id: int | None = None
    link_type: str = "finish_start"


class DependencyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    successor_id: str
    predecessor_id: str
    municipality_id: int | None
    link_type: str | None


# --- "Актуалност" subscription -----------------------------------------------
class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None
    plan: str | None
    status: str | None
    active_until: Any


# --- Expert validation (dd) --------------------------------------------------
class ValidationRequestIn(BaseModel):
    note: str | None = None


class ValidationRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    status: str
    note: str | None
    review_note: str | None
    certified_pdf_url: str | None
    created_at: Any
    reviewed_at: Any


class ValidationQueueItem(ValidationRequestOut):
    """Admin view of the queue — adds who/what so the reviewer has context."""
    project_name: str
    requester_email: str


class ValidationReview(BaseModel):
    status: str  # in_review | approved | rejected
    review_note: str | None = None
    certified_pdf_url: str | None = None

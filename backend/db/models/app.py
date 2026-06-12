from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, Float, Boolean,
    DateTime, JSON, ForeignKey, Text,
)
from backend.db.base import Base

SCHEMA = "app"


def _now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    company = Column(String, nullable=True)
    role = Column(String, nullable=False, default="user", server_default="user")  # user | admin
    created_at = Column(DateTime(timezone=True), default=_now)
    gdpr_consent_at = Column(DateTime(timezone=True), nullable=True)


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("app.users.id"), nullable=False)
    name = Column(String, nullable=False)
    project_type_id = Column(String, ForeignKey("core.project_types.id"), nullable=True)
    municipality_id = Column(Integer, ForeignKey("core.municipalities.id"), nullable=True)
    tier = Column(String, default="free")   # free | standard | pro | dd
    status = Column(String, default="active")
    created_at = Column(DateTime(timezone=True), default=_now)


class ProjectParam(Base):
    __tablename__ = "project_params"
    __table_args__ = {"schema": SCHEMA}

    project_id = Column(Integer, ForeignKey("app.projects.id"), primary_key=True)
    param_name = Column(String, primary_key=True)
    value = Column(String, nullable=True)


class ProjectNode(Base):
    __tablename__ = "project_nodes"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("app.projects.id"), nullable=False)
    procedure_id = Column(String, ForeignKey("core.procedures.id"), nullable=True)
    status = Column(String, default="pending")  # pending | active | done | delayed | excluded
    planned_duration_days = Column(Integer, nullable=True)
    actual_start = Column(DateTime(timezone=True), nullable=True)
    actual_end = Column(DateTime(timezone=True), nullable=True)
    computed_start_day = Column(Integer, nullable=True)
    computed_end_day = Column(Integer, nullable=True)
    is_critical = Column(Boolean, default=False)


class ProjectFee(Base):
    __tablename__ = "project_fees"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("app.projects.id"), nullable=False)
    node_id = Column(Integer, ForeignKey("app.project_nodes.id"), nullable=True)
    fee_tariff_id = Column(String, ForeignKey("core.fee_tariffs.id"), nullable=True)
    basis_value = Column(Float, nullable=True)
    computed_amount = Column(Float, nullable=True)
    act_snapshot = Column(JSON, nullable=True)


class ProjectVersion(Base):
    __tablename__ = "project_versions"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("app.projects.id"), nullable=False)
    version_no = Column(Integer, nullable=False)
    snapshot = Column(JSON, nullable=True)
    reason = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("app.projects.id"), nullable=False)
    node_id = Column(Integer, ForeignKey("app.project_nodes.id"), nullable=True)
    event_type = Column(String, nullable=False)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now)
    created_by = Column(Integer, ForeignKey("app.users.id"), nullable=True)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("app.users.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("app.projects.id"), nullable=True)
    tier = Column(String, nullable=True)
    amount = Column(Float, nullable=True)
    currency = Column(String, default="BGN")
    stripe_payment_id = Column(String, nullable=True)
    status = Column(String, nullable=True)
    invoice_no = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now)


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("app.users.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("app.projects.id"), nullable=True)
    plan = Column(String, nullable=True)
    active_until = Column(DateTime(timezone=True), nullable=True)
    stripe_sub_id = Column(String, nullable=True)
    status = Column(String, nullable=True)


class ValidationRequest(Base):
    """A dd user's request for expert validation of a project, and the admin's
    handling of it (SPEC 5.2 / 5.3 'Опашка валидации')."""
    __tablename__ = "validation_requests"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("app.projects.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("app.users.id"), nullable=False)
    # requested | in_review | approved | rejected
    status = Column(String, nullable=False, default="requested", server_default="requested")
    note = Column(Text, nullable=True)          # the requester's note
    review_note = Column(Text, nullable=True)   # the reviewer's note
    certified_pdf_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by = Column(Integer, ForeignKey("app.users.id"), nullable=True)

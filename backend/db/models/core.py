from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Date, JSON,
    ForeignKey, Text,
)
from backend.db.base import Base

SCHEMA = "core"


class Municipality(Base):
    __tablename__ = "municipalities"
    __table_args__ = {"schema": SCHEMA}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    region = Column(String)
    coverage_status = Column(String, default="none")  # verified | partial | none
    verified_at = Column(Date, nullable=True)


class NormativeAct(Base):
    __tablename__ = "normative_acts"
    __table_args__ = {"schema": SCHEMA}

    id = Column(String, primary_key=True)
    act_type = Column(String, nullable=True)
    title = Column(String, nullable=False)
    level = Column(String, nullable=False)  # state | municipal
    municipality_id = Column(Integer, ForeignKey("core.municipalities.id"), nullable=True)
    article = Column(String, nullable=True)
    valid_from = Column(Date, nullable=False)
    valid_to = Column(Date, nullable=True)
    supersedes_id = Column(String, ForeignKey("core.normative_acts.id"), nullable=True)
    source_url = Column(String, nullable=True)
    verified_at = Column(Date, nullable=True)
    verified_by = Column(String, nullable=True)


class Institution(Base):
    __tablename__ = "institutions"
    __table_args__ = {"schema": SCHEMA}

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    inst_type = Column(String, nullable=True)
    competence = Column(Text, nullable=True)
    default_term_days = Column(Integer, nullable=True)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = {"schema": SCHEMA}

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    issuer_institution_id = Column(String, ForeignKey("core.institutions.id"), nullable=True)
    doc_type = Column(String, nullable=True)
    note = Column(Text, nullable=True)


class Procedure(Base):
    __tablename__ = "procedures"
    __table_args__ = {"schema": SCHEMA}

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    institution_id = Column(String, ForeignKey("core.institutions.id"), nullable=True)
    output_document_id = Column(String, ForeignKey("core.documents.id"), nullable=True)
    statutory_term_days = Column(Integer, nullable=True)
    act_id = Column(String, ForeignKey("core.normative_acts.id"), nullable=True)
    note = Column(Text, nullable=True)
    # None = national; set = a step required only in this municipality.
    municipality_id = Column(Integer, ForeignKey("core.municipalities.id"), nullable=True)


class ProcedureInput(Base):
    __tablename__ = "procedure_inputs"
    __table_args__ = {"schema": SCHEMA}

    procedure_id = Column(String, ForeignKey("core.procedures.id"), primary_key=True)
    document_id = Column(String, ForeignKey("core.documents.id"), primary_key=True)


class Dependency(Base):
    __tablename__ = "dependencies"
    __table_args__ = {"schema": SCHEMA}

    successor_id = Column(String, ForeignKey("core.procedures.id"), primary_key=True)
    predecessor_id = Column(String, ForeignKey("core.procedures.id"), primary_key=True)
    link_type = Column(String, default="finish_start")
    # None = national edge; set = applies only in this municipality.
    municipality_id = Column(Integer, ForeignKey("core.municipalities.id"), nullable=True)


class FeeTariff(Base):
    __tablename__ = "fee_tariffs"
    __table_args__ = {"schema": SCHEMA}

    id = Column(String, primary_key=True)
    procedure_id = Column(String, ForeignKey("core.procedures.id"), nullable=False)
    description = Column(String, nullable=True)
    basis = Column(String, nullable=False)  # fixed | per_sqm_rzp | pct_of_value | per_mw
    rate = Column(Float, nullable=False)
    municipality_id = Column(Integer, ForeignKey("core.municipalities.id"), nullable=True)
    act_id = Column(String, ForeignKey("core.normative_acts.id"), nullable=True)
    valid_from = Column(Date, nullable=True)
    valid_to = Column(Date, nullable=True)


class Rule(Base):
    __tablename__ = "rules"
    __table_args__ = {"schema": SCHEMA}

    id = Column(String, primary_key=True)
    param_name = Column(String, nullable=False)
    operator = Column(String, nullable=False)  # = | != | >= | <= | in
    value = Column(String, nullable=False)
    action = Column(String, nullable=False)   # include | exclude | switch_institution
    target_procedure_id = Column(String, ForeignKey("core.procedures.id"), nullable=True)
    target_institution_id = Column(String, ForeignKey("core.institutions.id"), nullable=True)
    explanation = Column(Text, nullable=True)
    # None = national rule; set = applies only to projects in this municipality.
    municipality_id = Column(Integer, ForeignKey("core.municipalities.id"), nullable=True)


class ProjectType(Base):
    __tablename__ = "project_types"
    __table_args__ = {"schema": SCHEMA}

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    base_procedure_set = Column(JSON, nullable=True)

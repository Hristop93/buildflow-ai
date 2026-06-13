"""Catalog repository — load core regulatory data from the DB and convert it
into the plain-dict shapes the engines expect (the same shapes seed.py exposes).

The engines (rules/fees/schedule/economics) are pure and consume seed-format
dicts. The DB models use different field names (institution_id vs institution,
statutory_term_days vs duration_days, ...), so this layer is the single place
that maps between the two. Keeping it here means the engines never import the ORM.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from backend.db.models.core import (
    Procedure, Dependency, Rule, FeeTariff, NormativeAct, ProjectType,
    Document, ProcedureInput,
)


@dataclass
class Catalog:
    procedures: list[dict]
    dependencies: dict[str, list[str]]
    rules: list[dict]
    fee_tariffs: list[dict]
    acts: list[dict]
    project_types: dict[str, dict]
    documents: dict[str, str]              # doc_id -> name
    procedure_inputs: dict[str, list[str]]  # procedure_id -> [doc_id]


def _coerce(value: str):
    """Rule values are stored as TEXT. Recover numbers so comparison operators
    (<, >=, ...) work; non-numeric stays a string (category match for =, in)."""
    if value is None:
        return None
    try:
        if "." in value:
            return float(value)
        return int(value)
    except (ValueError, TypeError):
        return value


def load_catalog(db: Session, municipality_id: int | None = None) -> Catalog:
    """The graph is layered: national rows (municipality_id IS NULL) always
    apply; a municipality's own procedures/rules/edges apply only to projects
    in that municipality (SPEC 3.1). So a municipality can require a different
    set of steps, not just different fees."""
    def _scope(model):
        return or_(model.municipality_id.is_(None), model.municipality_id == municipality_id)

    procedures = [
        {
            "id": p.id,
            "name": p.name,
            "institution": p.institution_id,
            "duration_days": p.statutory_term_days,
            "act": p.act_id,
            "output_document": p.output_document_id,
        }
        for p in db.scalars(select(Procedure).where(_scope(Procedure))).all()
    ]

    documents = {d.id: d.name for d in db.scalars(select(Document)).all()}
    procedure_inputs: dict[str, list[str]] = {}
    for pi in db.scalars(select(ProcedureInput)).all():
        procedure_inputs.setdefault(pi.procedure_id, []).append(pi.document_id)

    dependencies: dict[str, list[str]] = {}
    for d in db.scalars(select(Dependency).where(_scope(Dependency))).all():
        dependencies.setdefault(d.successor_id, []).append(d.predecessor_id)

    rules = [
        {
            "id": r.id,
            "param": r.param_name,
            "op": r.operator,
            "value": _coerce(r.value),
            "action": r.action,
            "target": r.target_procedure_id,
            "target_institution": r.target_institution_id,
            # JSON conditions keep native types (bool/number/str) — no coercion.
            "conditions": r.conditions,
        }
        for r in db.scalars(select(Rule).where(_scope(Rule))).all()
    ]

    # Only tariffs in force today (SPEC 4.2): valid_from <= today < valid_to.
    # This keeps superseded versions (created by an admin revise) out of recalc.
    today = date.today()
    in_force = select(FeeTariff).where(
        or_(FeeTariff.valid_from.is_(None), FeeTariff.valid_from <= today),
        or_(FeeTariff.valid_to.is_(None), FeeTariff.valid_to > today),
    )
    fee_tariffs = [
        {
            "id": t.id,
            "procedure": t.procedure_id,
            "desc": t.description,
            "basis": t.basis,
            "rate": t.rate,
            "tiers": t.tiers,
            "min_fee": t.min_fee,
            "max_fee": t.max_fee,
            "act": t.act_id,
            "municipality": t.municipality_id,  # None = national
        }
        for t in db.scalars(in_force).all()
    ]

    acts = [
        {
            "id": a.id,
            "title": a.title,
            "article": a.article,
            "valid_from": a.valid_from.isoformat() if a.valid_from else None,
        }
        for a in db.scalars(select(NormativeAct)).all()
    ]

    project_types = {
        pt.id: {"name": pt.name, "procedures": pt.base_procedure_set or []}
        for pt in db.scalars(select(ProjectType)).all()
    }

    return Catalog(
        procedures=procedures,
        dependencies=dependencies,
        rules=rules,
        fee_tariffs=fee_tariffs,
        acts=acts,
        project_types=project_types,
        documents=documents,
        procedure_inputs=procedure_inputs,
    )

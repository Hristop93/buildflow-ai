"""
Load seed data into the database.
Run from the project root:  python -m backend.data.loader
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.db.base import SessionLocal
from backend.db.models.core import (
    Institution, NormativeAct, Procedure, Dependency,
    FeeTariff, Rule, ProjectType,
)
from backend.data.seed import (
    INSTITUTIONS, ACTS, PROCEDURES, DEPENDENCIES,
    FEE_TARIFFS, RULES, PROJECT_TYPES,
)


def _parse_date(s: str | None) -> date | None:
    if s is None:
        return None
    return date.fromisoformat(s)


def load_all():
    db = SessionLocal()
    try:
        _load_institutions(db)
        _load_acts(db)
        db.flush()
        _load_procedures(db)
        db.flush()
        _load_dependencies(db)
        _load_fee_tariffs(db)
        _load_rules(db)
        _load_project_types(db)
        db.commit()
        print("Seed data loaded successfully.")
    except Exception as exc:
        db.rollback()
        print(f"Error loading seed data: {exc}", file=sys.stderr)
        raise
    finally:
        db.close()


def _load_institutions(db):
    for row in INSTITUTIONS:
        if db.get(Institution, row["id"]):
            continue
        db.add(Institution(
            id=row["id"],
            name=row["name"],
            inst_type=row.get("type"),
        ))
    print(f"  institutions: {len(INSTITUTIONS)}")


def _load_acts(db):
    for row in ACTS:
        if db.get(NormativeAct, row["id"]):
            continue
        db.add(NormativeAct(
            id=row["id"],
            title=row["title"],
            level=row["level"],
            article=row.get("article"),
            valid_from=_parse_date(row["valid_from"]),
            valid_to=_parse_date(row.get("valid_to")),
        ))
    print(f"  normative_acts: {len(ACTS)}")


def _load_procedures(db):
    for row in PROCEDURES:
        if db.get(Procedure, row["id"]):
            continue
        db.add(Procedure(
            id=row["id"],
            name=row["name"],
            institution_id=row.get("institution"),
            statutory_term_days=row.get("duration_days"),
            act_id=row.get("act"),
        ))
    print(f"  procedures: {len(PROCEDURES)}")


def _load_dependencies(db):
    count = 0
    for successor_id, predecessors in DEPENDENCIES.items():
        for pred_id in predecessors:
            existing = db.get(Dependency, (successor_id, pred_id))
            if existing:
                continue
            db.add(Dependency(
                successor_id=successor_id,
                predecessor_id=pred_id,
            ))
            count += 1
    print(f"  dependencies: {count}")


def _load_fee_tariffs(db):
    for row in FEE_TARIFFS:
        if db.get(FeeTariff, row["id"]):
            continue
        db.add(FeeTariff(
            id=row["id"],
            procedure_id=row["procedure"],
            description=row.get("desc"),
            basis=row["basis"],
            rate=row["rate"],
            act_id=row.get("act"),
        ))
    print(f"  fee_tariffs: {len(FEE_TARIFFS)}")


def _load_rules(db):
    for row in RULES:
        if db.get(Rule, row["id"]):
            continue
        db.add(Rule(
            id=row["id"],
            param_name=row["param"],
            operator=row["op"],
            value=str(row["value"]),
            action=row["action"],
            target_procedure_id=row.get("target"),
            target_institution_id=row.get("target_institution"),
        ))
    print(f"  rules: {len(RULES)}")


def _load_project_types(db):
    for type_id, data in PROJECT_TYPES.items():
        if db.get(ProjectType, type_id):
            continue
        db.add(ProjectType(
            id=type_id,
            name=data["name"],
            base_procedure_set=data["procedures"],
        ))
    print(f"  project_types: {len(PROJECT_TYPES)}")


if __name__ == "__main__":
    load_all()

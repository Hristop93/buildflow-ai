"""Admin endpoints — data entry for the regulatory knowledge (SPEC 5.3 / 7).

Restricted to role='admin'. Core data is append-only (SPEC 3.1): editing an act
or tariff never overwrites a row — it creates a new superseding version and
closes the old one with valid_to. This preserves reproducibility: past project
reports keep citing the exact row that was in force when they were computed.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from backend.db.base import get_db
from backend.db.models.app import User, Project, ValidationRequest, ProjectNode
from backend.db.models.core import (
    NormativeAct, FeeTariff, Procedure, Municipality, Rule, Dependency, Institution,
    Document, ProcedureInput,
)
from backend.api import schemas
from backend.api.deps import get_current_admin
from backend.services.monitoring import propagate_tariff_change
from backend.services import import_csv
from backend.services.import_csv import import_municipalities, import_tariffs, ImportError_

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_current_admin)])

ALLOWED_BASES = {"fixed", "per_sqm_rzp", "pct_of_value", "per_mw"}
ALLOWED_LEVELS = {"state", "municipal"}
REVIEW_STATUSES = {"in_review", "approved", "rejected"}
RULE_OPERATORS = {"=", "!=", ">=", "<=", "<", ">", "in"}
RULE_ACTIONS = {"include", "exclude", "switch_institution"}


def _require(db, model, pk, label):
    if pk is not None and db.get(model, pk) is None:
        raise HTTPException(400, f"unknown {label}: {pk}")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


def _check_municipality(db: Session, municipality_id: int | None) -> None:
    if municipality_id is not None and db.get(Municipality, municipality_id) is None:
        raise HTTPException(400, f"unknown municipality_id: {municipality_id}")


# --- Acts --------------------------------------------------------------------
@router.post("/acts", response_model=schemas.ActOut, status_code=201)
def create_act(payload: schemas.ActCreate, db: Session = Depends(get_db)):
    if payload.level not in ALLOWED_LEVELS:
        raise HTTPException(400, f"level must be one of {sorted(ALLOWED_LEVELS)}")
    _check_municipality(db, payload.municipality_id)

    act = NormativeAct(
        id=_new_id("ACT"),
        title=payload.title,
        level=payload.level,
        article=payload.article,
        valid_from=payload.valid_from,
        act_type=payload.act_type,
        municipality_id=payload.municipality_id,
        source_url=payload.source_url,
    )
    db.add(act)
    db.commit()
    db.refresh(act)
    return act


@router.get("/acts", response_model=list[schemas.ActOut])
def list_acts(active_only: bool = False, db: Session = Depends(get_db)):
    stmt = select(NormativeAct)
    if active_only:
        stmt = stmt.where(NormativeAct.valid_to.is_(None))
    return db.scalars(stmt.order_by(NormativeAct.id)).all()


@router.get("/acts/{act_id}", response_model=schemas.ActOut)
def get_act(act_id: str, db: Session = Depends(get_db)):
    act = db.get(NormativeAct, act_id)
    if act is None:
        raise HTTPException(404, "act not found")
    return act


@router.post("/acts/{act_id}/revise", response_model=schemas.ActOut, status_code=201)
def revise_act(act_id: str, payload: schemas.ActRevise, db: Session = Depends(get_db)):
    """Create a new version that supersedes the given act and close the old one."""
    old = db.get(NormativeAct, act_id)
    if old is None:
        raise HTTPException(404, "act not found")
    if old.valid_to is not None:
        raise HTTPException(409, "this act version is already superseded")
    if payload.level is not None and payload.level not in ALLOWED_LEVELS:
        raise HTTPException(400, f"level must be one of {sorted(ALLOWED_LEVELS)}")

    new = NormativeAct(
        id=_new_id("ACT"),
        title=payload.title if payload.title is not None else old.title,
        level=payload.level if payload.level is not None else old.level,
        article=payload.article if payload.article is not None else old.article,
        valid_from=payload.valid_from,
        act_type=old.act_type,
        municipality_id=old.municipality_id,
        source_url=payload.source_url if payload.source_url is not None else old.source_url,
        supersedes_id=old.id,
    )
    old.valid_to = payload.valid_from  # old stays valid up to the day the new one starts
    db.add(new)
    db.commit()
    db.refresh(new)
    return new


@router.post("/acts/{act_id}/verify", response_model=schemas.ActOut)
def verify_act(act_id: str, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    act = db.get(NormativeAct, act_id)
    if act is None:
        raise HTTPException(404, "act not found")
    act.verified_at = date.today()
    act.verified_by = admin.email
    db.commit()
    db.refresh(act)
    return act


# --- Tariffs -----------------------------------------------------------------
@router.post("/tariffs", response_model=schemas.TariffOut, status_code=201)
def create_tariff(payload: schemas.TariffCreate, db: Session = Depends(get_db)):
    if payload.basis not in ALLOWED_BASES:
        raise HTTPException(400, f"basis must be one of {sorted(ALLOWED_BASES)}")
    if db.get(Procedure, payload.procedure_id) is None:
        raise HTTPException(400, f"unknown procedure_id: {payload.procedure_id}")
    if payload.act_id is not None and db.get(NormativeAct, payload.act_id) is None:
        raise HTTPException(400, f"unknown act_id: {payload.act_id}")
    _check_municipality(db, payload.municipality_id)

    tariff = FeeTariff(
        id=_new_id("FEE"),
        procedure_id=payload.procedure_id,
        description=payload.description,
        basis=payload.basis,
        rate=payload.rate,
        tiers=[t.model_dump() for t in payload.tiers] if payload.tiers else None,
        min_fee=payload.min_fee,
        max_fee=payload.max_fee,
        municipality_id=payload.municipality_id,
        act_id=payload.act_id,
        valid_from=payload.valid_from,
    )
    db.add(tariff)
    db.commit()
    db.refresh(tariff)
    return tariff


@router.get("/tariffs", response_model=list[schemas.TariffOut])
def list_tariffs(
    municipality_id: int | None = None,
    active_only: bool = False,
    db: Session = Depends(get_db),
):
    stmt = select(FeeTariff)
    if municipality_id is not None:
        stmt = stmt.where(FeeTariff.municipality_id == municipality_id)
    if active_only:
        stmt = stmt.where(FeeTariff.valid_to.is_(None))
    return db.scalars(stmt.order_by(FeeTariff.id)).all()


@router.get("/tariffs/{tariff_id}", response_model=schemas.TariffOut)
def get_tariff(tariff_id: str, db: Session = Depends(get_db)):
    tariff = db.get(FeeTariff, tariff_id)
    if tariff is None:
        raise HTTPException(404, "tariff not found")
    return tariff


@router.post("/tariffs/{tariff_id}/revise", response_model=schemas.TariffOut, status_code=201)
def revise_tariff(tariff_id: str, payload: schemas.TariffRevise, db: Session = Depends(get_db)):
    old = db.get(FeeTariff, tariff_id)
    if old is None:
        raise HTTPException(404, "tariff not found")
    if old.valid_to is not None:
        raise HTTPException(409, "this tariff version is already superseded")
    if payload.act_id is not None and db.get(NormativeAct, payload.act_id) is None:
        raise HTTPException(400, f"unknown act_id: {payload.act_id}")
    _check_municipality(db, payload.municipality_id)

    new = FeeTariff(
        id=_new_id("FEE"),
        procedure_id=old.procedure_id,
        description=payload.description if payload.description is not None else old.description,
        basis=old.basis,
        rate=payload.rate if payload.rate is not None else old.rate,
        tiers=[t.model_dump() for t in payload.tiers] if payload.tiers is not None else old.tiers,
        min_fee=payload.min_fee if payload.min_fee is not None else old.min_fee,
        max_fee=payload.max_fee if payload.max_fee is not None else old.max_fee,
        municipality_id=payload.municipality_id if payload.municipality_id is not None else old.municipality_id,
        act_id=payload.act_id if payload.act_id is not None else old.act_id,
        valid_from=payload.valid_from,
    )
    old.valid_to = payload.valid_from
    db.add(new)
    db.commit()
    db.refresh(new)

    # 'Актуалност': recalc + notify subscribed projects that use this procedure.
    propagate_tariff_change(db, new.procedure_id, reason="актуалност: промяна в тарифа")
    return new


# --- Validation queue --------------------------------------------------------
@router.get("/validation-queue", response_model=list[schemas.ValidationQueueItem])
def validation_queue(status: str | None = None, db: Session = Depends(get_db)):
    stmt = (
        select(ValidationRequest, Project.name, User.email)
        .join(Project, Project.id == ValidationRequest.project_id)
        .join(User, User.id == ValidationRequest.user_id)
        .order_by(ValidationRequest.created_at.desc())
    )
    if status is not None:
        stmt = stmt.where(ValidationRequest.status == status)

    items = []
    for req, project_name, requester_email in db.execute(stmt).all():
        base = schemas.ValidationRequestOut.model_validate(req).model_dump()
        items.append(schemas.ValidationQueueItem(
            **base, project_name=project_name, requester_email=requester_email,
        ))
    return items


@router.patch("/validation-queue/{request_id}", response_model=schemas.ValidationRequestOut)
def review_validation(
    request_id: int,
    payload: schemas.ValidationReview,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    if payload.status not in REVIEW_STATUSES:
        raise HTTPException(400, f"status must be one of {sorted(REVIEW_STATUSES)}")
    req = db.get(ValidationRequest, request_id)
    if req is None:
        raise HTTPException(404, "validation request not found")
    if req.status in ("approved", "rejected"):
        raise HTTPException(409, "this request is already closed")

    req.status = payload.status
    if payload.review_note is not None:
        req.review_note = payload.review_note
    if payload.certified_pdf_url is not None:
        req.certified_pdf_url = payload.certified_pdf_url
    req.reviewed_at = datetime.now(timezone.utc)
    req.reviewed_by = admin.id
    db.commit()
    db.refresh(req)
    return req


# --- Procedure graph: procedures --------------------------------------------
# Unlike acts/tariffs (append-only, cited), the graph is editable config: past
# reports are snapshotted, so edits only affect future recalcs. None
# municipality_id = national step; set = required only in that municipality.
@router.post("/procedures", response_model=schemas.ProcedureOut, status_code=201)
def create_procedure(payload: schemas.ProcedureIn, db: Session = Depends(get_db)):
    _require(db, Institution, payload.institution_id, "institution_id")
    _require(db, NormativeAct, payload.act_id, "act_id")
    _require(db, Municipality, payload.municipality_id, "municipality_id")
    pid = payload.id or _new_id("PRO")
    if db.get(Procedure, pid) is not None:
        raise HTTPException(409, f"procedure {pid} already exists")
    if payload.term_basis not in ("calendar", "working"):
        raise HTTPException(400, "term_basis must be calendar or working")
    proc = Procedure(
        id=pid, name=payload.name, institution_id=payload.institution_id,
        statutory_term_days=payload.statutory_term_days, term_basis=payload.term_basis,
        act_id=payload.act_id, municipality_id=payload.municipality_id, note=payload.note,
    )
    db.add(proc)
    db.commit()
    db.refresh(proc)
    return proc


@router.get("/procedures", response_model=list[schemas.ProcedureOut])
def list_procedures(municipality_id: int | None = None, national: bool = True, db: Session = Depends(get_db)):
    stmt = select(Procedure)
    if municipality_id is not None:
        scope = [Procedure.municipality_id == municipality_id]
        if national:
            scope.append(Procedure.municipality_id.is_(None))
        stmt = stmt.where(or_(*scope))
    return db.scalars(stmt.order_by(Procedure.id)).all()


@router.patch("/procedures/{procedure_id}", response_model=schemas.ProcedureOut)
def update_procedure(procedure_id: str, payload: schemas.ProcedureUpdate, db: Session = Depends(get_db)):
    proc = db.get(Procedure, procedure_id)
    if proc is None:
        raise HTTPException(404, "procedure not found")
    _require(db, Institution, payload.institution_id, "institution_id")
    _require(db, NormativeAct, payload.act_id, "act_id")
    _require(db, Document, payload.output_document_id, "output_document_id")
    if payload.term_basis is not None and payload.term_basis not in ("calendar", "working"):
        raise HTTPException(400, "term_basis must be calendar or working")
    for field in ("name", "institution_id", "statutory_term_days", "term_basis", "act_id", "output_document_id", "note"):
        val = getattr(payload, field)
        if val is not None:
            setattr(proc, field, val)
    db.commit()
    db.refresh(proc)
    return proc


@router.delete("/procedures/{procedure_id}", status_code=204)
def delete_procedure(procedure_id: str, db: Session = Depends(get_db)):
    if db.get(Procedure, procedure_id) is None:
        raise HTTPException(404, "procedure not found")
    refs = []
    if db.scalar(select(ProjectNode.id).where(ProjectNode.procedure_id == procedure_id).limit(1)):
        refs.append("projects")
    if db.scalar(select(Dependency.successor_id).where(
            or_(Dependency.successor_id == procedure_id, Dependency.predecessor_id == procedure_id)).limit(1)):
        refs.append("dependencies")
    if db.scalar(select(FeeTariff.id).where(FeeTariff.procedure_id == procedure_id).limit(1)):
        refs.append("tariffs")
    if db.scalar(select(Rule.id).where(Rule.target_procedure_id == procedure_id).limit(1)):
        refs.append("rules")
    if refs:
        raise HTTPException(409, f"procedure is still referenced by: {', '.join(refs)}")
    db.delete(db.get(Procedure, procedure_id))
    db.commit()


# --- Procedure graph: rules --------------------------------------------------
@router.post("/rules", response_model=schemas.RuleOut, status_code=201)
def create_rule(payload: schemas.RuleIn, db: Session = Depends(get_db)):
    if payload.conditions:
        for c in payload.conditions:
            if c.op not in RULE_OPERATORS:
                raise HTTPException(400, f"condition op must be one of {sorted(RULE_OPERATORS)}")
    else:
        if not (payload.param_name and payload.operator and payload.value is not None):
            raise HTTPException(400, "provide either conditions[] or param_name+operator+value")
        if payload.operator not in RULE_OPERATORS:
            raise HTTPException(400, f"operator must be one of {sorted(RULE_OPERATORS)}")
    if payload.action not in RULE_ACTIONS:
        raise HTTPException(400, f"action must be one of {sorted(RULE_ACTIONS)}")
    _require(db, Procedure, payload.target_procedure_id, "target_procedure_id")
    _require(db, Institution, payload.target_institution_id, "target_institution_id")
    _require(db, Municipality, payload.municipality_id, "municipality_id")
    rid = payload.id or _new_id("R")
    if db.get(Rule, rid) is not None:
        raise HTTPException(409, f"rule {rid} already exists")
    rule = Rule(
        id=rid, param_name=payload.param_name, operator=payload.operator,
        value=payload.value, action=payload.action,
        conditions=[c.model_dump() for c in payload.conditions] if payload.conditions else None,
        target_procedure_id=payload.target_procedure_id,
        target_institution_id=payload.target_institution_id,
        municipality_id=payload.municipality_id, explanation=payload.explanation,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.get("/rules", response_model=list[schemas.RuleOut])
def list_rules(municipality_id: int | None = None, national: bool = True, db: Session = Depends(get_db)):
    stmt = select(Rule)
    if municipality_id is not None:
        scope = [Rule.municipality_id == municipality_id]
        if national:
            scope.append(Rule.municipality_id.is_(None))
        stmt = stmt.where(or_(*scope))
    return db.scalars(stmt.order_by(Rule.id)).all()


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: str, db: Session = Depends(get_db)):
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(404, "rule not found")
    db.delete(rule)
    db.commit()


# --- Procedure graph: dependencies -------------------------------------------
@router.post("/dependencies", response_model=schemas.DependencyOut, status_code=201)
def create_dependency(payload: schemas.DependencyIn, db: Session = Depends(get_db)):
    _require(db, Procedure, payload.successor_id, "successor_id")
    _require(db, Procedure, payload.predecessor_id, "predecessor_id")
    if payload.successor_id == payload.predecessor_id:
        raise HTTPException(400, "a procedure cannot depend on itself")
    _require(db, Municipality, payload.municipality_id, "municipality_id")
    if payload.link_type not in ("finish_start", "start_start"):
        raise HTTPException(400, "link_type must be finish_start or start_start")
    if db.get(Dependency, (payload.successor_id, payload.predecessor_id)) is not None:
        raise HTTPException(409, "this edge already exists")
    dep = Dependency(
        successor_id=payload.successor_id, predecessor_id=payload.predecessor_id,
        municipality_id=payload.municipality_id, link_type=payload.link_type,
        lag_days=payload.lag_days,
    )
    db.add(dep)
    db.commit()
    db.refresh(dep)
    return dep


@router.get("/dependencies", response_model=list[schemas.DependencyOut])
def list_dependencies(municipality_id: int | None = None, national: bool = True, db: Session = Depends(get_db)):
    stmt = select(Dependency)
    if municipality_id is not None:
        scope = [Dependency.municipality_id == municipality_id]
        if national:
            scope.append(Dependency.municipality_id.is_(None))
        stmt = stmt.where(or_(*scope))
    return db.scalars(stmt).all()


@router.delete("/dependencies/{successor_id}/{predecessor_id}", status_code=204)
def delete_dependency(successor_id: str, predecessor_id: str, db: Session = Depends(get_db)):
    dep = db.get(Dependency, (successor_id, predecessor_id))
    if dep is None:
        raise HTTPException(404, "dependency not found")
    db.delete(dep)
    db.commit()


# --- Documents ("what documents are needed") ---------------------------------
@router.post("/documents", response_model=schemas.DocumentOut, status_code=201)
def create_document(payload: schemas.DocumentIn, db: Session = Depends(get_db)):
    _require(db, Institution, payload.issuer_institution_id, "issuer_institution_id")
    did = payload.id or _new_id("DOC")
    if db.get(Document, did) is not None:
        raise HTTPException(409, f"document {did} already exists")
    doc = Document(
        id=did, name=payload.name, issuer_institution_id=payload.issuer_institution_id,
        doc_type=payload.doc_type, note=payload.note,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/documents", response_model=list[schemas.DocumentOut])
def list_documents(db: Session = Depends(get_db)):
    return db.scalars(select(Document).order_by(Document.id)).all()


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str, db: Session = Depends(get_db)):
    if db.get(Document, document_id) is None:
        raise HTTPException(404, "document not found")
    refs = []
    if db.scalar(select(ProcedureInput.document_id).where(ProcedureInput.document_id == document_id).limit(1)):
        refs.append("procedure inputs")
    if db.scalar(select(Procedure.id).where(Procedure.output_document_id == document_id).limit(1)):
        refs.append("procedure outputs")
    if refs:
        raise HTTPException(409, f"document is still referenced by: {', '.join(refs)}")
    db.delete(db.get(Document, document_id))
    db.commit()


# --- Procedure input documents (M:N) -----------------------------------------
@router.post("/procedures/{procedure_id}/inputs", status_code=201)
def add_procedure_input(procedure_id: str, payload: schemas.ProcedureInputIn, db: Session = Depends(get_db)):
    if db.get(Procedure, procedure_id) is None:
        raise HTTPException(404, "procedure not found")
    if db.get(Document, payload.document_id) is None:
        raise HTTPException(400, f"unknown document_id: {payload.document_id}")
    if db.get(ProcedureInput, (procedure_id, payload.document_id)) is not None:
        raise HTTPException(409, "this input document is already linked")
    db.add(ProcedureInput(procedure_id=procedure_id, document_id=payload.document_id))
    db.commit()
    return {"procedure_id": procedure_id, "document_id": payload.document_id}


@router.get("/procedures/{procedure_id}/inputs", response_model=list[schemas.DocumentOut])
def list_procedure_inputs(procedure_id: str, db: Session = Depends(get_db)):
    if db.get(Procedure, procedure_id) is None:
        raise HTTPException(404, "procedure not found")
    doc_ids = db.scalars(
        select(ProcedureInput.document_id).where(ProcedureInput.procedure_id == procedure_id)
    ).all()
    return db.scalars(select(Document).where(Document.id.in_(doc_ids)).order_by(Document.id)).all()


@router.delete("/procedures/{procedure_id}/inputs/{document_id}", status_code=204)
def remove_procedure_input(procedure_id: str, document_id: str, db: Session = Depends(get_db)):
    link = db.get(ProcedureInput, (procedure_id, document_id))
    if link is None:
        raise HTTPException(404, "input link not found")
    db.delete(link)
    db.commit()


# --- CSV bulk import (SPEC 5.3) ----------------------------------------------
# Raw CSV in the request body. dry_run=true validates and reports without
# writing — use it before the real import. All-or-nothing per file.
@router.post("/import/municipalities")
def import_municipalities_csv(
    dry_run: bool = False,
    body: bytes = Body(..., media_type="text/csv"),
    db: Session = Depends(get_db),
):
    try:
        return import_municipalities(db, body.decode("utf-8-sig"), dry_run=dry_run)
    except ImportError_ as e:
        raise HTTPException(422, {"errors": e.errors})


@router.post("/import/tariffs")
def import_tariffs_csv(
    dry_run: bool = False,
    body: bytes = Body(..., media_type="text/csv"),
    db: Session = Depends(get_db),
):
    try:
        return import_tariffs(db, body.decode("utf-8-sig"), dry_run=dry_run)
    except ImportError_ as e:
        raise HTTPException(422, {"errors": e.errors})


# The rest of the catalog. Import order respects FKs: institutions -> acts /
# documents -> procedures -> procedure-inputs / dependencies -> tariffs.
_IMPORTERS = {
    "institutions": import_csv.import_institutions,
    "acts": import_csv.import_acts,
    "documents": import_csv.import_documents,
    "procedures": import_csv.import_procedures,
    "procedure-inputs": import_csv.import_procedure_inputs,
    "dependencies": import_csv.import_dependencies,
}


@router.post("/import/{entity}")
def import_catalog_csv(
    entity: str,
    dry_run: bool = False,
    body: bytes = Body(..., media_type="text/csv"),
    db: Session = Depends(get_db),
):
    fn = _IMPORTERS.get(entity)
    if fn is None:
        raise HTTPException(404, f"no CSV importer for {entity!r}")
    try:
        return fn(db, body.decode("utf-8-sig"), dry_run=dry_run)
    except ImportError_ as e:
        raise HTTPException(422, {"errors": e.errors})

"""Admin endpoints — data entry for the regulatory knowledge (SPEC 5.3 / 7).

Restricted to role='admin'. Core data is append-only (SPEC 3.1): editing an act
or tariff never overwrites a row — it creates a new superseding version and
closes the old one with valid_to. This preserves reproducibility: past project
reports keep citing the exact row that was in force when they were computed.
"""
from __future__ import annotations

from datetime import date
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.base import get_db
from backend.db.models.app import User
from backend.db.models.core import NormativeAct, FeeTariff, Procedure, Municipality
from backend.api import schemas
from backend.api.deps import get_current_admin

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_current_admin)])

ALLOWED_BASES = {"fixed", "per_sqm_rzp", "pct_of_value", "per_mw"}
ALLOWED_LEVELS = {"state", "municipal"}


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
        municipality_id=payload.municipality_id if payload.municipality_id is not None else old.municipality_id,
        act_id=payload.act_id if payload.act_id is not None else old.act_id,
        valid_from=payload.valid_from,
    )
    old.valid_to = payload.valid_from
    db.add(new)
    db.commit()
    db.refresh(new)
    return new

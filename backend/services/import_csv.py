"""CSV bulk import — municipalities and tariffs (SPEC 5.3 'импорт от CSV').

Built for the real data-entry workflow: ordinances arrive as spreadsheets, one
row per fee/municipality. Imports are ALL-OR-NOTHING (any row error aborts the
whole file) and support dry_run, so a file can be validated before it writes.

Tariff semantics mirror the admin 'revise' endpoint: an in-force tariff for the
same (procedure, municipality) with a different rate is SUPERSEDED (closed with
valid_to, new row created); an identical one is skipped — so re-importing the
same file is a no-op and importing an updated ordinance rolls the version.

CSV format (UTF-8, comma-separated; Bulgarian decimal comma accepted in rate):

municipalities.csv:  name,region,coverage_status
tariffs.csv:         municipality,procedure_id,description,basis,rate,act_id,valid_from
                     (municipality empty = national; valid_from empty = today)
"""
from __future__ import annotations

import csv
import io
from datetime import date
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models.core import (
    Municipality, FeeTariff, Procedure, NormativeAct,
    Institution, Document, ProcedureInput, Dependency,
)

ALLOWED_BASES = {"fixed", "per_sqm_rzp", "pct_of_value", "per_mw"}
ALLOWED_COVERAGE = {"verified", "partial", "none"}

MUNICIPALITY_HEADERS = {"name"}
TARIFF_HEADERS = {"municipality", "procedure_id", "basis", "rate"}


class ImportError_(Exception):
    """Carries per-row errors for the whole rejected file."""
    def __init__(self, errors: list[dict]):
        self.errors = errors
        super().__init__(f"{len(errors)} row error(s)")


def _read(csv_text: str, required: set[str]) -> list[dict]:
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("﻿")))
    headers = set(reader.fieldnames or [])
    missing = required - headers
    if missing:
        raise ImportError_([{"row": 0, "error": f"missing column(s): {', '.join(sorted(missing))}"}])
    return [{k: (v or "").strip() for k, v in (row or {}).items()} for row in reader]


def _finish(db: Session, errors: list, dry_run: bool):
    """All-or-nothing: any error rolls the whole file back; dry-run never writes."""
    if errors:
        db.rollback()
        raise ImportError_(errors)
    if dry_run:
        db.rollback()
    else:
        db.commit()


def _opt_int(raw: str):
    return int(raw) if raw not in ("", None) else None


def import_municipalities(db: Session, csv_text: str, *, dry_run: bool = False) -> dict:
    rows = _read(csv_text, MUNICIPALITY_HEADERS)
    existing = {m.name: m for m in db.scalars(select(Municipality)).all()}

    created, updated, errors = 0, 0, []
    for i, row in enumerate(rows, start=2):  # row 1 = header
        name = row.get("name", "")
        coverage = row.get("coverage_status", "") or "none"
        if not name:
            errors.append({"row": i, "error": "empty name"})
            continue
        if coverage not in ALLOWED_COVERAGE:
            errors.append({"row": i, "error": f"coverage_status must be one of {sorted(ALLOWED_COVERAGE)}"})
            continue
        m = existing.get(name)
        if m is None:
            m = Municipality(name=name, region=row.get("region") or None, coverage_status=coverage)
            existing[name] = m
            if not dry_run:
                db.add(m)
            created += 1
        else:
            if row.get("region"):
                m.region = row["region"]
            m.coverage_status = coverage
            updated += 1

    if errors:
        db.rollback()
        raise ImportError_(errors)
    if dry_run:
        db.rollback()
    else:
        db.commit()
    return {"rows": len(rows), "created": created, "updated": updated, "dry_run": dry_run}


def _parse_rate(raw: str) -> float:
    return float(raw.replace(",", ".").replace(" ", ""))


def import_tariffs(db: Session, csv_text: str, *, dry_run: bool = False) -> dict:
    rows = _read(csv_text, TARIFF_HEADERS)

    municipalities = {m.name: m.id for m in db.scalars(select(Municipality)).all()}
    procedures = {p.id for p in db.scalars(select(Procedure)).all()}
    acts = {a.id for a in db.scalars(select(NormativeAct)).all()}

    # In-force tariffs keyed by (procedure, municipality) for supersede/skip.
    in_force: dict[tuple, FeeTariff] = {}
    for t in db.scalars(select(FeeTariff).where(FeeTariff.valid_to.is_(None))).all():
        in_force[(t.procedure_id, t.municipality_id)] = t

    created, superseded, skipped, errors = 0, 0, 0, []
    for i, row in enumerate(rows, start=2):
        mun_name = row.get("municipality", "")
        mun_id = None
        if mun_name:
            mun_id = municipalities.get(mun_name)
            if mun_id is None:
                errors.append({"row": i, "error": f"unknown municipality: {mun_name}"})
                continue
        if row["procedure_id"] not in procedures:
            errors.append({"row": i, "error": f"unknown procedure_id: {row['procedure_id']}"})
            continue
        if row["basis"] not in ALLOWED_BASES:
            errors.append({"row": i, "error": f"basis must be one of {sorted(ALLOWED_BASES)}"})
            continue
        act_id = row.get("act_id") or None
        if act_id is not None and act_id not in acts:
            errors.append({"row": i, "error": f"unknown act_id: {act_id}"})
            continue
        try:
            rate = _parse_rate(row["rate"])
            min_fee = _parse_rate(row["min_fee"]) if row.get("min_fee") else None
            max_fee = _parse_rate(row["max_fee"]) if row.get("max_fee") else None
        except ValueError:
            errors.append({"row": i, "error": f"bad number in rate/min_fee/max_fee"})
            continue
        try:
            valid_from = date.fromisoformat(row["valid_from"]) if row.get("valid_from") else date.today()
        except ValueError:
            errors.append({"row": i, "error": f"bad valid_from: {row['valid_from']!r} (use YYYY-MM-DD)"})
            continue

        key = (row["procedure_id"], mun_id)
        current = in_force.get(key)
        if (current is not None and current.basis == row["basis"] and current.rate == rate
                and current.min_fee == min_fee and current.max_fee == max_fee and current.tiers is None):
            skipped += 1
            continue

        new = FeeTariff(
            id=f"FEE-{uuid4().hex[:8]}",
            procedure_id=row["procedure_id"],
            description=row.get("description") or None,
            basis=row["basis"],
            rate=rate,
            min_fee=min_fee,
            max_fee=max_fee,
            municipality_id=mun_id,
            act_id=act_id,
            valid_from=valid_from,
        )
        if current is not None:
            current.valid_to = valid_from
            superseded += 1
        else:
            created += 1
        in_force[key] = new
        if not dry_run:
            db.add(new)

    if errors:
        db.rollback()
        raise ImportError_(errors)
    if dry_run:
        db.rollback()
    else:
        db.commit()
    return {
        "rows": len(rows), "created": created, "superseded": superseded,
        "skipped": skipped, "dry_run": dry_run,
    }


def import_institutions(db: Session, csv_text: str, *, dry_run: bool = False) -> dict:
    """Columns: id,name,type"""
    rows = _read(csv_text, {"id", "name"})
    existing = {i.id: i for i in db.scalars(select(Institution)).all()}
    created, updated, errors = 0, 0, []
    for i, row in enumerate(rows, start=2):
        if not row["id"] or not row["name"]:
            errors.append({"row": i, "error": "id and name are required"})
            continue
        obj = existing.get(row["id"])
        if obj is None:
            obj = Institution(id=row["id"], name=row["name"], inst_type=row.get("type") or None)
            existing[row["id"]] = obj
            if not dry_run:
                db.add(obj)
            created += 1
        else:
            obj.name = row["name"]
            if row.get("type"):
                obj.inst_type = row["type"]
            updated += 1
    _finish(db, errors, dry_run)
    return {"rows": len(rows), "created": created, "updated": updated, "dry_run": dry_run}


def import_acts(db: Session, csv_text: str, *, dry_run: bool = False) -> dict:
    """Columns: id,title,level,article,valid_from,municipality,source_url.
    Acts are append-only — an existing id is skipped (edit via the revise API)."""
    rows = _read(csv_text, {"id", "title", "level"})
    existing = {a.id for a in db.scalars(select(NormativeAct)).all()}
    municipalities = {m.name: m.id for m in db.scalars(select(Municipality)).all()}
    created, skipped, errors = 0, 0, []
    for i, row in enumerate(rows, start=2):
        if not row["id"] or not row["title"]:
            errors.append({"row": i, "error": "id and title are required"}); continue
        if row["level"] not in ("state", "municipal"):
            errors.append({"row": i, "error": "level must be state or municipal"}); continue
        mun_id = None
        if row.get("municipality"):
            mun_id = municipalities.get(row["municipality"])
            if mun_id is None:
                errors.append({"row": i, "error": f"unknown municipality: {row['municipality']}"}); continue
        try:
            vf = date.fromisoformat(row["valid_from"]) if row.get("valid_from") else date.today()
        except ValueError:
            errors.append({"row": i, "error": f"bad valid_from: {row['valid_from']!r}"}); continue
        if row["id"] in existing:
            skipped += 1; continue
        existing.add(row["id"])
        if not dry_run:
            db.add(NormativeAct(id=row["id"], title=row["title"], level=row["level"],
                                article=row.get("article") or None, valid_from=vf,
                                municipality_id=mun_id, source_url=row.get("source_url") or None))
        created += 1
    _finish(db, errors, dry_run)
    return {"rows": len(rows), "created": created, "skipped": skipped, "dry_run": dry_run}


def import_documents(db: Session, csv_text: str, *, dry_run: bool = False) -> dict:
    """Columns: id,name,issuer_institution_id,doc_type,note"""
    rows = _read(csv_text, {"id", "name"})
    existing = {d.id: d for d in db.scalars(select(Document)).all()}
    institutions = {i.id for i in db.scalars(select(Institution)).all()}
    created, updated, errors = 0, 0, []
    for i, row in enumerate(rows, start=2):
        if not row["id"] or not row["name"]:
            errors.append({"row": i, "error": "id and name are required"}); continue
        issuer = row.get("issuer_institution_id") or None
        if issuer and issuer not in institutions:
            errors.append({"row": i, "error": f"unknown issuer_institution_id: {issuer}"}); continue
        obj = existing.get(row["id"])
        if obj is None:
            obj = Document(id=row["id"], name=row["name"], issuer_institution_id=issuer,
                           doc_type=row.get("doc_type") or None, note=row.get("note") or None)
            existing[row["id"]] = obj
            if not dry_run:
                db.add(obj)
            created += 1
        else:
            obj.name = row["name"]
            obj.issuer_institution_id = issuer
            if row.get("doc_type"):
                obj.doc_type = row["doc_type"]
            updated += 1
    _finish(db, errors, dry_run)
    return {"rows": len(rows), "created": created, "updated": updated, "dry_run": dry_run}


def import_procedures(db: Session, csv_text: str, *, dry_run: bool = False) -> dict:
    """Columns: id,name,institution_id,statutory_term_days,term_basis,act_id,
    output_document_id,municipality,note"""
    rows = _read(csv_text, {"id", "name"})
    existing = {p.id: p for p in db.scalars(select(Procedure)).all()}
    institutions = {i.id for i in db.scalars(select(Institution)).all()}
    acts = {a.id for a in db.scalars(select(NormativeAct)).all()}
    documents = {d.id for d in db.scalars(select(Document)).all()}
    municipalities = {m.name: m.id for m in db.scalars(select(Municipality)).all()}
    created, updated, errors = 0, 0, []
    for i, row in enumerate(rows, start=2):
        if not row["id"] or not row["name"]:
            errors.append({"row": i, "error": "id and name are required"}); continue
        basis = row.get("term_basis") or "calendar"
        if basis not in ("calendar", "working"):
            errors.append({"row": i, "error": "term_basis must be calendar or working"}); continue
        inst = row.get("institution_id") or None
        if inst and inst not in institutions:
            errors.append({"row": i, "error": f"unknown institution_id: {inst}"}); continue
        act = row.get("act_id") or None
        if act and act not in acts:
            errors.append({"row": i, "error": f"unknown act_id: {act}"}); continue
        out_doc = row.get("output_document_id") or None
        if out_doc and out_doc not in documents:
            errors.append({"row": i, "error": f"unknown output_document_id: {out_doc}"}); continue
        mun_id = None
        if row.get("municipality"):
            mun_id = municipalities.get(row["municipality"])
            if mun_id is None:
                errors.append({"row": i, "error": f"unknown municipality: {row['municipality']}"}); continue
        try:
            term = _opt_int(row.get("statutory_term_days", ""))
        except ValueError:
            errors.append({"row": i, "error": f"bad statutory_term_days: {row.get('statutory_term_days')!r}"}); continue
        obj = existing.get(row["id"])
        if obj is None:
            obj = Procedure(id=row["id"], name=row["name"], institution_id=inst,
                            statutory_term_days=term, term_basis=basis, act_id=act,
                            output_document_id=out_doc, municipality_id=mun_id,
                            note=row.get("note") or None)
            existing[row["id"]] = obj
            if not dry_run:
                db.add(obj)
            created += 1
        else:
            obj.name, obj.institution_id, obj.statutory_term_days = row["name"], inst, term
            obj.term_basis, obj.act_id, obj.output_document_id = basis, act, out_doc
            updated += 1
    _finish(db, errors, dry_run)
    return {"rows": len(rows), "created": created, "updated": updated, "dry_run": dry_run}


def import_procedure_inputs(db: Session, csv_text: str, *, dry_run: bool = False) -> dict:
    """Columns: procedure_id,document_id"""
    rows = _read(csv_text, {"procedure_id", "document_id"})
    procedures = {p.id for p in db.scalars(select(Procedure)).all()}
    documents = {d.id for d in db.scalars(select(Document)).all()}
    seen = {(pi.procedure_id, pi.document_id) for pi in db.scalars(select(ProcedureInput)).all()}
    created, skipped, errors = 0, 0, []
    for i, row in enumerate(rows, start=2):
        if row["procedure_id"] not in procedures:
            errors.append({"row": i, "error": f"unknown procedure_id: {row['procedure_id']}"}); continue
        if row["document_id"] not in documents:
            errors.append({"row": i, "error": f"unknown document_id: {row['document_id']}"}); continue
        key = (row["procedure_id"], row["document_id"])
        if key in seen:
            skipped += 1; continue
        seen.add(key)
        if not dry_run:
            db.add(ProcedureInput(procedure_id=row["procedure_id"], document_id=row["document_id"]))
        created += 1
    _finish(db, errors, dry_run)
    return {"rows": len(rows), "created": created, "skipped": skipped, "dry_run": dry_run}


def import_dependencies(db: Session, csv_text: str, *, dry_run: bool = False) -> dict:
    """Columns: successor_id,predecessor_id,link_type,lag_days,municipality"""
    rows = _read(csv_text, {"successor_id", "predecessor_id"})
    procedures = {p.id for p in db.scalars(select(Procedure)).all()}
    municipalities = {m.name: m.id for m in db.scalars(select(Municipality)).all()}
    seen = {(d.successor_id, d.predecessor_id) for d in db.scalars(select(Dependency)).all()}
    created, skipped, errors = 0, 0, []
    for i, row in enumerate(rows, start=2):
        s, p = row["successor_id"], row["predecessor_id"]
        if s not in procedures or p not in procedures:
            errors.append({"row": i, "error": "successor_id/predecessor_id must be known procedures"}); continue
        if s == p:
            errors.append({"row": i, "error": "a procedure cannot depend on itself"}); continue
        link = row.get("link_type") or "finish_start"
        if link not in ("finish_start", "start_start"):
            errors.append({"row": i, "error": "link_type must be finish_start or start_start"}); continue
        try:
            lag = int(row["lag_days"]) if row.get("lag_days") else 0
        except ValueError:
            errors.append({"row": i, "error": f"bad lag_days: {row.get('lag_days')!r}"}); continue
        mun_id = None
        if row.get("municipality"):
            mun_id = municipalities.get(row["municipality"])
            if mun_id is None:
                errors.append({"row": i, "error": f"unknown municipality: {row['municipality']}"}); continue
        if (s, p) in seen:
            skipped += 1; continue
        seen.add((s, p))
        if not dry_run:
            db.add(Dependency(successor_id=s, predecessor_id=p, link_type=link,
                              lag_days=lag, municipality_id=mun_id))
        created += 1
    _finish(db, errors, dry_run)
    return {"rows": len(rows), "created": created, "skipped": skipped, "dry_run": dry_run}

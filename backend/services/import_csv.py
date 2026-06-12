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

from backend.db.models.core import Municipality, FeeTariff, Procedure, NormativeAct

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
    return [{k: (v or "").strip() for k, v in row.items()} for row in reader]


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
        except ValueError:
            errors.append({"row": i, "error": f"bad rate: {row['rate']!r}"})
            continue
        try:
            valid_from = date.fromisoformat(row["valid_from"]) if row.get("valid_from") else date.today()
        except ValueError:
            errors.append({"row": i, "error": f"bad valid_from: {row['valid_from']!r} (use YYYY-MM-DD)"})
            continue

        key = (row["procedure_id"], mun_id)
        current = in_force.get(key)
        if current is not None and current.basis == row["basis"] and current.rate == rate:
            skipped += 1
            continue

        new = FeeTariff(
            id=f"FEE-{uuid4().hex[:8]}",
            procedure_id=row["procedure_id"],
            description=row.get("description") or None,
            basis=row["basis"],
            rate=rate,
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

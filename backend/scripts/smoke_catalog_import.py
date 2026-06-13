"""Smoke test for the full-catalog CSV import (institutions/acts/documents/
procedures/procedure-inputs/dependencies). Covers dry-run, FK validation,
all-or-nothing, and idempotent re-import. Uses fixed test ids and cleans up.

Usage (server must be running on :8000):
    python -m backend.scripts.smoke_catalog_import
"""
import json
import os
import sys
import urllib.request
import urllib.error
import http.cookiejar

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from sqlalchemy import select
from backend.scripts.make_admin import make_admin
from backend.db.base import SessionLocal
from backend.db.models.app import User
from backend.db.models.core import Institution, NormativeAct, Document, Procedure, ProcedureInput, Dependency

BASE = os.getenv("BUILDFLOW_API", "http://127.0.0.1:8000")
EMAIL = "catimport@buildflow.bg"
PASSWORD = "catimport-123"
INST, ACT, DOC, PROC = "INST-CSV", "ACT-CSV", "DOC-CSV", "PRO-CSV"


def _opener():
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )


def _json(opener, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"}, method=method)
    try:
        with opener.open(req) as resp:
            raw = resp.read(); return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read(); return e.code, (json.loads(raw) if raw else None)


def _csv(opener, entity, text, dry_run=False):
    q = "?dry_run=true" if dry_run else ""
    req = urllib.request.Request(f"{BASE}/admin/import/{entity}{q}", data=text.encode("utf-8"),
                                 headers={"Content-Type": "text/csv"}, method="POST")
    try:
        with opener.open(req) as resp:
            raw = resp.read(); return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read(); return e.code, (json.loads(raw) if raw else None)


def _set_role(email, role):
    db = SessionLocal()
    try:
        u = db.scalar(select(User).where(User.email == email))
        if u:
            u.role = role; db.commit()
    finally:
        db.close()


def _cleanup():
    db = SessionLocal()
    try:
        db.query(ProcedureInput).filter(ProcedureInput.procedure_id == PROC).delete()
        db.query(Dependency).filter(Dependency.successor_id == PROC).delete()
        db.query(Procedure).filter(Procedure.id == PROC).delete()
        db.query(Document).filter(Document.id == DOC).delete()
        db.query(NormativeAct).filter(NormativeAct.id == ACT).delete()
        db.query(Institution).filter(Institution.id == INST).delete()
        db.commit()
    finally:
        db.close()


def _check(label, got, expected):
    ok = "OK " if got == expected else "FAIL"
    print(f"  [{ok}] {label}: got {got!r}, expected {expected!r}")
    assert got == expected, f"{label}: {got!r} != {expected!r}"


def main():
    op = _opener()
    st, _ = _json(op, "POST", "/auth/register", {"email": EMAIL, "password": PASSWORD, "gdpr_consent": True})
    if st == 409:
        _json(op, "POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    _set_role(EMAIL, "user")
    _cleanup()

    try:
        _check("non-admin import -> 403", _csv(op, "institutions", "id,name\nX,Y")[0], 403)
        make_admin(EMAIL)

        _check("unknown entity -> 404", _csv(op, "bogus", "a,b\n1,2")[0], 404)

        # institutions
        _check("institutions created", _csv(op, "institutions", f"id,name,type\n{INST},Тест институция,държавна")[1]["created"], 1)
        # acts (append-only: re-import skips)
        acts_csv = f"id,title,level,article,valid_from\n{ACT},Тестов акт,state,чл.1,2024-01-01"
        _check("acts created", _csv(op, "acts", acts_csv)[1]["created"], 1)
        _check("acts re-import skipped", _csv(op, "acts", acts_csv)[1]["skipped"], 1)
        # documents (FK to institution)
        _check("documents bad issuer -> 422",
               _csv(op, "documents", f"id,name,issuer_institution_id\n{DOC},Док,INST-NOPE")[0], 422)
        _check("documents created",
               _csv(op, "documents", f"id,name,issuer_institution_id\n{DOC},Тест документ,{INST}")[1]["created"], 1)
        # procedures (dry-run writes nothing, then real)
        proc_csv = f"id,name,institution_id,statutory_term_days,term_basis,act_id,output_document_id\n{PROC},Тест процедура,{INST},10,working,{ACT},{DOC}"
        _check("procedures dry-run", _csv(op, "procedures", proc_csv, dry_run=True)[1]["created"], 1)
        db = SessionLocal()
        try:
            assert db.get(Procedure, PROC) is None, "dry-run wrote a procedure!"
        finally:
            db.close()
        _check("procedures created", _csv(op, "procedures", proc_csv)[1]["created"], 1)
        _check("procedures re-import updates", _csv(op, "procedures", proc_csv)[1]["updated"], 1)
        _check("procedures bad act -> 422",
               _csv(op, "procedures", f"id,name,act_id\nPRO-X,x,ACT-NOPE")[0], 422)
        # procedure-inputs
        _check("inputs created", _csv(op, "procedure-inputs", f"procedure_id,document_id\n{PROC},{DOC}")[1]["created"], 1)
        _check("inputs re-import skipped", _csv(op, "procedure-inputs", f"procedure_id,document_id\n{PROC},{DOC}")[1]["skipped"], 1)
        # dependencies
        _check("self-dependency -> 422", _csv(op, "dependencies", f"successor_id,predecessor_id\n{PROC},{PROC}")[0], 422)
        _check("dependency created",
               _csv(op, "dependencies", f"successor_id,predecessor_id,link_type,lag_days\n{PROC},PRO-01,finish_start,5")[1]["created"], 1)

        print("\nSMOKE OK - full-catalog CSV import works (dry-run, FKs, idempotent).")
    finally:
        _cleanup()
        _set_role(EMAIL, "user")


if __name__ == "__main__":
    main()

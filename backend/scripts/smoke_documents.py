"""Smoke test for documents in the route (gap #3) + admin documents CRUD.

The route now answers "what documents are needed" — each step carries its input
documents and the document it produces. Admins can manage documents and link
them to procedures. Uses fixed ids + cleanup so nothing leaks.

Usage (server must be running on :8000):
    python -m backend.scripts.smoke_documents
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
from backend.db.models.core import Document, Procedure, ProcedureInput
from backend.data import seed

BASE = os.getenv("BUILDFLOW_API", "http://127.0.0.1:8000")
EMAIL = "docs@buildflow.bg"
PASSWORD = "docs-pass-123"
DOC, PROC = "DOC-TEST", "PRO-DOC-TEST"


def _opener():
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )


def _req(opener, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method=method,
    )
    try:
        with opener.open(req) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, (json.loads(raw) if raw else None)


def _set_role(email, role):
    db = SessionLocal()
    try:
        u = db.scalar(select(User).where(User.email == email))
        if u:
            u.role = role
            db.commit()
    finally:
        db.close()


def _remove():
    db = SessionLocal()
    try:
        db.query(ProcedureInput).filter(ProcedureInput.procedure_id == PROC).delete()
        db.query(Procedure).filter(Procedure.id == PROC).delete()
        db.query(Document).filter(Document.id == DOC).delete()
        db.commit()
    finally:
        db.close()


def _check(label, got, expected):
    ok = "OK " if got == expected else "FAIL"
    print(f"  [{ok}] {label}: got {got!r}, expected {expected!r}")
    assert got == expected, f"{label}: {got!r} != {expected!r}"


def main():
    op = _opener()
    st, _ = _req(op, "POST", "/auth/register", {"email": EMAIL, "password": PASSWORD, "gdpr_consent": True})
    if st == 409:
        _req(op, "POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    _set_role(EMAIL, "user")
    _remove()

    try:
        # --- the route now carries documents -----------------------------------
        _, p = _req(op, "POST", "/projects", {"name": "Docs", "project_type_id": "pv_ground",
                                              "tier": "pro", "params": dict(seed.ETALON_PARAMS)})
        _req(op, "POST", f"/projects/{p['id']}/recalc")
        _, route = _req(op, "GET", f"/projects/{p['id']}/sections/route")
        permit = next(s for s in route["data"]["route"] if s["procedure_id"] == "PRO-09")
        _check("PRO-09 has input documents", "Оценка за съответствие" in permit["input_documents"], True)
        _check("PRO-09 outputs the permit", permit["output_document"], "Разрешение за строеж")
        first = next(s for s in route["data"]["route"] if s["procedure_id"] == "PRO-01")
        _check("PRO-01 outputs the ownership doc", first["output_document"], "Документ за собственост/суперфиция")

        # --- admin documents CRUD + linking ------------------------------------
        _check("non-admin create -> 403", _req(op, "POST", "/admin/documents", {"name": "x"})[0], 403)
        make_admin(EMAIL)
        _check("create document", _req(op, "POST", "/admin/documents", {
            "id": DOC, "name": "Тестов документ", "issuer_institution_id": "INST-01"})[0], 201)
        _check("create procedure", _req(op, "POST", "/admin/procedures", {
            "id": PROC, "name": "Тестова стъпка", "institution_id": "INST-01"})[0], 201)

        _check("link input doc", _req(op, "POST", f"/admin/procedures/{PROC}/inputs", {"document_id": DOC})[0], 201)
        _check("duplicate link -> 409", _req(op, "POST", f"/admin/procedures/{PROC}/inputs", {"document_id": DOC})[0], 409)
        _, inputs = _req(op, "GET", f"/admin/procedures/{PROC}/inputs")
        _check("input listed", inputs[0]["id"], DOC)
        _check("set output document", _req(op, "PATCH", f"/admin/procedures/{PROC}",
                                           {"output_document_id": DOC})[0], 200)

        # referenced document can't be deleted
        _check("delete referenced doc -> 409", _req(op, "DELETE", f"/admin/documents/{DOC}")[0], 409)
        _check("unlink input -> 204", _req(op, "DELETE", f"/admin/procedures/{PROC}/inputs/{DOC}")[0], 204)
        _check("delete procedure -> 204", _req(op, "DELETE", f"/admin/procedures/{PROC}")[0], 204)
        _check("delete document now -> 204", _req(op, "DELETE", f"/admin/documents/{DOC}")[0], 204)

        print("\nSMOKE OK - documents surface in the route and are admin-manageable.")
    finally:
        _remove()
        _set_role(EMAIL, "user")


if __name__ == "__main__":
    main()

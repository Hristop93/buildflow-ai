"""Smoke test for the admin procedure-graph CRUD (procedures/rules/dependencies).

Lets the admin enter the graph — including municipal steps — via the API.
Validates create/list/patch/delete, referential delete guards, and tier/role
gating. Uses fixed ids + an inert rule so nothing leaks into recalc; cleans up.

Usage (server must be running on :8000):
    python -m backend.scripts.smoke_admin_graph
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
from backend.db.models.core import Procedure, Rule, Dependency, Municipality

BASE = os.getenv("BUILDFLOW_API", "http://127.0.0.1:8000")
EMAIL = "graph@buildflow.bg"
PASSWORD = "graph-pass-123"
NAT, VAR, RULE = "PRO-TEST-NAT", "PRO-TEST-VAR", "R-TEST"


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
        db.query(Dependency).filter(Dependency.successor_id == NAT).delete()
        db.query(Rule).filter(Rule.id == RULE).delete()
        db.query(Procedure).filter(Procedure.id.in_([NAT, VAR])).delete()
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

    db = SessionLocal()
    try:
        varna = db.scalar(select(Municipality.id).where(Municipality.name == "Варна"))
    finally:
        db.close()

    try:
        # role gating
        _check("non-admin create -> 403", _req(op, "POST", "/admin/procedures", {"name": "x"})[0], 403)
        make_admin(EMAIL)

        # procedures
        _check("create national procedure", _req(op, "POST", "/admin/procedures", {
            "id": NAT, "name": "Тестова процедура", "institution_id": "INST-01",
            "statutory_term_days": 12})[0], 201)
        _check("create Варна procedure", _req(op, "POST", "/admin/procedures", {
            "id": VAR, "name": "Варна стъпка", "institution_id": "INST-01", "municipality_id": varna})[0], 201)
        _check("bad institution -> 400", _req(op, "POST", "/admin/procedures", {
            "id": "PRO-X", "name": "x", "institution_id": "INST-NOPE"})[0], 400)
        _check("duplicate id -> 409", _req(op, "POST", "/admin/procedures", {"id": NAT, "name": "x"})[0], 409)

        # rules (inert: a param no project sets, so it never fires -> etalon safe)
        _check("bad operator -> 400", _req(op, "POST", "/admin/rules", {
            "param_name": "__t__", "operator": "~~", "value": "x", "action": "include"})[0], 400)
        _check("create rule", _req(op, "POST", "/admin/rules", {
            "id": RULE, "param_name": "__test_only__", "operator": "=", "value": "x",
            "action": "include", "target_procedure_id": NAT})[0], 201)

        # dependencies
        _check("self-dependency -> 400", _req(op, "POST", "/admin/dependencies", {
            "successor_id": NAT, "predecessor_id": NAT})[0], 400)
        _check("create dependency", _req(op, "POST", "/admin/dependencies", {
            "successor_id": NAT, "predecessor_id": "PRO-01"})[0], 201)
        _check("duplicate edge -> 409", _req(op, "POST", "/admin/dependencies", {
            "successor_id": NAT, "predecessor_id": "PRO-01"})[0], 409)

        # list scoping: Варна view shows national + Варна
        _, procs = _req(op, "GET", f"/admin/procedures?municipality_id={varna}")
        ids = {p["id"] for p in procs}
        _check("Варна list has national test proc", NAT in ids, True)
        _check("Варна list has Варна proc", VAR in ids, True)

        # update
        _, upd = _req(op, "PATCH", f"/admin/procedures/{NAT}", {"statutory_term_days": 20})
        _check("patch duration", upd["statutory_term_days"], 20)

        # referential delete guard, then ordered cleanup
        _check("delete referenced proc -> 409", _req(op, "DELETE", f"/admin/procedures/{NAT}")[0], 409)
        _check("delete dependency -> 204", _req(op, "DELETE", f"/admin/dependencies/{NAT}/PRO-01")[0], 204)
        _check("delete rule -> 204", _req(op, "DELETE", f"/admin/rules/{RULE}")[0], 204)
        _check("delete proc now -> 204", _req(op, "DELETE", f"/admin/procedures/{NAT}")[0], 204)
        _check("delete Варна proc -> 204", _req(op, "DELETE", f"/admin/procedures/{VAR}")[0], 204)

        print("\nSMOKE OK - admin can CRUD the procedure graph (incl. municipal steps).")
    finally:
        _remove()
        _set_role(EMAIL, "user")


if __name__ == "__main__":
    main()

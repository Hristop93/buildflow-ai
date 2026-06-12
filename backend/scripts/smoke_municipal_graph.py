"""Smoke test for municipality-scoped procedures/rules/dependencies (gap #1).

A municipality can require a different STEP, not just a different fee: a
municipal procedure (pulled in by a municipal include-rule) appears only for
projects in that municipality; projects elsewhere are unaffected. Inserts the
municipal graph rows directly (no admin API for procedures yet) and cleans up.

Usage (server must be running on :8000):
    python -m backend.scripts.smoke_municipal_graph
"""
import json
import os
import sys
import urllib.request
import urllib.error
import http.cookiejar

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from backend.db.base import SessionLocal
from backend.db.models.core import Procedure, Rule, Dependency, Municipality
from backend.db.models.app import ProjectNode
from backend.data import seed
from sqlalchemy import select

BASE = os.getenv("BUILDFLOW_API", "http://127.0.0.1:8000")
EMAIL = "mungraph@buildflow.bg"
PASSWORD = "mungraph-pass-123"
PROC, RULE = "MUN-VAR-TEST", "R-VAR-TEST"


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
        return e.code, (json.loads(e.read() or b"null"))


def _varna_id():
    db = SessionLocal()
    try:
        return db.scalar(select(Municipality.id).where(Municipality.name == "Варна"))
    finally:
        db.close()


def _install(varna):
    _remove()
    db = SessionLocal()
    try:
        db.add(Procedure(id=PROC, name="Общинско съгласуване (Варна)",
                         institution_id="INST-01", statutory_term_days=15, municipality_id=varna))
        db.flush()
        db.add(Rule(id=RULE, param_name="project_type", operator="=", value="pv_ground",
                    action="include", target_procedure_id=PROC, municipality_id=varna))
        db.add(Dependency(successor_id=PROC, predecessor_id="PRO-01",
                          link_type="finish_start", municipality_id=varna))
        db.commit()
    finally:
        db.close()


def _remove():
    db = SessionLocal()
    try:
        # project_nodes reference the procedure (recalc instantiates them).
        db.query(ProjectNode).filter(ProjectNode.procedure_id == PROC).delete()
        db.query(Dependency).filter(Dependency.successor_id == PROC).delete()
        db.query(Rule).filter(Rule.id == RULE).delete()
        db.query(Procedure).filter(Procedure.id == PROC).delete()
        db.commit()
    finally:
        db.close()


def _check(label, got, expected):
    ok = "OK " if got == expected else "FAIL"
    print(f"  [{ok}] {label}: got {got!r}, expected {expected!r}")
    assert got == expected, f"{label}: {got!r} != {expected!r}"


def _project(op, municipality_id=None):
    body = {"name": "Mun graph", "project_type_id": "pv_ground", "tier": "pro",
            "params": dict(seed.ETALON_PARAMS)}
    if municipality_id is not None:
        body["municipality_id"] = municipality_id
    _, p = _req(op, "POST", "/projects", body)
    _, r = _req(op, "POST", f"/projects/{p['id']}/recalc")
    return r


def main():
    op = _opener()
    st, _ = _req(op, "POST", "/auth/register", {"email": EMAIL, "password": PASSWORD, "gdpr_consent": True})
    if st == 409:
        _req(op, "POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})

    varna = _varna_id()
    _install(varna)
    try:
        nat = _project(op)
        var = _project(op, municipality_id=varna)

        _check("national stays 13 procedures", nat["summary"]["procedure_count"], 13)
        nat_has = any(s["procedure_id"] == PROC for s in nat["route"])
        _check("national does NOT include the municipal step", nat_has, False)

        _check("Варна gets 14 procedures", var["summary"]["procedure_count"], 14)
        var_step = next((s for s in var["route"] if s["procedure_id"] == PROC), None)
        _check("Варна includes the municipal step", var_step is not None, True)
        _check("municipal step scheduled after its predecessor", var_step["start_day"] >= 10, True)

        # national total days unchanged (the etalon), so the moat is per-municipality
        _check("national total_days = 420", nat["summary"]["total_days"], 420)

        print("\nSMOKE OK - municipality-scoped graph: extra step only where it applies.")
    finally:
        _remove()


if __name__ == "__main__":
    main()

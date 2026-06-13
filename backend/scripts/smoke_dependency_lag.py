"""Smoke test for dependency link types + lag (gap #6).

Two things: the admin API persists link_type/lag_days, and a lag on a real edge
actually shifts the schedule. Uses a Варна-scoped extra step wired with a +60d
lag so only the Варна project moves; the national project stays the etalon.
Inserts the municipal graph rows directly (admin has no UPDATE for edges) and
cleans up.

Usage (server must be running on :8000):
    python -m backend.scripts.smoke_dependency_lag
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
from backend.db.models.app import User, ProjectNode
from backend.db.models.core import Procedure, Rule, Dependency, Municipality
from backend.data import seed

BASE = os.getenv("BUILDFLOW_API", "http://127.0.0.1:8000")
EMAIL = "lag@buildflow.bg"
PASSWORD = "lag-pass-123"
PROC, RULE = "PRO-LAG-TEST", "R-LAG-TEST"


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


def _set_role(email, role):
    db = SessionLocal()
    try:
        u = db.scalar(select(User).where(User.email == email))
        if u:
            u.role = role
            db.commit()
    finally:
        db.close()


def _install(varna):
    _remove()
    db = SessionLocal()
    try:
        db.add(Procedure(id=PROC, name="Лаг тест стъпка", institution_id="INST-01",
                         statutory_term_days=10, municipality_id=varna))
        db.flush()
        db.add(Rule(id=RULE, param_name="project_type", operator="=", value="pv_ground",
                    action="include", target_procedure_id=PROC, municipality_id=varna))
        # +60d lag after PRO-13 (the last step, ends at 420), Варна only
        db.add(Dependency(successor_id=PROC, predecessor_id="PRO-13",
                          link_type="finish_start", lag_days=60, municipality_id=varna))
        db.commit()
    finally:
        db.close()


def _remove():
    db = SessionLocal()
    try:
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
    body = {"name": "Lag", "project_type_id": "pv_ground", "tier": "pro",
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
    _set_role(EMAIL, "user")

    db = SessionLocal()
    try:
        varna = db.scalar(select(Municipality.id).where(Municipality.name == "Варна"))
    finally:
        db.close()
    _install(varna)

    try:
        # --- admin API persists link_type + lag -------------------------------
        make_admin(EMAIL)
        _check("bad link_type -> 400", _req(op, "POST", "/admin/dependencies", {
            "successor_id": "PRO-13", "predecessor_id": "PRO-02", "link_type": "weird"})[0], 400)
        st, dep = _req(op, "POST", "/admin/dependencies", {
            "successor_id": "PRO-13", "predecessor_id": "PRO-02",
            "link_type": "start_start", "lag_days": 7})
        _check("create lagged edge -> 201", st, 201)
        _check("link_type persisted", dep["link_type"], "start_start")
        _check("lag_days persisted", dep["lag_days"], 7)
        _req(op, "DELETE", "/admin/dependencies/PRO-13/PRO-02")  # undo (don't pollute recalc)

        # --- lag actually shifts a real schedule ------------------------------
        nat = _project(op)
        var = _project(op, municipality_id=varna)
        _check("national stays the etalon", nat["summary"]["total_days"], 420)
        lag_step = next((s for s in var["route"] if s["procedure_id"] == PROC), None)
        _check("Варна includes the lagged step", lag_step is not None, True)
        # PRO-13 ends at 420; +60 lag -> step starts at 480, ends 490
        _check("lagged step starts at 480", lag_step["start_day"], 480)
        _check("Варна deadline extended by the lag", var["summary"]["total_days"], 490)

        print("\nSMOKE OK - dependency link types + lag drive the schedule.")
    finally:
        _remove()
        _set_role(EMAIL, "user")


if __name__ == "__main__":
    main()

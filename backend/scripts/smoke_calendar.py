"""Smoke test for the working-days calendar (gap #7).

A project start_date maps the schedule onto real dates; the etalon (all
calendar-day procedures) keeps 420 days. A procedure marked term_basis=working
has its term counted in working days, so its calendar span grows past the term.
Admin can set term_basis. Inserts a Варна working-day step directly and cleans up.

Usage (server must be running on :8000):
    python -m backend.scripts.smoke_calendar
"""
import json
import os
import sys
import urllib.request
import urllib.error
import http.cookiejar
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from sqlalchemy import select
from backend.scripts.make_admin import make_admin
from backend.db.base import SessionLocal
from backend.db.models.app import User, ProjectNode
from backend.db.models.core import Procedure, Rule, Dependency, Municipality
from backend.data import seed

BASE = os.getenv("BUILDFLOW_API", "http://127.0.0.1:8000")
EMAIL = "calendar@buildflow.bg"
PASSWORD = "calendar-pass-123"
PROC, RULE = "PRO-CAL-TEST", "R-CAL-TEST"


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
        db.add(Procedure(id=PROC, name="Работни-дни стъпка", institution_id="INST-01",
                         statutory_term_days=20, term_basis="working", municipality_id=varna))
        db.flush()
        db.add(Rule(id=RULE, param_name="project_type", operator="=", value="pv_ground",
                    action="include", target_procedure_id=PROC, municipality_id=varna))
        db.add(Dependency(successor_id=PROC, predecessor_id="PRO-01", municipality_id=varna))
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


def _project(op, params_extra=None, municipality_id=None):
    params = dict(seed.ETALON_PARAMS)
    if params_extra:
        params.update(params_extra)
    body = {"name": "Calendar", "project_type_id": "pv_ground", "tier": "pro", "params": params}
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
        # real dates + etalon preserved
        r = _project(op, {"start_date": "2025-01-06"})
        _check("etalon stays 420 with a start date", r["summary"]["total_days"], 420)
        pro01 = r["schedule"]["nodes"]["PRO-01"]
        _check("PRO-01 starts on the project start date", pro01["start_date"], "2025-01-06")
        _check("PRO-01 has an end date", "end_date" in pro01, True)

        # working-day step: 20 working days span > 20 calendar days
        var = _project(op, {"start_date": "2025-01-06"}, municipality_id=varna)
        step = var["schedule"]["nodes"].get(PROC)
        _check("working step present", step is not None, True)
        _check("20 working days span > 20 calendar days", step["duration"] > 20, True)

        # admin can set term_basis; bad value rejected
        make_admin(EMAIL)
        _check("bad term_basis -> 400", _req(op, "POST", "/admin/procedures",
               {"name": "x", "term_basis": "weird"})[0], 400)
        st, proc = _req(op, "POST", "/admin/procedures",
                        {"id": "PRO-CAL-API", "name": "Раб. дни (API)", "term_basis": "working"})
        _check("create working procedure", proc["term_basis"], "working")
        _req(op, "DELETE", "/admin/procedures/PRO-CAL-API")

        print("\nSMOKE OK - working-days calendar maps real dates; etalon preserved.")
    finally:
        _remove()
        _set_role(EMAIL, "user")


if __name__ == "__main__":
    main()

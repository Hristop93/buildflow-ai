"""Smoke test for per-municipality fee resolution (SPEC 4.2).

A municipality-specific tariff overrides the national one for projects in that
municipality, without double-counting; projects elsewhere keep the national
tariff. Restores the catalog afterwards so the etalon smokes stay valid.

Usage (server must be running on :8000):
    python -m backend.scripts.smoke_municipal_fees
"""
import json
import os
import sys
import urllib.request
import urllib.error
import http.cookiejar

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from sqlalchemy import select, func, delete
from backend.scripts.make_admin import make_admin
from backend.db.base import SessionLocal
from backend.db.models.app import User
from backend.db.models.core import FeeTariff
from backend.data import seed

BASE = os.getenv("BUILDFLOW_API", "http://127.0.0.1:8000")
EMAIL = "munfees@buildflow.bg"
PASSWORD = "munfees-pass-123"


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


def _cleanup_tariffs():
    db = SessionLocal()
    try:
        db.execute(delete(FeeTariff).where(func.length(FeeTariff.id) > 6))
        db.commit()
    finally:
        db.close()


def _check(label, got, expected):
    ok = "OK " if got == expected else "FAIL"
    print(f"  [{ok}] {label}: got {got!r}, expected {expected!r}")
    assert got == expected, f"{label}: {got!r} != {expected!r}"


def _project(op, municipality_id=None):
    body = {"name": "Mun fees", "project_type_id": "pv_ground", "tier": "pro",
            "params": dict(seed.ETALON_PARAMS)}
    if municipality_id is not None:
        body["municipality_id"] = municipality_id
    _, p = _req(op, "POST", "/projects", body)
    _, r = _req(op, "POST", f"/projects/{p['id']}/recalc")
    return p["id"], r


def _fees(op, pid):
    _, r = _req(op, "POST", f"/projects/{pid}/recalc")
    return r["summary"]["total_fees"]


def main():
    op = _opener()
    st, _ = _req(op, "POST", "/auth/register", {"email": EMAIL, "password": PASSWORD, "gdpr_consent": True})
    if st == 409:
        _req(op, "POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    _set_role(EMAIL, "user")
    _cleanup_tariffs()

    try:
        muns = _req(op, "GET", "/catalog/municipalities")[1]
        varna = next(m["id"] for m in muns if m["name"] == "Варна")

        national_pid, nat = _project(op)
        varna_pid, _ = _project(op, municipality_id=varna)
        _check("national baseline", nat["summary"]["total_fees"], 39870.0)
        _check("varna baseline (no local tariff yet)", _fees(op, varna_pid), 39870.0)

        # admin adds a Варна-specific tariff for PRO-09 (2.0 vs national 1.5)
        make_admin(EMAIL)
        st, _ = _req(op, "POST", "/admin/tariffs", {
            "procedure_id": "PRO-09", "basis": "per_sqm_rzp", "rate": 2.0,
            "municipality_id": varna, "description": "Варна — разрешение за строеж",
        })
        _check("create Варна tariff -> 201", st, 201)

        # Варна project picks it up (+250); national project unchanged
        _check("varna uses local tariff (+250)", _fees(op, varna_pid), 40120.0)
        _check("national still national", _fees(op, national_pid), 39870.0)

        # no double-count: PRO-09 has exactly one fee line for the Варна project
        _, fees_sec = _req(op, "GET", f"/projects/{varna_pid}/sections/fees")
        pro09 = [i for i in fees_sec["data"]["fees"]["items"] if i["procedure"] == "PRO-09"]
        _check("varna PRO-09 single line", len(pro09), 1)
        _check("varna PRO-09 amount = 1000", pro09[0]["amount"], 1000.0)

        print("\nSMOKE OK - municipal tariff overrides national, no double-count.")
    finally:
        _cleanup_tariffs()
        _set_role(EMAIL, "user")


if __name__ == "__main__":
    main()

"""Smoke test for tiered / clamped fees (gap #5) end to end.

An admin creates a progressive (bracketed) municipal tariff; a project in that
municipality computes the bracketed amount, while a national project keeps the
flat seed tariff. Cleans up so the etalon stays valid.

Usage (server must be running on :8000):
    python -m backend.scripts.smoke_tiered_fees
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
from backend.db.models.core import FeeTariff, Municipality
from backend.data import seed

BASE = os.getenv("BUILDFLOW_API", "http://127.0.0.1:8000")
EMAIL = "tiered@buildflow.bg"
PASSWORD = "tiered-pass-123"


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


def _cleanup():
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
    body = {"name": "Tiered", "project_type_id": "pv_ground", "tier": "pro",
            "params": dict(seed.ETALON_PARAMS)}
    if municipality_id is not None:
        body["municipality_id"] = municipality_id
    _, p = _req(op, "POST", "/projects", body)
    _, r = _req(op, "POST", f"/projects/{p['id']}/recalc")
    return p["id"], r


def main():
    op = _opener()
    st, _ = _req(op, "POST", "/auth/register", {"email": EMAIL, "password": PASSWORD, "gdpr_consent": True})
    if st == 409:
        _req(op, "POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    _set_role(EMAIL, "user")
    _cleanup()

    db = SessionLocal()
    try:
        varna = db.scalar(select(Municipality.id).where(Municipality.name == "Варна"))
    finally:
        db.close()

    try:
        make_admin(EMAIL)
        # PRO-09 base = rzp_sqm = 500. Brackets: first 200 @ 3.0, rest @ 1.0
        # -> 200*3 + 300*1 = 900 (vs national flat 1.5*500 = 750).
        st, _ = _req(op, "POST", "/admin/tariffs", {
            "procedure_id": "PRO-09", "basis": "per_sqm_rzp", "municipality_id": varna,
            "description": "Варна — прогресивна такса",
            "tiers": [{"up_to": 200, "rate": 3.0}, {"up_to": None, "rate": 1.0}],
        })
        _check("create tiered tariff -> 201", st, 201)

        _, nat = _project(op)
        _check("national flat fee total", nat["summary"]["total_fees"], 39870.0)

        vpid, var = _project(op, municipality_id=varna)
        _check("varna bracketed total (+150)", var["summary"]["total_fees"], 40020.0)
        _, fees = _req(op, "GET", f"/projects/{vpid}/sections/fees")
        pro09 = next(i for i in fees["data"]["fees"]["items"] if i["procedure"] == "PRO-09")
        _check("PRO-09 bracketed amount = 900", pro09["amount"], 900.0)
        _check("PRO-09 flagged tiered", pro09["tiered"], True)

        print("\nSMOKE OK - tiered/bracketed fees compute end to end.")
    finally:
        _cleanup()
        _set_role(EMAIL, "user")


if __name__ == "__main__":
    main()

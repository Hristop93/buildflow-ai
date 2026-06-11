"""Smoke test for the admin acts/tariffs API (SPEC 5.3 / 7).

Checks that admin endpoints reject non-admins (403), that an admin can create
and verify acts and tariffs, and that "revise" creates a new superseding
version while closing the old one with valid_to (append-only core data).

Usage (server must be running on :8000):
    python -m backend.scripts.smoke_admin
"""
import json
import os
import sys
import urllib.request
import urllib.error
import http.cookiejar

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from sqlalchemy import select, delete, func
from backend.scripts.make_admin import make_admin
from backend.db.base import SessionLocal
from backend.db.models.app import User
from backend.db.models.core import NormativeAct, FeeTariff

BASE = os.getenv("BUILDFLOW_API", "http://127.0.0.1:8000")
EMAIL = "admin@buildflow.bg"
PASSWORD = "admin-pass-123"


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


def _check(label, got, expected):
    ok = "OK " if got == expected else "FAIL"
    print(f"  [{ok}] {label}: got {got!r}, expected {expected!r}")
    assert got == expected, f"{label}: {got!r} != {expected!r}"


def _set_role(email, role):
    """Reset to a known role so the test is independent of previous runs."""
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        if user is not None:
            user.role = role
            db.commit()
    finally:
        db.close()


def _cleanup():
    """Remove every admin-created row so the shared dev DB returns to its
    seed-only catalog and the etalon smokes hold. Seed ids are 6 chars
    ('FEE-06'); admin ids are longer ('FEE-' + 8 hex), so length is a clean
    discriminator. Self-healing: also clears rows leaked by an interrupted run.
    (Production core data is append-only; this is test housekeeping.)"""
    db = SessionLocal()
    try:
        db.execute(delete(FeeTariff).where(func.length(FeeTariff.id) > 6))
        db.execute(delete(NormativeAct).where(func.length(NormativeAct.id) > 6))
        db.commit()
    finally:
        db.close()


def main():
    op = _opener()
    st, _ = _req(op, "POST", "/auth/register", {
        "email": EMAIL, "password": PASSWORD, "gdpr_consent": True,
    })
    if st == 409:
        _req(op, "POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})

    # --- non-admin is rejected -------------------------------------------------
    _set_role(EMAIL, "user")  # known starting state, regardless of prior runs
    _check("non-admin GET /admin/acts -> 403", _req(op, "GET", "/admin/acts")[0], 403)

    # promote, then the same session is admin (role is read fresh per request)
    make_admin(EMAIL)
    _check("after promotion GET /admin/acts -> 200", _req(op, "GET", "/admin/acts")[0], 200)

    try:
        # --- acts: create / verify / revise ------------------------------------
        print("acts:")
        st, act = _req(op, "POST", "/admin/acts", {
            "title": "ЗУТ", "level": "state", "article": "чл.150", "valid_from": "2024-01-01",
        })
        _check("create act", st, 201)
        act_id = act["id"]

        _, verified = _req(op, "POST", f"/admin/acts/{act_id}/verify")
        _check("verify sets verified_by", verified["verified_by"], EMAIL)

        st, new_act = _req(op, "POST", f"/admin/acts/{act_id}/revise", {
            "valid_from": "2025-06-01", "article": "чл.150 (изм.)",
        })
        _check("revise -> 201", st, 201)
        _check("new version supersedes old", new_act["supersedes_id"], act_id)
        _, old_act = _req(op, "GET", f"/admin/acts/{act_id}")
        _check("old act closed with valid_to", old_act["valid_to"], "2025-06-01")
        _check("revising a superseded act -> 409",
               _req(op, "POST", f"/admin/acts/{act_id}/revise", {"valid_from": "2025-07-01"})[0], 409)

        # --- tariffs: create / validation / revise -----------------------------
        print("tariffs:")
        st, tariff = _req(op, "POST", "/admin/tariffs", {
            "procedure_id": "PRO-09", "basis": "per_sqm_rzp", "rate": 2.0,
            "description": "Такса разрешение (нова)", "valid_from": "2024-01-01",
        })
        _check("create tariff", st, 201)
        tariff_id = tariff["id"]

        _check("bad basis -> 400", _req(op, "POST", "/admin/tariffs", {
            "procedure_id": "PRO-09", "basis": "bogus", "rate": 1})[0], 400)
        _check("unknown procedure -> 400", _req(op, "POST", "/admin/tariffs", {
            "procedure_id": "PRO-NOPE", "basis": "fixed", "rate": 1})[0], 400)

        st, new_tariff = _req(op, "POST", f"/admin/tariffs/{tariff_id}/revise", {
            "valid_from": "2025-06-01", "rate": 3.5,
        })
        _check("revise tariff -> 201", st, 201)
        _check("new rate applied", new_tariff["rate"], 3.5)
        _, old_tariff = _req(op, "GET", f"/admin/tariffs/{tariff_id}")
        _check("old tariff closed with valid_to", old_tariff["valid_to"], "2025-06-01")

        print("\nSMOKE OK - admin acts/tariffs CRUD + versioning enforced.")
    finally:
        _cleanup()
        _set_role(EMAIL, "user")  # leave the test user demoted


if __name__ == "__main__":
    main()

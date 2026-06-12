"""Smoke test for the expert-validation workflow (SPEC 5.2 / 5.3).

A dd user requests validation; a non-dd project is refused; duplicates are
blocked; an admin sees the queue (with project + requester context), moves the
request in_review -> approved with a certified PDF, and a closed request can't
be re-reviewed. Non-admins can't touch the queue.

Usage (server must be running on :8000):
    python -m backend.scripts.smoke_validation
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
from backend.data import seed

BASE = os.getenv("BUILDFLOW_API", "http://127.0.0.1:8000")
EMAIL = "validation@buildflow.bg"
PASSWORD = "validation-pass-123"


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


def _check(label, got, expected):
    ok = "OK " if got == expected else "FAIL"
    print(f"  [{ok}] {label}: got {got!r}, expected {expected!r}")
    assert got == expected, f"{label}: {got!r} != {expected!r}"


def _new_project(op, tier):
    _, p = _req(op, "POST", "/projects", {
        "name": f"Validation ({tier})", "project_type_id": "pv_ground",
        "tier": tier, "params": dict(seed.ETALON_PARAMS),
    })
    return p["id"]


def main():
    op = _opener()
    st, _ = _req(op, "POST", "/auth/register", {"email": EMAIL, "password": PASSWORD, "gdpr_consent": True})
    if st == 409:
        _req(op, "POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    _set_role(EMAIL, "user")  # known starting state

    try:
        # non-dd project can't request validation
        pid_pro = _new_project(op, "pro")
        _check("pro project -> 403", _req(op, "POST", f"/projects/{pid_pro}/validation", {})[0], 403)

        # dd project requests it
        pid = _new_project(op, "dd")
        _req(op, "POST", f"/projects/{pid}/recalc")
        st, req = _req(op, "POST", f"/projects/{pid}/validation", {"note": "моля за заверка"})
        _check("request -> 201", st, 201)
        _check("status requested", req["status"], "requested")
        rid = req["id"]
        _check("duplicate -> 409", _req(op, "POST", f"/projects/{pid}/validation", {})[0], 409)
        _, got = _req(op, "GET", f"/projects/{pid}/validation")
        _check("GET returns the request", got["id"], rid)

        # non-admin can't see the queue
        _check("non-admin queue -> 403", _req(op, "GET", "/admin/validation-queue")[0], 403)

        # promote, process the queue
        make_admin(EMAIL)
        st, queue = _req(op, "GET", "/admin/validation-queue?status=requested")
        _check("admin queue -> 200", st, 200)
        mine = next((q for q in queue if q["id"] == rid), None)
        _check("our request is in the queue", mine is not None, True)
        _check("queue item has project name", mine["project_name"], "Validation (dd)")
        _check("queue item has requester email", mine["requester_email"], EMAIL)

        _check("review -> in_review", _req(op, "PATCH", f"/admin/validation-queue/{rid}", {"status": "in_review"})[0], 200)
        st, approved = _req(op, "PATCH", f"/admin/validation-queue/{rid}", {
            "status": "approved", "review_note": "одобрено", "certified_pdf_url": "https://example.org/cert.pdf",
        })
        _check("approve -> 200", st, 200)
        _check("reviewed_by set", approved["reviewed_at"] is not None, True)

        # the requester sees the outcome
        _, final = _req(op, "GET", f"/projects/{pid}/validation")
        _check("requester sees approved", final["status"], "approved")
        _check("requester sees certificate", final["certified_pdf_url"], "https://example.org/cert.pdf")

        # can't re-review a closed request
        _check("re-review closed -> 409", _req(op, "PATCH", f"/admin/validation-queue/{rid}", {"status": "rejected"})[0], 409)

        print("\nSMOKE OK - expert-validation queue works end to end.")
    finally:
        _set_role(EMAIL, "user")


if __name__ == "__main__":
    main()

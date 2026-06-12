"""Smoke test for the 'Актуалност' subscription (SPEC 3 / 6 / 9).

A subscribed dd project is auto-recalculated and notified when a tariff it uses
is revised; an unsubscribed project is left untouched. Free projects can't
subscribe. Cleans up the revised tariff so the etalon smokes stay valid.

Usage (server must be running on :8000):
    python -m backend.scripts.smoke_subscription
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
from backend.db.models.core import FeeTariff
from backend.data import seed

BASE = os.getenv("BUILDFLOW_API", "http://127.0.0.1:8000")
EMAIL = "subscription@buildflow.bg"
PASSWORD = "subscription-pass-123"
TARIFF = "FEE-06"  # PRO-09, per_sqm_rzp, seed rate 1.5


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


def _restore_tariffs():
    """Delete admin-created tariff versions and un-supersede the seed FEE-06."""
    db = SessionLocal()
    try:
        from sqlalchemy import func, delete
        db.execute(delete(FeeTariff).where(func.length(FeeTariff.id) > 6))
        fee = db.get(FeeTariff, TARIFF)
        if fee is not None:
            fee.valid_to = None
        db.commit()
    finally:
        db.close()


def _check(label, got, expected):
    ok = "OK " if got == expected else "FAIL"
    print(f"  [{ok}] {label}: got {got!r}, expected {expected!r}")
    assert got == expected, f"{label}: {got!r} != {expected!r}"


def _new(op, tier):
    _, p = _req(op, "POST", "/projects", {
        "name": f"Subscription ({tier})", "project_type_id": "pv_ground",
        "tier": tier, "params": dict(seed.ETALON_PARAMS),
    })
    _req(op, "POST", f"/projects/{p['id']}/recalc")
    return p["id"]


def main():
    op = _opener()
    st, _ = _req(op, "POST", "/auth/register", {"email": EMAIL, "password": PASSWORD, "gdpr_consent": True})
    if st == 409:
        _req(op, "POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    _set_role(EMAIL, "user")
    _restore_tariffs()  # in case a previous run was interrupted

    try:
        # free can't subscribe
        free_pid = _new(op, "free")
        _check("free subscribe -> 403", _req(op, "POST", f"/projects/{free_pid}/subscription")[0], 403)

        # subscribed dd project (A) and an unsubscribed control (B)
        a = _new(op, "dd")
        _check("subscribe A -> 201", _req(op, "POST", f"/projects/{a}/subscription")[0], 201)
        _, sub = _req(op, "GET", f"/projects/{a}/subscription")
        _check("A subscription active", sub["status"], "active")

        b = _new(op, "dd")
        _, b_versions_before = _req(op, "GET", f"/projects/{b}/versions")

        # admin revises the PRO-09 tariff: 1.5 -> 3.0 (+750 on rzp 500)
        make_admin(EMAIL)
        st, _ = _req(op, "POST", f"/admin/tariffs/{TARIFF}/revise", {"valid_from": "2025-01-01", "rate": 3.0})
        _check("tariff revise -> 201", st, 201)

        # A (subscribed) was recalculated and notified
        _, a_journal = _req(op, "GET", f"/projects/{a}/sections/journal")
        recalc_ev = [e for e in a_journal["data"]["journal"] if e["event_type"] == "subscription_recalc"]
        _check("A got a subscription_recalc notification", len(recalc_ev), 1)
        _check("A fees delta = +750", recalc_ev[0]["payload"]["fees_delta"], 750.0)

        # B (not subscribed) was left untouched
        _, b_versions_after = _req(op, "GET", f"/projects/{b}/versions")
        _check("B not auto-recalculated", len(b_versions_after), len(b_versions_before))
        _, b_journal = _req(op, "GET", f"/projects/{b}/sections/journal")
        _check("B has no subscription_recalc", any(e["event_type"] == "subscription_recalc" for e in b_journal["data"]["journal"]), False)

        # unsubscribe
        _check("unsubscribe -> 204", _req(op, "DELETE", f"/projects/{a}/subscription")[0], 204)
        _, after = _req(op, "GET", f"/projects/{a}/subscription")
        _check("subscription cleared", after, None)

        print("\nSMOKE OK - 'Актуалност' auto-recalcs + notifies only subscribers.")
    finally:
        _restore_tariffs()
        _set_role(EMAIL, "user")


if __name__ == "__main__":
    main()

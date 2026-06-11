"""Smoke test for the editable schedule (SPEC 5.2 real-time contract).

Edits a node's duration via PATCH /projects/{id}/nodes/{procedure_id} and
verifies the whole pipeline reacts: CPM total moves 420 -> 450 (PRO-11 is on
the critical path), the response carries the delta for the banner, clearing
the override returns to 420, validation (reason on delay, tier gating) holds,
and the journal logs the edit.

Usage (server must be running on :8000):
    python -m backend.scripts.smoke_schedule_edit
"""
import json
import os
import sys
import urllib.request
import urllib.error
import http.cookiejar

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from backend.data import seed

BASE = os.getenv("BUILDFLOW_API", "http://127.0.0.1:8000")
EMAIL = "schedule@buildflow.bg"
PASSWORD = "schedule-pass-123"


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


def _new_project(op, tier):
    _, p = _req(op, "POST", "/projects", {
        "name": f"Schedule edit ({tier})",
        "project_type_id": "pv_ground",
        "tier": tier,
        "params": dict(seed.ETALON_PARAMS),
    })
    return p["id"]


def main():
    op = _opener()
    st, _ = _req(op, "POST", "/auth/register", {
        "email": EMAIL, "password": PASSWORD, "gdpr_consent": True,
    })
    if st == 409:
        _req(op, "POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})

    pid = _new_project(op, "dd")
    _, base = _req(op, "POST", f"/projects/{pid}/recalc")
    _check("baseline total_days", base["summary"]["total_days"], 420)

    # --- validation ------------------------------------------------------------
    _check("delayed without reason -> 400",
           _req(op, "PATCH", f"/projects/{pid}/nodes/PRO-11", {"status": "delayed"})[0], 400)
    _check("unknown procedure -> 404",
           _req(op, "PATCH", f"/projects/{pid}/nodes/PRO-99", {"status": "done"})[0], 404)
    _check("empty patch -> 400",
           _req(op, "PATCH", f"/projects/{pid}/nodes/PRO-11", {})[0], 400)

    # --- the real-time contract: +30 days on a critical node --------------------
    st, r = _req(op, "PATCH", f"/projects/{pid}/nodes/PRO-11", {
        "planned_duration_days": 150, "status": "delayed",
        "reason": "забавена доставка на панели",
    })
    _check("edit critical node -> 200", st, 200)
    _check("delta_days = +30", r["delta_days"], 30)
    _check("new total = 450", r["result"]["summary"]["total_days"], 450)
    _check("delta_irr reported", r["delta_irr_pp"] is not None, True)

    _, sec = _req(op, "GET", f"/projects/{pid}/sections/schedule")
    _check("schedule section reflects 450", sec["data"]["schedule"]["total_days"], 450)
    _check("node duration shows 150",
           sec["data"]["schedule"]["nodes"]["PRO-11"]["duration"], 150)

    # --- clearing the override returns to statutory ------------------------------
    st, r2 = _req(op, "PATCH", f"/projects/{pid}/nodes/PRO-11", {
        "planned_duration_days": None, "status": "active",
    })
    _check("clear override -> 200", st, 200)
    _check("back to 420", r2["result"]["summary"]["total_days"], 420)
    _check("delta_days = -30", r2["delta_days"], -30)

    # --- journal carries the edits ----------------------------------------------
    _, j = _req(op, "GET", f"/projects/{pid}/sections/journal")
    kinds = [e["event_type"] for e in j["data"]["journal"]]
    _check("journal has node_changed", "node_changed" in kinds, True)

    # --- tier gating --------------------------------------------------------------
    pid_std = _new_project(op, "standard")
    _req(op, "POST", f"/projects/{pid_std}/recalc")
    _check("standard tier edit -> 403",
           _req(op, "PATCH", f"/projects/{pid_std}/nodes/PRO-11", {"status": "done"})[0], 403)

    print("\nSMOKE OK - editable schedule drives recalc with honest deltas.")


if __name__ == "__main__":
    main()

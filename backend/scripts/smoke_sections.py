"""Smoke test for tier-gated section reads (SPEC 6).

Proves the server enforces tier access: a standard project can read
summary/route/fees but is locked out of economics (pro) and risk (dd);
a pro project unlocks economics and journal; a dd project reaches risk/export
(501 until those phases land). Also checks 409 before recalc and 404 for
unknown sections.

Usage (server must be running on :8000):
    python -m backend.scripts.smoke_sections
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
EMAIL = "sections@buildflow.bg"
PASSWORD = "sections-pass-123"


def _opener():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def _req(opener, method, path, body=None):
    """Return (status, parsed_body) without raising on HTTP error statuses."""
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


def _authenticate(opener):
    st, _ = _req(opener, "POST", "/auth/register", {
        "email": EMAIL, "password": PASSWORD, "gdpr_consent": True,
    })
    if st == 409:
        _req(opener, "POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})


def _new_project(opener, tier):
    _, p = _req(opener, "POST", "/projects", {
        "name": f"Sections {tier}",
        "project_type_id": "pv_ground",
        "tier": tier,
        "params": dict(seed.ETALON_PARAMS),
    })
    return p["id"]


def _check(label, got, expected):
    ok = "OK " if got == expected else "FAIL"
    print(f"  [{ok}] {label}: got {got}, expected {expected}")
    assert got == expected, f"{label}: {got} != {expected}"


def main():
    op = _opener()
    _authenticate(op)

    # --- 409 before any recalc -------------------------------------------------
    pid = _new_project(op, "standard")
    st, _ = _req(op, "GET", f"/projects/{pid}/sections/summary")
    _check("summary before recalc -> 409", st, 409)
    _req(op, "POST", f"/projects/{pid}/recalc")

    # --- standard tier ---------------------------------------------------------
    print("standard project:")
    _check("summary (free)", _req(op, "GET", f"/projects/{pid}/sections/summary")[0], 200)
    _check("route (standard)", _req(op, "GET", f"/projects/{pid}/sections/route")[0], 200)
    _check("fees (standard)", _req(op, "GET", f"/projects/{pid}/sections/fees")[0], 200)
    st, body = _req(op, "GET", f"/projects/{pid}/sections/economics")
    _check("economics (pro) locked", st, 403)
    _check("  required_tier=pro", body["detail"]["required_tier"], "pro")
    _check("risk (dd) locked", _req(op, "GET", f"/projects/{pid}/sections/risk")[0], 403)
    _check("unknown section -> 404", _req(op, "GET", f"/projects/{pid}/sections/nope")[0], 404)

    # --- pro tier --------------------------------------------------------------
    print("pro project:")
    pid = _new_project(op, "pro")
    _req(op, "POST", f"/projects/{pid}/recalc")
    _check("economics (pro)", _req(op, "GET", f"/projects/{pid}/sections/economics")[0], 200)
    _check("journal (pro)", _req(op, "GET", f"/projects/{pid}/sections/journal")[0], 200)
    _check("risk (dd) locked", _req(op, "GET", f"/projects/{pid}/sections/risk")[0], 403)

    # --- dd tier ---------------------------------------------------------------
    print("dd project:")
    pid = _new_project(op, "dd")
    _req(op, "POST", f"/projects/{pid}/recalc")
    _check("economics (pro)", _req(op, "GET", f"/projects/{pid}/sections/economics")[0], 200)
    _check("risk allowed but unbuilt -> 501", _req(op, "GET", f"/projects/{pid}/sections/risk")[0], 501)
    _check("export allowed but unbuilt -> 501", _req(op, "GET", f"/projects/{pid}/sections/export")[0], 501)

    print("\nSMOKE OK - tier gating enforced across free/standard/pro/dd.")


if __name__ == "__main__":
    main()

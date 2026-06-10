"""End-to-end smoke test for the auth + recalc API against a running server.

Registers (or logs in), then creates a project with the etalon PV params and
runs recalc, asserting the pipeline reproduces the Excel etalon
(420 days, 39 870 BGN, IRR ~11.8%). Also checks that an unauthenticated
request is rejected.

Usage (server must be running on :8000):
    python -m backend.scripts.smoke_recalc
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
EMAIL = "smoke@buildflow.bg"
PASSWORD = "smoke-pass-123"


def _make_opener():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def _req(opener, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method=method,
    )
    with opener.open(req) as resp:
        raw = resp.read()
        return resp.status, (json.loads(raw) if raw else None)


def _authenticate(opener):
    try:
        _req(opener, "POST", "/auth/register", {
            "email": EMAIL, "password": PASSWORD,
            "full_name": "Smoke Test", "gdpr_consent": True,
        })
        print("registered new user")
    except urllib.error.HTTPError as e:
        if e.code == 409:
            _req(opener, "POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
            print("logged in existing user")
        else:
            raise


def main():
    # 1) Unauthenticated project creation must be rejected.
    bare = _make_opener()
    try:
        _req(bare, "POST", "/projects", {"name": "x", "project_type_id": "pv_ground"})
        raise SystemExit("FAIL: unauthenticated create was not rejected")
    except urllib.error.HTTPError as e:
        assert e.code == 401, e.code
        print("unauthenticated create -> 401 (correct)")

    # 2) Authenticate, create project, recalc.
    opener = _make_opener()
    _authenticate(opener)

    _, me = _req(opener, "GET", "/auth/me")
    print(f"  /me -> {me['email']}")

    _, project = _req(opener, "POST", "/projects", {
        "name": "Etalon PV (smoke)",
        "project_type_id": "pv_ground",
        "tier": "pro",
        "params": dict(seed.ETALON_PARAMS),
    })
    pid = project["id"]
    print(f"created project id={pid}")

    _, result = _req(opener, "POST", f"/projects/{pid}/recalc")
    s = result["summary"]
    e = result["economics"]
    print(f"  procedures : {s['procedure_count']}")
    print(f"  total_days : {s['total_days']}")
    print(f"  total_fees : {s['total_fees']}")
    print(f"  irr        : {e['irr']:.4f}")
    print(f"  verdict    : {e['verdict']}")
    print(f"  version_no : {result['version_no']}")

    assert s["procedure_count"] == 13, s["procedure_count"]
    assert s["total_days"] == 420, s["total_days"]
    assert round(s["total_fees"]) == 39870, s["total_fees"]
    assert abs(e["irr"] - 0.1178) < 0.0015, e["irr"]
    assert e["verdict"] == "relevant", e["verdict"]
    print("\nSMOKE OK - auth + recalc reproduce the etalon end-to-end.")


if __name__ == "__main__":
    main()

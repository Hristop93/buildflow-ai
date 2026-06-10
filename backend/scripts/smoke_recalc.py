"""End-to-end smoke test for the recalc API against a running server.

Creates a project with the etalon PV params, runs recalc, and asserts the
pipeline reproduces the Excel etalon (420 days, 39 870 BGN, IRR ~11.8%).

Usage (server must be running on :8000):
    python -m backend.scripts.smoke_recalc
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from backend.data import seed

BASE = os.getenv("BUILDFLOW_API", "http://127.0.0.1:8000")


def _post(path, body):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def main():
    params = dict(seed.ETALON_PARAMS)
    project = _post("/projects", {
        "name": "Etalon PV (smoke)",
        "project_type_id": "pv_ground",
        "tier": "pro",
        "params": params,
    })
    pid = project["id"]
    print(f"created project id={pid}")

    result = _post(f"/projects/{pid}/recalc", {})
    s = result["summary"]
    e = result["economics"]
    print(f"  procedures : {s['procedure_count']}")
    print(f"  total_days : {s['total_days']}")
    print(f"  total_fees : {s['total_fees']}")
    print(f"  irr        : {e['irr']:.4f}")
    print(f"  npv        : {e['npv']:.0f}")
    print(f"  verdict    : {e['verdict']}")
    print(f"  version_no : {result['version_no']}")

    assert s["procedure_count"] == 13, s["procedure_count"]
    assert s["total_days"] == 420, s["total_days"]
    assert round(s["total_fees"]) == 39870, s["total_fees"]
    assert abs(e["irr"] - 0.1178) < 0.0015, e["irr"]
    assert e["verdict"] == "relevant", e["verdict"]
    print("\nSMOKE OK — recalc reproduces the etalon end-to-end.")


if __name__ == "__main__":
    main()

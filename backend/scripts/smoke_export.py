"""Smoke test for the Excel export (SPEC 5.2 Експорт, dd tier).

Verifies a dd project downloads a valid .xlsx with the expected sheets, that a
pro project is gated out (403), and that export before recalc is 409.

Usage (server must be running on :8000):
    python -m backend.scripts.smoke_export
"""
import io
import json
import os
import sys
import urllib.request
import urllib.error
import http.cookiejar
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from backend.data import seed

BASE = os.getenv("BUILDFLOW_API", "http://127.0.0.1:8000")
EMAIL = "export@buildflow.bg"
PASSWORD = "export-pass-123"


def _opener():
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )


def _json(opener, method, path, body=None):
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
        return e.code, None


def _download(opener, path):
    req = urllib.request.Request(BASE + path, method="GET")
    try:
        with opener.open(req) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def _check(label, got, expected):
    ok = "OK " if got == expected else "FAIL"
    print(f"  [{ok}] {label}: got {got!r}, expected {expected!r}")
    assert got == expected, f"{label}: {got!r} != {expected!r}"


def _new_project(op, tier):
    _, p = _json(op, "POST", "/projects", {
        "name": f"Export ({tier})", "project_type_id": "pv_ground",
        "tier": tier, "params": dict(seed.ETALON_PARAMS),
    })
    return p["id"]


def main():
    op = _opener()
    st, _ = _json(op, "POST", "/auth/register", {"email": EMAIL, "password": PASSWORD, "gdpr_consent": True})
    if st == 409:
        _json(op, "POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})

    # export before recalc -> 409
    pid = _new_project(op, "dd")
    _check("export before recalc -> 409", _download(op, f"/projects/{pid}/export/xlsx")[0], 409)

    # recalc then download
    _json(op, "POST", f"/projects/{pid}/recalc")
    status, headers, body = _download(op, f"/projects/{pid}/export/xlsx")
    _check("download -> 200", status, 200)
    _check("content-type is xlsx", "spreadsheetml" in headers.get("Content-Type", ""), True)
    _check("attachment filename set", "attachment" in headers.get("Content-Disposition", ""), True)

    # valid xlsx (it's a zip) with the expected sheets
    zf = zipfile.ZipFile(io.BytesIO(body))
    workbook_xml = zf.read("xl/workbook.xml").decode("utf-8")
    for sheet in ["Резюме", "Маршрут", "Такси", "График", "Икономика"]:
        _check(f"sheet '{sheet}' present", sheet in workbook_xml, True)
    print(f"        workbook size: {len(body)} bytes")

    # pro tier is gated out
    pid_pro = _new_project(op, "pro")
    _json(op, "POST", f"/projects/{pid_pro}/recalc")
    _check("pro tier export -> 403", _download(op, f"/projects/{pid_pro}/export/xlsx")[0], 403)

    print("\nSMOKE OK - dd Excel export works and is tier-gated.")


if __name__ == "__main__":
    main()

"""Smoke test for the CSV bulk import (SPEC 5.3).

Validates the real data-entry workflow: dry-run reports errors without writing;
a valid file imports municipalities and tariffs; re-importing the same file is
a no-op (skipped); an updated rate supersedes the old tariff; and recalc picks
the imported municipal tariff up. Cleans up everything it created.

Usage (server must be running on :8000):
    python -m backend.scripts.smoke_import
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
from backend.db.models.app import User, Project, ProjectParam, ProjectVersion, ProjectNode, Event
from backend.db.models.core import FeeTariff, Municipality
from backend.data import seed

BASE = os.getenv("BUILDFLOW_API", "http://127.0.0.1:8000")
EMAIL = "import@buildflow.bg"
PASSWORD = "import-pass-123"
TEST_MUNS = ["Тест-Импорт-1", "Тест-Импорт-2"]


def _opener():
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )


def _req(opener, method, path, body=None, *, csv=None):
    if csv is not None:
        data, ctype = csv.encode("utf-8"), "text/csv"
    elif body is not None:
        data, ctype = json.dumps(body).encode(), "application/json"
    else:
        data, ctype = None, "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": ctype}, method=method)
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


def _cleanup():
    db = SessionLocal()
    try:
        mun_ids = [m.id for m in db.scalars(
            select(Municipality).where(Municipality.name.in_(TEST_MUNS))).all()]
        if mun_ids:
            # projects created in the test municipality (and their children)
            proj_ids = [p.id for p in db.scalars(
                select(Project).where(Project.municipality_id.in_(mun_ids))).all()]
            if proj_ids:
                for model in (Event, ProjectVersion, ProjectNode, ProjectParam):
                    db.execute(delete(model).where(model.project_id.in_(proj_ids)))
                db.execute(delete(Project).where(Project.id.in_(proj_ids)))
            db.execute(delete(FeeTariff).where(FeeTariff.municipality_id.in_(mun_ids)))
            db.execute(delete(Municipality).where(Municipality.id.in_(mun_ids)))
        db.execute(delete(FeeTariff).where(func.length(FeeTariff.id) > 6))
        db.commit()
    finally:
        db.close()


def _check(label, got, expected):
    ok = "OK " if got == expected else "FAIL"
    print(f"  [{ok}] {label}: got {got!r}, expected {expected!r}")
    assert got == expected, f"{label}: {got!r} != {expected!r}"


def main():
    op = _opener()
    st, _ = _req(op, "POST", "/auth/register", {"email": EMAIL, "password": PASSWORD, "gdpr_consent": True})
    if st == 409:
        _req(op, "POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    _set_role(EMAIL, "user")
    _cleanup()

    try:
        _check("non-admin import -> 403",
               _req(op, "POST", "/admin/import/municipalities", csv="name\nX")[0], 403)
        make_admin(EMAIL)

        # --- municipalities ------------------------------------------------------
        bad = "name,region,coverage_status\nТест-Импорт-1,Юг,bogus\n"
        st, body = _req(op, "POST", "/admin/import/municipalities", csv=bad)
        _check("bad coverage -> 422", st, 422)
        _check("error names the row", body["detail"]["errors"][0]["row"], 2)

        good = "name,region,coverage_status\nТест-Импорт-1,Юг,partial\nТест-Импорт-2,Север,none\n"
        st, dry = _req(op, "POST", "/admin/import/municipalities?dry_run=true", csv=good)
        _check("dry-run reports 2 created", dry["created"], 2)
        _, muns = _req(op, "GET", "/catalog/municipalities")
        _check("dry-run wrote nothing", any(m["name"] in TEST_MUNS for m in muns), False)

        st, real = _req(op, "POST", "/admin/import/municipalities", csv=good)
        _check("import municipalities", real["created"], 2)
        _, muns = _req(op, "GET", "/catalog/municipalities")
        test_mun = next(m for m in muns if m["name"] == "Тест-Импорт-1")

        # --- tariffs ---------------------------------------------------------------
        tariffs = (
            "municipality,procedure_id,description,basis,rate,act_id,valid_from\n"
            "Тест-Импорт-1,PRO-09,Разрешение (тест),per_sqm_rzp,\"2,5\",ACT-04,2025-01-01\n"
            ",PRO-02,Скица национална (тест-дубъл),fixed,20,ACT-06,\n"
        )
        st, t1 = _req(op, "POST", "/admin/import/tariffs", csv=tariffs)
        _check("tariffs import -> created 1 (municipal)", t1["created"], 1)
        _check("national identical -> skipped 1", t1["skipped"], 1)

        # re-import the same file: everything skips
        st, t2 = _req(op, "POST", "/admin/import/tariffs", csv=tariffs)
        _check("re-import is a no-op", (t2["created"], t2["superseded"], t2["skipped"]), (0, 0, 2))

        # updated ordinance: new rate supersedes
        updated = tariffs.replace('"2,5"', '"3,0"')
        st, t3 = _req(op, "POST", "/admin/import/tariffs", csv=updated)
        _check("updated rate supersedes", t3["superseded"], 1)

        # recalc in the imported municipality uses the new rate: 3.0*500=1500 vs 750 -> +750
        _, p = _req(op, "POST", "/projects", {
            "name": "Import check", "project_type_id": "pv_ground", "tier": "pro",
            "municipality_id": test_mun["id"], "params": dict(seed.ETALON_PARAMS)})
        _, r = _req(op, "POST", f"/projects/{p['id']}/recalc")
        _check("recalc uses imported tariff (39870+750)", r["summary"]["total_fees"], 40620.0)

        # bad tariff file is all-or-nothing
        mixed = ("municipality,procedure_id,description,basis,rate\n"
                 "Тест-Импорт-2,PRO-04,Виза тест,fixed,150\n"
                 "Тест-Импорт-2,PRO-NOPE,счупен ред,fixed,1\n")
        st, body = _req(op, "POST", "/admin/import/tariffs", csv=mixed)
        _check("mixed file -> 422", st, 422)
        db = SessionLocal()
        try:
            wrote = db.scalar(select(func.count()).select_from(FeeTariff).where(
                FeeTariff.municipality_id == next(
                    m["id"] for m in muns if m["name"] == "Тест-Импорт-2")))
        finally:
            db.close()
        _check("nothing written from rejected file", wrote, 0)

        print("\nSMOKE OK - CSV import: dry-run, supersede, no-op re-import, all-or-nothing.")
    finally:
        _cleanup()
        _set_role(EMAIL, "user")


if __name__ == "__main__":
    main()

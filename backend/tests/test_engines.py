"""Etalon parity tests — the engines MUST reproduce the Excel model.

Reference PV project (5 MW, agricultural, medium voltage):
  critical path = 420 days, total fees = 39 870 BGN,
  IRR ~ 11.8%, NPV ~ 1.89M, LCOE ~ 121, payback ~ 7.7
Run: python -m pytest -q   (or: python backend/tests/test_engines.py)
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.data import seed
from backend.engines.rules import build_active_graph
from backend.engines.fees import compute_fees
from backend.engines.schedule import compute_schedule
from backend.engines.economics import evaluate, monte_carlo

P = seed.ETALON_PARAMS


def _graph():
    return build_active_graph(
        P, procedures=seed.PROCEDURES, dependencies=seed.DEPENDENCIES,
        rules=seed.RULES, project_types=seed.PROJECT_TYPES,
    )


def test_rules_activate_all_13():
    g = _graph()
    assert len(g["active"]) == 13, g["active"]


def test_rules_exclude_for_urban_land():
    p = dict(P, land_status="urban")
    g = build_active_graph(p, procedures=seed.PROCEDURES, dependencies=seed.DEPENDENCIES,
                           rules=seed.RULES, project_types=seed.PROJECT_TYPES)
    assert "PRO-05" not in g["active"]   # промяна на предназначение отпада


def test_critical_path_420():
    g = _graph()
    sched = compute_schedule(g)
    assert sched["total_days"] == 420, sched["total_days"]


def test_fees_total_39870():
    g = _graph()
    items, total = compute_fees(g["active"], P, fee_tariffs=seed.FEE_TARIFFS, acts=seed.ACTS)
    assert round(total) == 39870, total


def test_fees_carry_citations():
    g = _graph()
    items, _ = compute_fees(g["active"], P, fee_tariffs=seed.FEE_TARIFFS, acts=seed.ACTS)
    permit = next(i for i in items if i["procedure"] == "PRO-09")
    assert permit["citation"]["title"] == "ЗУТ"
    assert permit["citation"]["article"] == "чл.148"


def test_economics_match_excel():
    g = _graph()
    _, total = compute_fees(g["active"], P, fee_tariffs=seed.FEE_TARIFFS, acts=seed.ACTS)
    e = evaluate(P, total_fees=total)
    assert round(e["capex"]) == 6_539_870, e["capex"]
    assert abs(e["irr"] - 0.1178) < 0.0015, e["irr"]
    assert abs(e["npv"] - 1_892_538) < 5000, e["npv"]
    assert abs(e["lcoe"] - 121.4) < 1.0, e["lcoe"]
    assert abs(e["payback_years"] - 7.72) < 0.1, e["payback_years"]
    assert e["verdict"] == "relevant"


def test_zero_delay_matches_etalon_exactly():
    g = _graph()
    _, total = compute_fees(g["active"], P, fee_tariffs=seed.FEE_TARIFFS, acts=seed.ACTS)
    base = evaluate(P, total_fees=total)
    shifted = evaluate(P, total_fees=total, delay_days=0)
    assert shifted["irr"] == base["irr"]
    assert shifted["npv"] == base["npv"]
    assert shifted["lcoe"] == base["lcoe"]


def test_delay_lowers_irr_and_npv():
    g = _graph()
    _, total = compute_fees(g["active"], P, fee_tariffs=seed.FEE_TARIFFS, acts=seed.ACTS)
    base = evaluate(P, total_fees=total)
    delayed = evaluate(P, total_fees=total, delay_days=30)
    assert delayed["irr"] < base["irr"], (delayed["irr"], base["irr"])
    assert delayed["npv"] < base["npv"], (delayed["npv"], base["npv"])
    # a 30-day slip should dent IRR, not demolish it (sanity bound: < 1 п.п.)
    assert base["irr"] - delayed["irr"] < 0.01, base["irr"] - delayed["irr"]
    assert delayed["payback_years"] > base["payback_years"]


def test_monte_carlo_runs():
    g = _graph()
    _, total = compute_fees(g["active"], P, fee_tariffs=seed.FEE_TARIFFS, acts=seed.ACTS)
    mc = monte_carlo(P, total_fees=total, n=3000, seed=42)
    assert 0.0 <= mc["p_pass"] <= 1.0
    assert mc["irr_p5"] <= mc["irr_p50"] <= mc["irr_p95"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except AssertionError as ex:
            print(f"  FAIL  {fn.__name__}: {ex}")
        except Exception as ex:
            print(f"  ERROR {fn.__name__}: {ex!r}")
    print(f"\n{passed}/{len(fns)} tests passed")

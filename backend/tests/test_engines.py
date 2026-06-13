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


def test_protected_zone_adds_full_ovos():
    p = dict(P, protected_zone=True)
    g = build_active_graph(p, procedures=seed.PROCEDURES, dependencies=seed.DEPENDENCIES,
                           rules=seed.RULES, project_types=seed.PROJECT_TYPES)
    assert "PRO-14" in g["active"], g["active"]
    assert len(g["active"]) == 14
    # the full assessment gates the permit and extends the critical path
    sched = compute_schedule(g)
    assert sched["total_days"] > 420, sched["total_days"]
    # and its fee is now counted
    _, total = compute_fees(g["active"], p, fee_tariffs=seed.FEE_TARIFFS, acts=seed.ACTS)
    assert round(total) == 39870 + 1500, total


def test_compound_rule_requires_all_conditions():
    # protected zone but tiny plant: the power condition fails -> no full ОВОС
    p = dict(P, protected_zone=True, power_mw=0.5)
    g = build_active_graph(p, procedures=seed.PROCEDURES, dependencies=seed.DEPENDENCIES,
                           rules=seed.RULES, project_types=seed.PROJECT_TYPES)
    assert "PRO-14" not in g["active"], g["active"]


def test_critical_path_420():
    g = _graph()
    sched = compute_schedule(g)
    assert sched["total_days"] == 420, sched["total_days"]


def test_lag_and_start_start_links():
    g = _graph()
    base = compute_schedule(g)["total_days"]
    # a +30d lag on a critical-path finish_start edge pushes the deadline out
    fs_lag = compute_schedule(g, edge_meta={("PRO-11", "PRO-09"): {"link_type": "finish_start", "lag_days": 30}})
    assert fs_lag["total_days"] == base + 30, (fs_lag["total_days"], base)
    # start_start lets the successor begin with its predecessor (here +0),
    # overlapping work and finishing no later than the finish_start baseline
    ss = compute_schedule(g, edge_meta={("PRO-11", "PRO-09"): {"link_type": "start_start", "lag_days": 0}})
    assert ss["total_days"] <= base, (ss["total_days"], base)
    # empty edge_meta == the etalon
    assert compute_schedule(g, edge_meta={})["total_days"] == 420


def test_fees_total_39870():
    g = _graph()
    items, total = compute_fees(g["active"], P, fee_tariffs=seed.FEE_TARIFFS, acts=seed.ACTS)
    assert round(total) == 39870, total


def test_municipal_tariff_overrides_national():
    g = _graph()
    varna = {"id": "FEE-VAR", "procedure": "PRO-09", "desc": "Варна разрешение",
             "basis": "per_sqm_rzp", "rate": 2.0, "act": "ACT-04", "municipality": 1}
    tariffs = seed.FEE_TARIFFS + [varna]

    # National project: the Варна tariff is ignored, total stays the etalon.
    _, national = compute_fees(g["active"], P, fee_tariffs=tariffs, acts=seed.ACTS)
    assert round(national) == 39870, national

    # Project in municipality 1: PRO-09 uses the Варна rate (2.0), NOT both.
    items, total = compute_fees(g["active"], P, fee_tariffs=tariffs, acts=seed.ACTS, municipality_id=1)
    pro09 = [i for i in items if i["procedure"] == "PRO-09"]
    assert len(pro09) == 1, pro09                     # no double-count
    assert pro09[0]["fee_id"] == "FEE-VAR", pro09[0]
    assert round(total) == 39870 + 250, total          # +250 = (2.0-1.5)*500


def test_tiered_and_clamped_fees():
    from backend.engines.fees import _amount
    # progressive: first 1000 @ 1.0, remainder @ 0.5; base 3000 -> 1000 + 1000 = 2000
    tiered = {"tiers": [{"up_to": 1000, "rate": 1.0}, {"up_to": None, "rate": 0.5}]}
    assert _amount(tiered, 3000) == 2000.0
    assert _amount(tiered, 800) == 800.0           # within first bracket
    # min/max clamp on a flat rate
    assert _amount({"rate": 1.5, "min_fee": 1000}, 100) == 1000.0   # base×rate=150 -> floored
    assert _amount({"rate": 1.5, "max_fee": 500}, 1000) == 500.0    # 1500 -> capped
    assert _amount({"rate": 2.0}, 10) == 20.0                       # plain unchanged


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

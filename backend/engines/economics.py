"""EconEngine — financial model, verdict, and Monte Carlo risk.

Mirrors the Excel etalon formulas exactly so unit tests can verify parity:
IRR ~11.8%, NPV ~1.89M, LCOE ~121, payback ~7.7 for the reference PV project.
"""
from __future__ import annotations
import random


def _npv(rate, cashflows_from_year1, shift=0.0):
    """Excel NPV(): discounts the first value at period 1. A positive `shift`
    (in years) delays every flow — the schedule-delay link (SPEC 4.4)."""
    return sum(cf / (1 + rate) ** (i + 1 + shift) for i, cf in enumerate(cashflows_from_year1))


def _irr(cashflows, shift=0.0):
    """IRR over [year0, year1, ...] via bisection. `shift` delays the
    operating flows (index >= 1) while year 0 (CAPEX) stays at t=0.
    At shift=0 this is exactly the original integer-period IRR."""
    def f(r):
        return sum(
            cf / (1 + r) ** (i if i == 0 else i + shift)
            for i, cf in enumerate(cashflows)
        )
    lo, hi = -0.95, 2.0
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        return float("nan")
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = f(mid)
        if abs(fm) < 1e-6:
            return mid
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


def annual_model(params, capex):
    """Return per-year lists: production(MWh), revenue, opex, depreciation, tax, fcf."""
    mw = params["power_mw"]
    yld = params["yield_kwh_kwp"]
    ppa = params["ppa_price"]
    opex = mw * 1000 * params["opex_per_kw"]
    years = params["years"]
    deg = params["degradation"]
    tax_rate = params["tax_rate"]
    depr = capex / years

    prod, rev, fcf = [], [], []
    for t in range(1, years + 1):
        p = mw * yld * (1 - deg) ** (t - 1)        # MWh (mw*yield == MWh; ×1000/÷1000 cancel)
        r = p * ppa
        taxable = r - opex - depr
        tax = max(0.0, taxable * tax_rate)
        prod.append(p)
        rev.append(r)
        fcf.append(r - opex - tax)
    return {"production": prod, "revenue": rev, "opex": opex, "depr": depr, "fcf": fcf}


def evaluate(params, *, total_fees, p5_irr=None, delay_days=0):
    """Full economic evaluation. total_fees comes from FeeEngine.

    delay_days (SPEC 4.4): deviation of the actual schedule from the statutory
    one. The etalon Excel prices the statutory schedule into its baseline, so
    only the DEVIATION shifts the operating cashflows — delay_days=0 reproduces
    the etalon exactly; a slip pushes every flow later and IRR/NPV honestly drop.
    """
    kw = params["power_mw"] * 1000
    capex = kw * params["specific_capex_per_kw"] + total_fees
    m = annual_model(params, capex)
    wacc = params["wacc"]
    hurdle = params["hurdle_rate"]
    # Clamp so year-1 flows can never be discounted to before t=0.
    shift = max(-1.0, delay_days / 365.0)

    npv = -capex + _npv(wacc, m["fcf"], shift)
    irr = _irr([-capex] + m["fcf"], shift)
    lcoe = (capex + _npv(wacc, [m["opex"]] * params["years"], shift)) / _npv(wacc, m["production"], shift)
    payback = capex / (sum(m["fcf"]) / len(m["fcf"])) + shift

    if p5_irr is not None and p5_irr >= hurdle:
        verdict = "resilient"
    elif irr >= hurdle:
        verdict = "relevant"
    else:
        verdict = "risky"

    # Yearly cash position: year 0 is the upfront CAPEX, then free cash flow
    # accumulates. The cumulative line crosses zero at the payback point.
    cashflow = [{"year": 0, "fcf": -capex, "cumulative": -capex}]
    cum = -capex
    for t, f in enumerate(m["fcf"], start=1):
        cum += f
        cashflow.append({"year": t, "fcf": f, "cumulative": cum})

    return {
        "capex": capex,
        "irr": irr,
        "npv": npv,
        "lcoe": lcoe,
        "payback_years": payback,
        "verdict": verdict,
        "delay_days": delay_days,
        "cashflow": cashflow,
    }


def monte_carlo(params, *, total_fees, n=5000, sigmas=None, seed=None):
    """Probabilistic risk: returns P(IRR>=hurdle), percentiles, P(NPV>0)."""
    rng = random.Random(seed)
    sg = sigmas or {"ppa_price": 25, "yield_kwh_kwp": 120,
                    "specific_capex_per_kw": 150, "delay_months": 4}
    hurdle = params["hurdle_rate"]
    irrs, npvs, npos, npass = [], [], 0, 0

    for _ in range(n):
        p = dict(params)
        p["ppa_price"] = max(0, params["ppa_price"] + rng.gauss(0, sg["ppa_price"]))
        p["yield_kwh_kwp"] = max(0, params["yield_kwh_kwp"] + rng.gauss(0, sg["yield_kwh_kwp"]))
        scap = max(0, params["specific_capex_per_kw"] + rng.gauss(0, sg["specific_capex_per_kw"]))
        kw = p["power_mw"] * 1000
        capex = kw * scap + total_fees
        mm = annual_model(p, capex)
        irr = _irr([-capex] + mm["fcf"])
        npv = -capex + _npv(p["wacc"], mm["fcf"])
        irrs.append(irr)
        npvs.append(npv)
        if npv > 0:
            npos += 1
        if irr == irr and irr >= hurdle:  # not NaN
            npass += 1

    valid = sorted(x for x in irrs if x == x)

    def pct(s, q):
        if not s:
            return float("nan")
        i = (len(s) - 1) * q
        lo, hi = int(i), min(int(i) + 1, len(s) - 1)
        return s[lo] + (s[hi] - s[lo]) * (i - lo)

    return {
        "n": n,
        "p_pass": npass / n,
        "irr_p50": pct(valid, 0.5),
        "irr_p5": pct(valid, 0.05),
        "irr_p95": pct(valid, 0.95),
        "p_npv_positive": npos / n,
    }

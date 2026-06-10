"""FeeEngine — parametric fee computation linked to normative acts.

fee = basis_value(params) x rate. Each result carries the citing act (snapshot),
so the report is reproducible even after the tariff changes later.
"""
from __future__ import annotations


def _basis_value(basis: str, params: dict) -> float:
    if basis == "fixed":
        return 1.0
    if basis == "per_sqm_rzp":
        return float(params.get("rzp_sqm", 0))
    if basis == "pct_of_value":
        return float(params.get("invest_value", 0))
    if basis == "per_mw":
        return float(params.get("power_mw", 0))
    raise ValueError(f"unknown basis {basis!r}")


def compute_fees(active_ids, params, *, fee_tariffs, acts):
    """Return (line_items, total). Only fees for active procedures are counted."""
    acts_by_id = {a["id"]: a for a in acts}
    active = set(active_ids)
    items = []
    total = 0.0
    for t in fee_tariffs:
        if t["procedure"] not in active:
            continue
        base = _basis_value(t["basis"], params)
        amount = base * t["rate"]
        act = acts_by_id.get(t["act"])
        citation = None
        if act:
            citation = {
                "act_id": act["id"],
                "title": act["title"],
                "article": act["article"],
                "valid_from": act["valid_from"],
            }
        items.append({
            "fee_id": t["id"],
            "procedure": t["procedure"],
            "description": t["desc"],
            "basis": t["basis"],
            "basis_value": base,
            "rate": t["rate"],
            "amount": amount,
            "citation": citation,
        })
        total += amount
    return items, total

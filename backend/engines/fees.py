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


def _resolve(tariffs, municipality_id):
    """Per procedure, a municipality-specific tariff overrides the national one
    (SPEC 4.2): if the project's municipality has its own tariff(s) for this
    procedure use only those, otherwise fall back to the national (NULL) ones.
    The two are never summed together."""
    if municipality_id is not None:
        local = [t for t in tariffs if t.get("municipality") == municipality_id]
        if local:
            return local
    return [t for t in tariffs if t.get("municipality") is None]


def compute_fees(active_ids, params, *, fee_tariffs, acts, municipality_id=None):
    """Return (line_items, total) for the active procedures, resolving each
    procedure's tariff against the project's municipality."""
    acts_by_id = {a["id"]: a for a in acts}
    active = set(active_ids)

    by_proc: dict = {}
    for t in fee_tariffs:
        if t["procedure"] in active:
            by_proc.setdefault(t["procedure"], []).append(t)

    items = []
    total = 0.0
    for proc in sorted(by_proc):
        for t in _resolve(by_proc[proc], municipality_id):
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

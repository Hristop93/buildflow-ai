"""RuleEngine — assembles the active procedure set for a project.

Pure logic, no LLM. Given project params, applies the rules to include/exclude
procedures and switch institutions. Never invents procedures outside the base set.
"""
from __future__ import annotations


def _cmp(op: str, left, right) -> bool:
    if op == "=":
        return left == right
    if op == "!=":
        return left != right
    if op == ">=":
        return left >= right
    if op == "<=":
        return left <= right
    if op == "<":
        return left < right
    if op == ">":
        return left > right
    if op == "in":
        return left in right
    raise ValueError(f"unknown operator {op!r}")


def _matches(rule: dict, params: dict) -> bool:
    """A rule fires when its condition(s) hold. Compound form: `conditions` is
    a list of {param, op, value} that must ALL hold (AND); express OR as two
    rules. Legacy form: the single param/op/value triple."""
    conds = rule.get("conditions")
    if conds:
        for c in conds:
            pval = params.get(c["param"])
            if pval is None or not _cmp(c["op"], pval, c["value"]):
                return False
        return True
    pval = params.get(rule["param"])
    return pval is not None and _cmp(rule["op"], pval, rule["value"])


def build_active_graph(params: dict, *, procedures, dependencies, rules, project_types):
    """Return dict with active procedure ids, their institutions, and active edges.

    params: project parameters (must include 'project_type').
    """
    ptype = params["project_type"]
    base = set(project_types[ptype]["procedures"])

    proc_by_id = {p["id"]: dict(p) for p in procedures}
    active = {pid for pid in base}
    institution = {pid: proc_by_id[pid]["institution"] for pid in base}

    for rule in rules:
        if not _matches(rule, params):
            continue
        target = rule["target"]
        action = rule["action"]
        if action == "exclude":
            active.discard(target)
        elif action == "include":
            if target in proc_by_id:
                active.add(target)
                institution.setdefault(target, proc_by_id[target]["institution"])
        elif action == "switch_institution":
            institution[target] = rule["target_institution"]

    # keep only edges between active nodes
    active_edges = {
        succ: [p for p in preds if p in active]
        for succ, preds in dependencies.items()
        if succ in active
    }

    return {
        "active": active,
        "institution": institution,
        "edges": active_edges,
        "procedures": {pid: proc_by_id[pid] for pid in active},
    }

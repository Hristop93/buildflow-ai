"""ScheduleEngine — critical path (CPM) over the procedure graph.

Forward pass: start = max(end of predecessors); end = start + duration.
Duration precedence: actual (if known) -> planned -> statutory.
Marks the critical path and returns the total project duration in days.
"""
from __future__ import annotations


def _topo_order(active, edges):
    indeg = {n: 0 for n in active}
    for succ, preds in edges.items():
        for _ in preds:
            indeg[succ] += 1
    queue = [n for n in active if indeg[n] == 0]
    order = []
    while queue:
        n = queue.pop()
        order.append(n)
        for succ, preds in edges.items():
            if n in preds:
                indeg[succ] -= 1
                if indeg[succ] == 0:
                    queue.append(succ)
    if len(order) != len(active):
        raise ValueError("cycle detected in dependency graph")
    return order


def compute_schedule(graph, *, durations=None, edge_meta=None):
    """graph: output of build_active_graph. durations: optional override per node.
    edge_meta: {(successor, predecessor): {"link_type", "lag_days"}} — defaults to
    finish_start with 0 lag, so a plain graph reproduces the original schedule.

    Returns dict: nodes {id: {start, end, duration, critical}}, total_days.
    """
    active = graph["active"]
    edges = graph["edges"]
    procs = graph["procedures"]
    durations = durations or {}
    edge_meta = edge_meta or {}

    def dur(pid):
        if pid in durations and durations[pid] is not None:
            return durations[pid]
        return procs[pid]["duration_days"]

    def link_lag(succ, pred):
        m = edge_meta.get((succ, pred))
        if not m:
            return "finish_start", 0
        return m.get("link_type") or "finish_start", m.get("lag_days") or 0

    order = _topo_order(active, edges)
    start, end = {}, {}
    for n in order:
        s = 0
        for p in edges.get(n, []):
            link, lag = link_lag(n, p)
            anchor = start[p] if link == "start_start" else end[p]
            s = max(s, anchor + lag)
        start[n] = max(0, s)
        end[n] = start[n] + dur(n)

    total = max(end.values()) if end else 0

    # backward pass: each successor edge bounds how late this node may finish,
    # accounting for link type and lag. finish_start/0 reduces to min(start[s]).
    late_finish = {}
    for n in reversed(order):
        bounds = []
        for s, preds in edges.items():
            if n not in preds:
                continue
            link, lag = link_lag(s, n)
            if link == "start_start":
                bounds.append(start[s] - lag + dur(n))
            else:
                bounds.append(start[s] - lag)
        late_finish[n] = min(bounds) if bounds else total

    nodes = {}
    for n in active:
        slack = late_finish[n] - end[n]
        nodes[n] = {
            "start": start[n],
            "end": end[n],
            "duration": dur(n),
            "critical": slack == 0,
        }
    return {"nodes": nodes, "total_days": total}

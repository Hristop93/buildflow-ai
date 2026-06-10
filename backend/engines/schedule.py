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


def compute_schedule(graph, *, durations=None):
    """graph: output of build_active_graph. durations: optional override per node.

    Returns dict: nodes {id: {start, end, duration, critical}}, total_days.
    """
    active = graph["active"]
    edges = graph["edges"]
    procs = graph["procedures"]
    durations = durations or {}

    def dur(pid):
        if pid in durations and durations[pid] is not None:
            return durations[pid]
        return procs[pid]["duration_days"]

    order = _topo_order(active, edges)
    start, end = {}, {}
    for n in order:
        preds = edges.get(n, [])
        s = max((end[p] for p in preds), default=0)
        start[n] = s
        end[n] = s + dur(n)

    total = max(end.values()) if end else 0

    # backward pass to mark critical path (zero slack)
    late_finish = {n: total for n in active}
    for n in reversed(order):
        succs = [s for s, preds in edges.items() if n in preds]
        if succs:
            late_finish[n] = min(start[s] for s in succs)
        else:
            late_finish[n] = total

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

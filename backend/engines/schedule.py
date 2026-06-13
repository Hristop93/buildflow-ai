"""ScheduleEngine — critical path (CPM) over the procedure graph.

Forward pass: start = max(end of predecessors); end = start + duration.
Duration precedence: actual (if known) -> planned -> statutory.
Marks the critical path and returns the total project duration in days.

When a project start_date is given, offsets are mapped to real calendar dates
and a procedure with term_basis='working' has its term counted in working days
(weekends + BG holidays skipped), so its calendar span grows accordingly. With
no start_date — or all-calendar procedures — the offsets are exactly as before.
"""
from __future__ import annotations

from datetime import date, timedelta

from backend.engines.calendar_bg import holidays_in_range, add_working_days


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


def compute_schedule(graph, *, durations=None, edge_meta=None, start_date=None):
    """graph: output of build_active_graph. durations: optional override per node.
    edge_meta: {(successor, predecessor): {"link_type", "lag_days"}} — defaults to
    finish_start with 0 lag. start_date (a date): when given, nodes carry real
    start_date/end_date and term_basis='working' terms span the BG calendar.

    Returns dict: nodes {id: {start, end, duration, critical[, start_date, end_date]}},
    total_days.
    """
    active = graph["active"]
    edges = graph["edges"]
    procs = graph["procedures"]
    durations = durations or {}
    edge_meta = edge_meta or {}

    holidays = set()
    if start_date is not None:
        holidays = holidays_in_range(start_date.year, start_date.year + 4)

    def term(pid):
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
    dates = {}  # pid -> (start_date, end_date)
    for n in order:
        s = 0
        for p in edges.get(n, []):
            link, lag = link_lag(n, p)
            anchor = start[p] if link == "start_start" else end[p]
            s = max(s, anchor + lag)
        start[n] = max(0, s)
        N = term(n)
        # Working-day terms span a wider calendar window; needs the start date.
        if start_date is not None and procs[n].get("term_basis") == "working":
            sd = start_date + timedelta(days=start[n])
            ed = add_working_days(sd, N, holidays)
            span = (ed - sd).days
        else:
            span = N
        end[n] = start[n] + span
        if start_date is not None:
            sd = start_date + timedelta(days=start[n])
            dates[n] = (sd, start_date + timedelta(days=end[n]))

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
                bounds.append(start[s] - lag + (end[n] - start[n]))
            else:
                bounds.append(start[s] - lag)
        late_finish[n] = min(bounds) if bounds else total

    nodes = {}
    for n in active:
        slack = late_finish[n] - end[n]
        node = {
            "start": start[n],
            "end": end[n],
            "duration": end[n] - start[n],
            "critical": slack == 0,
        }
        if n in dates:
            node["start_date"] = dates[n][0].isoformat()
            node["end_date"] = dates[n][1].isoformat()
        nodes[n] = node
    return {"nodes": nodes, "total_days": total}

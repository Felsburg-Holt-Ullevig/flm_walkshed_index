"""Pure experimental reachability in international feet and seconds; no file I/O."""
from __future__ import annotations

from dataclasses import dataclass, field
import heapq
import math


def number(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError("Expected a finite nonnegative number (positive where required)")
    return value


@dataclass(frozen=True)
class Segment:
    id: str
    start: str
    end: str
    length_ft: float
    direction: str = "both"

    def __post_init__(self):
        if any(not isinstance(x, str) or not x for x in (self.id, self.start, self.end)):
            raise ValueError("Segment and node identities must be nonempty strings")
        number(self.length_ft, positive=True)
        if self.start == self.end or self.direction not in {"both", "forward", "reverse"}:
            raise ValueError("Invalid segment topology or direction")


@dataclass(frozen=True)
class Origin:
    node: str | None = None
    segment: str | None = None
    offset_ft: float = 0
    access_distance_ft: float = 0


@dataclass(frozen=True)
class Readiness:
    policy_blockers: tuple[str, ...] = ()
    coverage: str = "not_established"
    frontier_nodes: tuple[str, ...] = ()
    in_domain: bool = True


@dataclass
class Result:
    computation_status: str
    origin_status: str
    policy_readiness: str
    coverage_readiness: str
    node_seconds: dict[str, float] | None = None
    intervals_ft: dict[str, list[tuple[float, float]]] | None = None
    unique_source_length_ft: float | None = None
    connector_length_ft: float = 0
    connector_seconds: float = 0
    network_origin_reached: bool = False
    frontier: dict[str, float] = field(default_factory=dict)
    blockers: tuple[str, ...] = ()
    error: str | None = None


def union_intervals(intervals):
    """Union by source segment identity. Never merge across a positive gap."""
    output = []
    for low, high in sorted(intervals):
        number(low)
        number(high)
        if high < low:
            raise ValueError("Reversed interval")
        if high == low:
            continue
        if output and low <= output[-1][1]:
            output[-1] = (output[-1][0], max(output[-1][1], high))
        else:
            output.append((low, high))
    return output


def combined_intervals(results):
    combined = {}
    for result in results:
        if result.intervals_ft is None:
            raise ValueError("Cannot aggregate an unexecuted result")
        for identity, intervals in result.intervals_ft.items():
            combined.setdefault(identity, []).extend(intervals)
    return {identity: union_intervals(values) for identity, values in sorted(combined.items())}


def traverse(segments, origin, budget_seconds, seconds_per_foot, readiness=Readiness()):
    """Bounded Dijkstra plus directed partial intervals; invalid inputs return failed."""
    result = Result("not_run", "not_checked", "blocked" if readiness.policy_blockers else "ready",
                    readiness.coverage, blockers=readiness.policy_blockers)
    try:
        number(budget_seconds)
        number(seconds_per_foot, positive=True)
        if readiness.coverage not in {"not_established", "synthetic_closed", "established"} or type(readiness.in_domain) is not bool:
            raise ValueError("Invalid coverage declaration")
        rows = list(segments)
        by_id = {s.id: s for s in rows}
        if len(by_id) != len(rows):
            raise ValueError("Duplicate segment identity")
        if (origin.node is None) == (origin.segment is None):
            raise ValueError("Choose exactly one origin mode")
        number(origin.offset_ft)
        number(origin.access_distance_ft)
        if origin.node is not None and (not isinstance(origin.node, str) or not origin.node or origin.offset_ft or origin.access_distance_ft):
            raise ValueError("Source node origins have no connector or offset")
        if not readiness.in_domain:
            result.computation_status = result.origin_status = "out_of_coverage"
            return result
        nodes = {n for s in rows for n in (s.start, s.end)}
        if not rows or (origin.node is not None and origin.node not in nodes):
            result.computation_status = result.origin_status = "no_network"
            return result
        selected = None
        if origin.segment is not None:
            if origin.segment not in by_id:
                raise ValueError("Origin segment is absent or ineligible")
            selected = by_id[origin.segment]
            if origin.offset_ft > selected.length_ft:
                raise ValueError("Origin offset exceeds segment")
        result.origin_status = "resolved"
        result.connector_length_ft = origin.access_distance_ft
        result.connector_seconds = origin.access_distance_ft * seconds_per_foot
        number(result.connector_seconds)
        result.node_seconds, result.intervals_ft = {}, {}
        result.unique_source_length_ft = 0
        if result.connector_seconds > budget_seconds:
            result.computation_status = "budget_exhausted_before_network"
            return result
        result.network_origin_reached = True
        queue = []
        distances = result.node_seconds
        def seed(node, cost):
            if cost <= budget_seconds and cost < distances.get(node, math.inf):
                distances[node] = cost
                heapq.heappush(queue, (cost, node))
        raw = {}
        def interval(s, low, high):
            if high > low:
                raw.setdefault(s.id, []).append((max(0, low), min(s.length_ft, high)))
        if selected is None:
            seed(origin.node, 0)
        else:
            s, off, access = selected, origin.offset_ft, result.connector_seconds
            residual = (budget_seconds - access) / seconds_per_foot
            # Endpoint projection is the actual source node, with all its incident arcs.
            if off == 0:
                seed(s.start, access)
            if off == s.length_ft:
                seed(s.end, access)
            if s.direction in {"both", "forward"}:
                interval(s, off, off + min(s.length_ft - off, residual))
                seed(s.end, access + (s.length_ft - off) * seconds_per_foot)
            if s.direction in {"both", "reverse"}:
                interval(s, off - min(off, residual), off)
                seed(s.start, access + off * seconds_per_foot)
        adjacency = {}
        for s in rows:
            if s.direction in {"both", "forward"}:
                adjacency.setdefault(s.start, []).append((s.end, s))
            if s.direction in {"both", "reverse"}:
                adjacency.setdefault(s.end, []).append((s.start, s))
        while queue:
            cost, node = heapq.heappop(queue)
            if cost != distances[node]:
                continue
            for target, s in sorted(adjacency.get(node, []), key=lambda item: (item[0], item[1].id)):
                seed(target, cost + s.length_ft * seconds_per_foot)
        for s in rows:
            if s.direction in {"both", "forward"} and s.start in distances:
                interval(s, 0, min(s.length_ft, (budget_seconds - distances[s.start]) / seconds_per_foot))
            if s.direction in {"both", "reverse"} and s.end in distances:
                interval(s, s.length_ft - min(s.length_ft, (budget_seconds - distances[s.end]) / seconds_per_foot), s.length_ft)
        result.node_seconds = dict(sorted(distances.items()))
        result.intervals_ft = {key: union_intervals(values) for key, values in sorted(raw.items())}
        result.unique_source_length_ft = math.fsum(hi - lo for values in result.intervals_ft.values() for lo, hi in values)
        result.frontier = {node: budget_seconds - distances[node] for node in sorted(set(readiness.frontier_nodes) & distances.keys())}
        if any(value > 0 for value in result.frontier.values()):
            result.coverage_readiness = "incomplete_coverage"
        if readiness.policy_blockers:
            result.computation_status = "incomplete"
        elif result.coverage_readiness == "incomplete_coverage":
            result.computation_status = "incomplete_coverage"
        elif readiness.coverage == "not_established":
            result.computation_status = "incomplete"
        else:
            result.computation_status = "synthetic_complete" if readiness.coverage == "synthetic_closed" else "experimental_complete"
        return result
    except (ValueError, TypeError, AttributeError, OverflowError) as error:
        result.computation_status = "failed"
        result.node_seconds = result.intervals_ft = result.unique_source_length_ft = None
        result.error = str(error)
        return result

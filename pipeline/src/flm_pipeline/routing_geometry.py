"""Explicit planar-foot and WGS84 adapters for experimental origin projection."""
from dataclasses import dataclass
import heapq
import math

from pyproj import Geod

from .routing import Origin, number

GEOD = Geod(ellps="WGS84")


def coordinate(point, geographic):
    if len(point) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in point):
        raise ValueError("Invalid coordinate")
    if geographic and not (-180 <= point[0] <= 180 and -90 <= point[1] <= 90):
        raise ValueError("Coordinate outside WGS84")
    return tuple(point)


@dataclass(frozen=True)
class Projection:
    candidate_id: str
    offset_ft: float
    distance_ft: float
    point: tuple[float, float]
    endpoint_node: str | None


@dataclass
class Snap:
    status: str
    origin: Origin | None
    projections: tuple[Projection, ...]
    selected: Projection | None = None
    warning: str = "geometric_experiment_not_verified_walkable_access"


def interpolate(start, end, offset_ft, *, geographic=False):
    start, end = coordinate(start, geographic), coordinate(end, geographic)
    number(offset_ft)
    if geographic:
        azimuth, _, meters = GEOD.inv(*start, *end)
        length = meters / 0.3048
        if offset_ft > length:
            raise ValueError("Offset exceeds geodesic segment")
        if offset_ft == 0:
            return start
        if offset_ft == length:
            return end
        lon, lat, _ = GEOD.fwd(*start, azimuth, offset_ft * 0.3048)
        return lon, lat
    length = math.dist(start, end)
    if not length or offset_ft > length:
        raise ValueError("Invalid planar segment or offset")
    return tuple(a + (b - a) * offset_ft / length for a, b in zip(start, end))


def project(candidate_id, start_node, end_node, start, end, point, *, geographic=False):
    start, end, point = (coordinate(p, geographic) for p in (start, end, point))
    if not geographic:
        length = math.dist(start, end)
        number(length, positive=True)
        offset = max(0, min(length, sum((p - a) * (b - a) for p, a, b in zip(point, start, end)) / length))
        projected = interpolate(start, end, offset)
        distance = math.dist(point, projected)
    else:
        azimuth, _, meters = GEOD.inv(*start, *end)
        length = meters / 0.3048
        number(length, positive=True)
        def evaluate(offset):
            if offset == 0:
                xy = start
            elif offset == length:
                xy = end
            else:
                lon, lat, _ = GEOD.fwd(*start, azimuth, offset * 0.3048)
                xy = (lon, lat)
            return GEOD.inv(*point, *xy)[2] / 0.3048, xy
        # Global interval search uses the geodesic triangle inequality, not a
        # projected cutoff or an assumption that the distance is unimodal.
        left, right = evaluate(0)[0], evaluate(length)[0]
        distance, offset = min((left, 0), (right, length))
        queue = []
        def push(a, b, da, db):
            lower = max(0, (da + db - (b - a)) / 2)
            heapq.heappush(queue, (lower, a, b, da, db))
        push(0, length, left, right)
        iterations = 0
        while queue:
            lower, a, b, da, db = heapq.heappop(queue)
            if lower > distance:
                continue
            mid = (a + b) / 2
            dm, _ = evaluate(mid)
            if dm < distance:
                distance, offset = dm, mid
            if b - a <= 0.001:
                continue
            push(a, mid, da, dm)
            push(mid, b, dm, db)
            iterations += 1
            if iterations > 500000:
                raise ValueError("Geodesic projection resource limit; no snap produced")
        distance, projected = evaluate(offset)
    endpoint = start_node if offset == 0 else end_node if offset == length else None
    return Projection(candidate_id, offset, distance, projected, endpoint)


def snap_origin(segments, coordinates, point, *, geographic=False, selected_id=None,
                maximum_ft=100, tie_ft=0.01, in_domain=True):
    """Input segments must already be included-only; scan every eligible segment.

    Explicit selection must be one of the nearest competing identities. Endpoint
    coalescing uses source node identity, never coordinate equality.
    """
    number(maximum_ft)
    number(tie_ft)
    coordinate(point, geographic)
    rows = list(segments)
    if len({s.id for s in rows}) != len(rows):
        raise ValueError("Duplicate candidate identity")
    if not in_domain:
        return Snap("out_of_coverage", None, ())
    if not rows:
        return Snap("no_network", None, ())
    for s in rows:
        a, b = coordinate(coordinates[s.start], geographic), coordinate(coordinates[s.end], geographic)
        geometric_length = GEOD.inv(*a, *b)[2] / 0.3048 if geographic else math.dist(a, b)
        if not math.isclose(s.length_ft, geometric_length, rel_tol=1e-12, abs_tol=1e-9):
            raise ValueError("Snap geometry and source segment length differ")
    projections = sorted((project(s.id, s.start, s.end, coordinates[s.start], coordinates[s.end], point,
                                  geographic=geographic) for s in rows), key=lambda p: (p.distance_ft, p.candidate_id))
    eligible = [p for p in projections if p.distance_ft <= maximum_ft]
    if not eligible:
        return Snap("off_network", None, ())
    nearest = eligible[0].distance_ft
    # Account only for subtraction roundoff at the declared tie threshold;
    # this does not extend the maximum snap distance or the travel budget.
    competing = tuple(sorted((p for p in eligible if p.distance_ft - nearest <= tie_ft
                             + 4 * max(math.ulp(p.distance_ft), math.ulp(nearest))), key=lambda p: p.candidate_id))
    groups = {("node", p.endpoint_node) if p.endpoint_node is not None else ("segment", p.candidate_id) for p in competing}
    if selected_id is not None:
        chosen = next((p for p in competing if p.candidate_id == selected_id), None)
        if chosen is None:
            raise ValueError("Explicit origin selection is not a nearest allowed candidate")
    elif len(groups) != 1:
        return Snap("ambiguous_origin", None, competing)
    else:
        chosen = min(competing, key=lambda p: (p.distance_ft, p.candidate_id))
    return Snap("resolved", Origin(segment=chosen.candidate_id, offset_ft=chosen.offset_ft,
                                   access_distance_ft=chosen.distance_ft), competing, chosen)

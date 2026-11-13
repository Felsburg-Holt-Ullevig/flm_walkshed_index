"""Step 3 experimental snapping and foot-budget traversal for walk tiles."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Sequence

from pyproj import Geod

from .routing import Origin, Readiness, Segment, traverse

# Scaling the WGS84 ellipsoid keeps every geodesic input and output in
# international feet. This is the same ellipsoid, with its axis in feet.
GEOD = Geod(a=20925646.325459316, rf=298.257223563)
MAX_SOLVE_EVALUATIONS = 10_000
UNCERTAINTY_FT = 1e-6
DISTANCE_GUARD_FT = 1e-7
CONVEXITY_RADIUS_CAP_FT = 1_000_000


class NumericalFailure(RuntimeError):
    """The requested distance or tie could not be resolved within the cap."""


@dataclass(frozen=True)
class Projection:
    candidate_id: str
    fraction: float
    offset_ft: float
    distance_ft: float
    distance_lower_ft: float
    distance_upper_ft: float
    point: tuple[float, float]
    endpoint_node: str | None
    offset_bounds_ft: tuple[float, float] | None = None


@dataclass(frozen=True)
class SnapResult:
    status: str
    selected: Projection | None
    candidates: tuple[Projection, ...]
    maximum_ft: float = 500

    def as_dict(self) -> dict:
        def projection(p):
            if p is None:
                return None
            return {
                "candidate_id": p.candidate_id, "point": list(p.point),
                "endpoint_node": p.endpoint_node, "fraction": p.fraction,
                "offset_ft": p.offset_ft, "distance_ft": p.distance_ft,
                "offset_bounds_ft": list(p.offset_bounds_ft) if p.offset_bounds_ft is not None else None,
                "distance_bounds_ft": [p.distance_lower_ft, p.distance_upper_ft],
            }
        return {"status": self.status, "maximum_ft": self.maximum_ft,
                "selected": projection(self.selected),
                "candidates": [projection(p) for p in self.candidates]}


def interpolate_fraction(start: Sequence[float], end: Sequence[float], fraction: float) -> tuple[float, float]:
    """Return the geodesic point at source-oriented fraction in [0, 1]."""
    _validate_point(start)
    _validate_point(end)
    if not math.isfinite(fraction) or not 0 <= fraction <= 1:
        raise ValueError("fraction must be finite and in [0, 1]")
    if fraction == 0:
        return float(start[0]), float(start[1])
    if fraction == 1:
        return float(end[0]), float(end[1])
    azimuth, _, length = GEOD.inv(*start, *end)
    lon, lat, _ = GEOD.fwd(*start, azimuth, length * fraction)
    return lon, lat


def offset_from_fraction(fraction: float, copied_length_ft: float) -> float:
    """Map geodesic fraction onto the preserved source length."""
    if not math.isfinite(fraction) or not 0 <= fraction <= 1:
        raise ValueError("fraction must be finite and in [0, 1]")
    if not math.isfinite(copied_length_ft) or copied_length_ft <= 0:
        raise ValueError("copied length must be positive and finite")
    return fraction * copied_length_ft


def within_snap_limit(distance_lower_ft: float, distance_upper_ft: float, maximum_ft: float = 500) -> bool:
    """Apply the inclusive limit without an epsilon; fail unresolved bounds."""
    if any(not math.isfinite(v) or v < 0 for v in (distance_lower_ft, distance_upper_ft, maximum_ft)):
        raise ValueError("snap distances and limit must be finite and nonnegative")
    if distance_upper_ft < distance_lower_ft:
        raise ValueError("reversed snap distance bounds")
    if distance_lower_ft == distance_upper_ft:
        return distance_lower_ft <= maximum_ft
    if distance_lower_ft <= maximum_ft < distance_upper_ft:
        raise NumericalFailure("snap eligibility overlaps the maximum distance")
    return distance_upper_ft <= maximum_ft


def _validate_point(p):
    if len(p) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in p):
        raise ValueError("coordinates must be finite longitude/latitude pairs")
    if not -180 <= p[0] <= 180 or not -90 <= p[1] <= 90:
        raise ValueError("coordinate outside WGS84")


def _distance(point, candidate):
    return abs(GEOD.inv(point[0], point[1], candidate[0], candidate[1])[2])


def _project(segment: Segment, coords: Mapping[str, Sequence[float]], point: Sequence[float], *, max_evaluations: int,
             endpoint_distances=None, geom_length=None) -> Projection:
    a, b = coords[segment.start], coords[segment.end]
    _validate_point(a); _validate_point(b)
    azimuth, _, measured_length = GEOD.inv(*a, *b)
    if geom_length is None:
        geom_length = measured_length
    if not math.isfinite(geom_length) or geom_length <= 0:
        raise ValueError(f"invalid geodesic for {segment.id}")
    da, db = endpoint_distances if endpoint_distances is not None else (_distance(point, a), _distance(point, b))
    radius_bound = max(da, db) + geom_length
    # On WGS84, K <= 1/b² and the maximum principal curvature is a/b².
    # Fenchel bounds each closed geodesic's length below by 2πb²/a;
    # Klingenberg then bounds injectivity radius, and the standard convexity
    # radius estimate gives πb²/(2a) ≈ 32.6 million ft. A ball of radius
    # max(endpoint distance)+segment length contains this query and arc, so
    # the 1,000,000-ft runtime cap stays inside that convex region. Distance
    # along the candidate geodesic is therefore convex; its monotone first
    # derivative brackets the global minimum without a local-minimum guess.
    # Longer/nonlocal cases fail; the full tile scan retains safe endpoint
    # triangle bounds. The published WGS84 accuracy is approximately
    # 0.00000005 foot; DISTANCE_GUARD_FT accounts for direct/inverse roundoff.
    # These are engineering error bounds, not interval-arithmetic guarantees.
    if radius_bound >= CONVEXITY_RADIUS_CAP_FT:
        raise NumericalFailure(f"candidate outside verified local convexity domain: {segment.id}")

    evaluations = 0
    def evaluate_s(s):
        nonlocal evaluations
        evaluations += 1
        if evaluations > max_evaluations:
            raise NumericalFailure(f"geodesic projection work cap reached for {segment.id}")
        if s <= 0:
            q = (float(a[0]), float(a[1]))
            tangent = azimuth
        elif s >= geom_length:
            q = (float(b[0]), float(b[1]))
            _, back, _ = GEOD.inv(*a, *b)
            tangent = (back + 180) % 360
        else:
            lon, lat, back = GEOD.fwd(*a, azimuth, s)
            q = (lon, lat)
            tangent = (back + 180) % 360
        d = _distance(point, q)
        if d == 0:
            return d, 0.0, q
        toward, _, _ = GEOD.inv(lon if 0 < s < geom_length else q[0],
                                lat if 0 < s < geom_length else q[1], *point)
        derivative = -math.cos(math.radians(toward - tangent))
        return d, derivative, q

    # A source endpoint exactly equal to the origin proves distance zero by
    # nonnegativity; avoid the undefined derivative at that point.
    if tuple(a) == tuple(point):
        return Projection(segment.id, 0.0, 0.0, 0.0, 0.0, DISTANCE_GUARD_FT, tuple(a), segment.start, (0.0, 0.0))
    if tuple(b) == tuple(point):
        return Projection(segment.id, 1.0, segment.length_ft, 0.0, 0.0, DISTANCE_GUARD_FT, tuple(b), segment.end,
                          (segment.length_ft, segment.length_ft))

    def derivative_guard(distance):
        # Inverse-azimuth conditioning scales with position error / range.
        return 2 * DISTANCE_GUARD_FT / max(distance, DISTANCE_GUARD_FT)

    d0, g0, q0 = evaluate_s(0)
    d1, g1, q1 = evaluate_s(geom_length)
    guard0, guard1 = derivative_guard(d0), derivative_guard(d1)
    if abs(g0) <= guard0 and d0 > DISTANCE_GUARD_FT:
        raise NumericalFailure(f"start endpoint derivative sign unresolved for {segment.id}")
    if abs(g1) <= guard1 and d1 > DISTANCE_GUARD_FT:
        raise NumericalFailure(f"end endpoint derivative sign unresolved for {segment.id}")
    if g0 > guard0:
        f, best, q = 0.0, d0, q0
        offset_bounds = (0.0, 0.0)
        low = max(0.0, d0 - DISTANCE_GUARD_FT)
        high = d0 + DISTANCE_GUARD_FT
    elif g1 < -guard1:
        f, best, q = 1.0, d1, q1
        offset_bounds = (segment.length_ft, segment.length_ft)
        low = max(0.0, d1 - DISTANCE_GUARD_FT)
        high = d1 + DISTANCE_GUARD_FT
    else:
        left, right = 0.0, geom_length
        gl, gr = g0, g1
        semi_minor = 20925646.325459316 * (1 - 1 / 298.257223563)
        curvature_root = 1 / semi_minor
        for _ in range(max_evaluations - evaluations):
            mid = (left + right) / 2
            if mid == left or mid == right:
                raise NumericalFailure(f"geodesic root precision exhausted for {segment.id}")
            dm, gm, qm = evaluate_s(mid)
            if dm == 0:
                fraction = mid / geom_length
                offset = offset_from_fraction(fraction, segment.length_ft)
                return Projection(segment.id, fraction, offset, 0.0, 0.0, DISTANCE_GUARD_FT, qm,
                                  None, (offset, offset))
            local_radius = min(radius_bound, dm + (right - left) / 2)
            hessian_floor = 0.75 * curvature_root / math.tan(curvature_root * local_radius)
            if not math.isfinite(hessian_floor) or hessian_floor <= 0:
                raise NumericalFailure(f"convexity derivative bound unavailable for {segment.id}")
            mid_guard = derivative_guard(dm)
            if 2 * mid_guard > 0.5:
                raise NumericalFailure(f"inverse-azimuth conditioning unresolved for {segment.id}")
            root_guard_s = mid_guard / hessian_floor
            # The 0.75 Hessian factor is valid while the guarded root has
            # |f'| <= 0.5; reject if numeric conditioning cannot establish it.
            if (right - left + 2 * root_guard_s) * segment.length_ft / geom_length <= UNCERTAINTY_FT:
                break
            gm_guard = derivative_guard(dm)
            if gm > gm_guard:
                right, gr = mid, gm
            elif gm < -gm_guard:
                left, gl = mid, gm
            else:
                root_guard_s = (abs(gm) + gm_guard) / hessian_floor
                symmetric_left = max(left, mid - root_guard_s)
                symmetric_right = min(right, mid + root_guard_s)
                if (symmetric_right - symmetric_left) * segment.length_ft / geom_length <= UNCERTAINTY_FT:
                    left, right = symmetric_left, symmetric_right
                else:
                    # The true derivative lies in [gm-guard, gm+guard].
                    # Bound each side independently when the symmetric
                    # interval is too wide, preserving resolved positions.
                    left_extent = max(0.0, gm + gm_guard) / hessian_floor
                    right_extent = max(0.0, gm_guard - gm) / hessian_floor
                    left = max(left, mid - left_extent)
                    right = min(right, mid + right_extent)
                break
        else:
            raise NumericalFailure(f"geodesic projection work cap reached for {segment.id}")
        if right - left > geom_length:
            raise NumericalFailure(f"geodesic root was not bracketed for {segment.id}")
        s = (left + right) / 2
        best, _, q = evaluate_s(s)
        f = s / geom_length
        offset_bounds = (left / geom_length * segment.length_ft,
                         right / geom_length * segment.length_ft)
        if offset_bounds[1] - offset_bounds[0] > UNCERTAINTY_FT:
            raise NumericalFailure(f"source offset uncertainty exceeds 1e-6 foot for {segment.id}")
        # Convex tangent supports at the bracket endpoints provide a lower
        # bound on the minimum; the midpoint evaluation is the upper bound.
        dl, gl, _ = evaluate_s(left)
        dr, gr, _ = evaluate_s(right)
        tangent_low = max(dl + min(0.0, (gl - derivative_guard(dl)) * (right - left)),
                          dr + min(0.0, (gr + derivative_guard(dr)) * (left - right)))
        low = max(0.0, tangent_low - DISTANCE_GUARD_FT)
        high = best + DISTANCE_GUARD_FT
        if high - low > UNCERTAINTY_FT:
            raise NumericalFailure(f"distance uncertainty exceeds 1e-6 foot for {segment.id}")
    endpoint = segment.start if f == 0 else segment.end if f == 1 else None
    offset = offset_from_fraction(f, segment.length_ft)
    return Projection(segment.id, f, offset, best, low, high, q, endpoint, offset_bounds)


def snap_origin(segments, coordinates, point, *, maximum_ft=500, max_evaluations=MAX_SOLVE_EVALUATIONS) -> SnapResult:
    """Globally inspect all included segments and return exact-limit eligibility."""
    _validate_point(point)
    if not math.isfinite(maximum_ft) or maximum_ft < 0:
        raise ValueError("maximum_ft must be finite and nonnegative")
    rows = sorted(segments, key=lambda s: s.id)
    if len({s.id for s in rows}) != len(rows):
        raise ValueError("duplicate segment identity")
    projections = []
    unresolved = []
    endpoint_cache = {}
    nearest_upper = math.inf
    candidates = []
    for s in rows:
        a, b = coordinates[s.start], coordinates[s.end]
        _validate_point(a); _validate_point(b)
        da = endpoint_cache.setdefault(s.start, None)
        if da is None:
            da = endpoint_cache[s.start] = _distance(point, a)
        db = endpoint_cache.setdefault(s.end, None)
        if db is None:
            db = endpoint_cache[s.end] = _distance(point, b)
        _, _, length = GEOD.inv(*a, *b)
        bound = max(0.0, da - length, db - length, (da + db - length) / 2) - 3 * DISTANCE_GUARD_FT
        bound = max(0.0, bound)
        # A strict lower bound above the best sampled result cannot win. For
        # off-network cases, a lower bound above the eligibility radius also
        # proves that this segment cannot produce an eligible snap.
        candidates.append((bound, s, da, db, length))
    for bound, s, da, db, length in sorted(candidates, key=lambda item: (item[0], item[1].id)):
        if bound > min(nearest_upper, maximum_ft):
            continue
        try:
            projected = _project(s, coordinates, point, max_evaluations=max_evaluations,
                                 endpoint_distances=(da, db), geom_length=length)
        except NumericalFailure as error:
            unresolved.append((bound, str(error)))
            continue
        projections.append(projected)
        nearest_upper = min(nearest_upper, projected.distance_upper_ft)
    if any(bound <= min(nearest_upper, maximum_ft) for bound, _ in unresolved):
        message = next(message for bound, message in unresolved if bound <= min(nearest_upper, maximum_ft))
        raise NumericalFailure(message)
    projections = tuple(projections)
    if not projections:
        return SnapResult("off_network" if rows else "no_network", None, (), maximum_ft)
    nearest_upper = min(p.distance_upper_ft for p in projections)
    contenders = [p for p in projections if p.distance_lower_ft <= nearest_upper]
    # Coalesce same source endpoint only. Keep distinct IDs at coincident XY.
    unique = {}
    for p in contenders:
        key = ("node", p.endpoint_node) if p.endpoint_node is not None else ("segment", p.candidate_id)
        old = unique.get(key)
        if old is None or (p.distance_ft, p.candidate_id) < (old.distance_ft, old.candidate_id):
            unique[key] = p
    contenders = list(unique.values())
    lower = min(p.distance_lower_ft for p in contenders)
    upper = min(p.distance_upper_ft for p in contenders)
    if not within_snap_limit(lower, upper, maximum_ft):
        return SnapResult("off_network", None, tuple(sorted(contenders, key=lambda p: p.candidate_id)), maximum_ft)
    # Find all candidates whose certified intervals overlap the best interval.
    eligible = [p for p in contenders if p.distance_lower_ft <= upper and p.distance_upper_ft >= lower]
    if len(eligible) == 1:
        chosen = eligible[0]
    else:
        # A tie is established only when coordinates and measured distances are
        # exactly equal; overlapping nonidentical intervals are unresolved.
        ref = eligible[0]
        if any(not _provable_distance_tie(ref, p, point) for p in eligible[1:]):
            raise NumericalFailure("nearest candidate ordering cannot be resolved")
        chosen = min(eligible, key=lambda p: (-p.point[1], p.candidate_id))
    return SnapResult("resolved", chosen, tuple(sorted(eligible, key=lambda p: p.candidate_id)), maximum_ft)


def _provable_distance_tie(a: Projection, b: Projection, origin: Sequence[float]) -> bool:
    """Recognize only exact shared-point or WGS84 reflection symmetries."""
    if a.point == b.point:
        return True
    origin_lon, origin_lat = origin
    a_delta = ((a.point[0] - origin_lon + 180) % 360) - 180
    b_delta = ((b.point[0] - origin_lon + 180) % 360) - 180
    meridian_reflection = a.point[1] == b.point[1] and a_delta == -b_delta
    equator_reflection = origin_lat == 0 and a.point[0] == b.point[0] and a.point[1] == -b.point[1]
    return meridian_reflection or equator_reflection


def traverse_reference(segments, projection: Projection, budget_ft: float, readiness=Readiness()):
    """Traverse from snapped source point; connector is recorded but costs no time."""
    if not math.isfinite(budget_ft) or budget_ft < 0:
        raise ValueError("budget_ft must be finite and nonnegative")
    segment = next((s for s in segments if s.id == projection.candidate_id), None)
    if segment is None:
        raise ValueError("origin segment is absent")
    origin = Origin(node=projection.endpoint_node) if projection.endpoint_node is not None else Origin(
        segment=segment.id, offset_ft=projection.offset_ft, access_distance_ft=0)
    # One second per foot makes the existing pure graph traversal a distance
    # traversal. The passed budget is the exact prescribed distance in feet.
    return traverse(segments, origin, budget_ft, 1.0, readiness)

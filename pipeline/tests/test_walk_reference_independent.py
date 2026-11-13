"""Independent, hand-specified checks for the step 3 reference method."""
from __future__ import annotations

import math
from fractions import Fraction
from pathlib import Path
import sys

import pytest
from pyproj import Geod

from flm_pipeline.routing import Readiness, Segment
from flm_pipeline.walk_reference import (
    GEOD,
    NumericalFailure,
    Projection,
    offset_from_fraction,
    snap_origin,
    traverse_reference,
    within_snap_limit,
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from independent_walk_reference_check import boundary_frontier, configured_bbox, ecef_bbox_edge_lower_bound, expected_tile_record, independent_dijkstra


WGS84_FEET = Geod(a=20_925_646.325459316, rf=298.257223563)


def test_independent_tile_schema_mapping_matches_actual_v0_record_shape() -> None:
    segment = {"candidate_id": "w42/0", "from_node_id": "n10", "to_node_id": "n11",
               "length_ft": 12.5, "direction": "both", "coordinates": [[-105, 39], [-105.001, 39]],
               "way_id": "w42"}
    way = {"tags": {"highway": "footway", "name": "Trail", "footway": "sidewalk"}}
    assert expected_tile_record(segment, way) == {
        "id": "w42/0", "from": "n10", "to": "n11", "len_ft": 12.5,
        "dir": "both", "coords": [[-105, 39], [-105.001, 39]], "way_id": "w42",
        "hwy": "footway", "name": "Trail", "sidewalk": "", "footway": "sidewalk",
    }


def test_sample_index_bbox_rounds_to_prepared_toml_precision() -> None:
    computed = [-104.812345678901234, 40.300000000000004, -104.6, 40.55]
    configured = tuple(float(format(value, ".15g")) for value in computed)
    assert configured_bbox(computed) == configured
    assert configured_bbox(computed) != tuple(computed)


def test_ecef_edge_margin_uses_global_chord_and_meridian_plane_bounds() -> None:
    origin = (-104.6928167, 40.4249)
    bbox = (-104.8, 40.3, -104.6, 40.55)
    result = ecef_bbox_edge_lower_bound(origin, bbox)
    assert result["global_edge_lower_bound_ft"] > 5000


def _direct(lon: float, lat: float, azimuth: float, feet: float) -> tuple[float, float]:
    x, y, _ = WGS84_FEET.fwd(lon, lat, azimuth, feet)
    return x, y


def test_foot_scaled_wgs84_and_exact_speed_budgets() -> None:
    # Closed-form equatorial arc: a * pi / 180, with a expressed in feet.
    expected = 20_925_646.325459316 * math.pi / 180
    assert WGS84_FEET.inv(0, 0, 1, 0)[2] == pytest.approx(expected, abs=1e-9)
    assert GEOD.inv(0, 0, 1, 0)[2] == pytest.approx(365_221.426487118, abs=1e-9)
    # 2.8 mph is exactly 14,784 feet per hour, hence 246.4 ft/min.
    assert [Fraction(14, 5) * 5280 * minutes / 60 for minutes in (5, 10, 15)] == [1232, 2464, 3696]


def test_directional_interior_origin_uses_full_budget_and_source_offsets() -> None:
    rows = [
        Segment("A", "u", "v", 100, "forward"),
        Segment("B", "v", "w", 100, "reverse"),
        Segment("C", "v", "x", 40, "forward"),
    ]
    start = Projection("A", 0.4, 40, 10, 10, 10, (0.0, 0.0), None)
    result = traverse_reference(rows, start, 80, Readiness(coverage="synthetic_closed"))

    assert result.node_seconds == {"v": 60.0}
    assert result.intervals_ft == {"A": [(40, 100)], "C": [(0, 20)]}
    assert result.unique_source_length_ft == 80
    assert result.connector_seconds == 0
    assert result.connector_length_ft == 0
    # Reverse-only B enters v from w, so it cannot be traversed outward from v.
    assert "B" not in result.intervals_ft


def test_endpoint_origin_enters_every_permitted_incident_direction() -> None:
    rows = [
        Segment("forward-in", "p", "q", 20, "forward"),
        Segment("reverse-out", "r", "p", 30, "reverse"),
        Segment("wrong-way", "p", "s", 50, "reverse"),
    ]
    at_p = Projection("forward-in", 0, 0, 0, 0, 0, (0.0, 0.0), "p")
    result = traverse_reference(rows, at_p, 25, Readiness(coverage="synthetic_closed"))
    assert result.node_seconds == {"p": 0.0, "q": 20.0}
    assert result.intervals_ft == {"forward-in": [(0, 20)], "reverse-out": [(5, 30)]}
    assert "wrong-way" not in result.intervals_ft


def test_geometric_crossing_without_shared_source_node_is_not_a_junction() -> None:
    rows = [
        Segment("horizontal", "h0", "h1", 100, "both"),
        Segment("vertical", "v0", "v1", 100, "both"),
    ]
    # The lines cross at their geometric midpoints, but the endpoints have
    # distinct source IDs. Routing must use those IDs, not coordinate overlap.
    coordinates = {"h0": (-0.001, 0.0), "h1": (0.001, 0.0),
                   "v0": (0.0, -0.001), "v1": (0.0, 0.001)}
    assert coordinates["h0"][0] < coordinates["v0"][0] < coordinates["h1"][0]
    origin = Projection("horizontal", 0.5, 50, 0, 0, 0, (0.0, 0.0), None)
    result = traverse_reference(rows, origin, 50, Readiness(coverage="synthetic_closed"))
    assert result.intervals_ft == {"horizontal": [(0, 100)]}
    assert "vertical" not in result.intervals_ft


def test_independent_frontier_keeps_boundary_node_reached_at_exact_zero_budget() -> None:
    segment = Segment("edge", "boundary", "inside", 20, "both")
    origin = Projection("edge", 0, 0, 0, 0, 0, (0.0, 0.0), "boundary")
    intervals, distances = independent_dijkstra([segment], origin, 0)
    result = traverse_reference([segment], origin, 0, Readiness(coverage="synthetic_closed", frontier_nodes=("boundary",)))

    assert intervals == {}
    assert distances == {"boundary": 0}
    assert boundary_frontier({"boundary"}, distances, 0) == {"boundary": 0}
    assert result.frontier == {"boundary": 0}


def test_projection_uses_fraction_for_geometry_and_copied_length_for_offset() -> None:
    segment = Segment("rounded", "a", "b", 1000, "both")
    coords = {"a": (0.0, 0.0), "b": (0.001, 0.0)}
    # Exact equatorial midpoint specified independently of the implementation.
    point = (0.0005, 0.0)
    snap = snap_origin([segment], coords, point)
    assert snap.status == "resolved"
    assert snap.selected is not None
    assert snap.selected.fraction == pytest.approx(0.5, abs=1e-9)
    assert snap.selected.offset_ft == pytest.approx(500, abs=1e-6)
    assert snap.selected.distance_ft <= 1e-6
    assert offset_from_fraction(0.25, 1000) == 250


def test_certified_snap_limit_is_inclusive_without_an_epsilon() -> None:
    assert within_snap_limit(500, 500) is True
    assert within_snap_limit(499.999, 499.999) is True
    assert within_snap_limit(500.001, 500.001) is False
    with pytest.raises(NumericalFailure):
        within_snap_limit(499.9999, 500.0001)


def test_geod_limit_representation_fails_when_numerical_bounds_overlap() -> None:
    segment_end = (0.0, 0.0)
    # Put the one-foot source segment on the same meridian, extending away
    # from the snap point. This gives independently exact endpoint distances.
    one_foot_south = _direct(*segment_end, 180, 1)
    segment = Segment("edge", "a", "b", 1, "both")

    def run(distance: float):
        origin = _direct(*segment_end, 0, distance)
        return snap_origin([segment], {"a": segment_end, "b": one_foot_south}, origin)

    # The fwd-generated float coordinate is not an exact 500-foot oracle; the
    # returned certified interval straddles the limit, so it must fail closed.
    with pytest.raises(NumericalFailure, match="overlaps"):
        run(500)
    assert run(499.999).status == "resolved"
    assert run(500.001).status == "off_network"


def test_northernmost_true_tie_wins_independent_of_input_order() -> None:
    rows = [Segment("south", "s0", "s1", 100, "both"), Segment("north", "n0", "n1", 100, "both")]
    coordinates = {
        "s0": (-0.001, -0.001), "s1": (0.001, -0.001),
        "n0": (-0.001, 0.001), "n1": (0.001, 0.001),
    }
    point = (0.0, 0.0)
    first = snap_origin(rows, coordinates, point)
    reversed_result = snap_origin(list(reversed(rows)), coordinates, point)
    assert first.selected is not None and reversed_result.selected is not None
    assert first.selected.candidate_id == "north"
    assert reversed_result.selected.candidate_id == "north"


def test_coincident_distinct_source_ids_remain_distinct_and_use_id_tie_break() -> None:
    rows = [Segment("z-id", "z-start", "z-end", 100, "both"), Segment("a-id", "a-start", "a-end", 100, "both")]
    coordinates = {
        "z-start": (0.0, 0.0), "z-end": (0.001, 0.0),
        "a-start": (0.0, 0.0), "a-end": (0.001, 0.0),
    }
    result = snap_origin(rows, coordinates, (0.0, 0.0))
    assert result.selected is not None
    assert result.selected.candidate_id == "a-id"
    assert result.selected.endpoint_node == "a-start"
    assert {p.candidate_id for p in result.candidates} == {"a-id", "z-id"}


def test_projection_work_cap_fails_instead_of_returning_unresolved_answer() -> None:
    segment = Segment("long", "a", "b", 100_000, "both")
    with pytest.raises(NumericalFailure):
        snap_origin([segment], {"a": (-1.0, 0.0), "b": (1.0, 0.0)}, (0.0, 0.001), max_evaluations=2)

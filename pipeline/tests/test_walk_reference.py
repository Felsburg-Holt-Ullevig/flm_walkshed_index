import math

import pytest

from flm_pipeline.routing import Segment
from flm_pipeline.walk_reference import (
    GEOD,
    NumericalFailure,
    Projection,
    interpolate_fraction,
    offset_from_fraction,
    snap_origin,
    traverse_reference,
    within_snap_limit,
)


def test_geodesic_is_foot_scaled_against_equatorial_closed_form():
    # Independent analytic reference: an equatorial degree is a*pi/180.
    semi_major_ft = 20_925_646.325459316
    assert GEOD.inv(0, 0, 1, 0)[2] == pytest.approx(semi_major_ft * math.pi / 180, abs=1e-9)


def test_fraction_interpolation_and_source_length_mapping():
    start, end = (0, 0), (1, 0)
    assert interpolate_fraction(start, end, 0) == start
    assert interpolate_fraction(start, end, 1) == end
    assert interpolate_fraction(start, end, 0.5) == pytest.approx((0.5, 0), abs=1e-12)
    # Offset uses the copied package length, not the ellipsoid geometry length.
    assert offset_from_fraction(0.25, 80) == 20


def test_off_network_is_distinct_from_empty_network():
    segment = Segment("s", "a", "b", 10, "both")
    coords = {"a": (0, 0), "b": (0.00001, 0)}
    assert snap_origin([], {}, (0, 0)).status == "no_network"
    assert snap_origin([segment], coords, (1, 1)).status == "off_network"


def test_solver_failure_is_explicit():
    segment = Segment("s", "a", "b", 100, "both")
    coords = {"a": (0, 0), "b": (0.0001, 0)}
    with pytest.raises(NumericalFailure, match="work cap"):
        snap_origin([segment], coords, (0.00005, 0.0001), max_evaluations=2)


def test_limit_comparison_is_inclusive_and_has_no_epsilon():
    assert within_snap_limit(500, 500) is True
    assert within_snap_limit(499.999, 499.999) is True
    assert within_snap_limit(500.001, 500.001) is False
    with pytest.raises(NumericalFailure, match="overlaps"):
        within_snap_limit(499.9999999, 500.0000001)


def test_c01_local_geodesic_reference_from_independent_root_fixture():
    segment = Segment("way/792734731/segment/0", "7412752634", "7412752639", 224.5495460269397, "both")
    coords = {"7412752634": (-104.943073, 39.8265983), "7412752639": (-104.9428759, 39.8260009)}
    result = snap_origin([segment], coords, (-104.943057, 39.826361))
    assert result.status == "resolved"
    assert result.selected is not None
    assert result.selected.offset_ft == pytest.approx(84.88237787, abs=2e-7)
    assert result.selected.distance_ft == pytest.approx(16.95622533, abs=2e-7)
    assert result.selected.point == pytest.approx((-104.94299849347304, 39.826372475797854), abs=2e-12)
    assert result.selected.offset_bounds_ft is not None
    assert result.selected.offset_bounds_ft[1] - result.selected.offset_bounds_ft[0] <= 1e-6


def test_f01_short_segment_derivative_uncertainty_keeps_certified_offset_bracket():
    segment = Segment("way/1281864112/segment/0", "11896041505", "11896041506",
                      165.05728614127887, "both")
    coords = {"11896041505": (-105.8193051, 39.9476397),
              "11896041506": (-105.8193038, 39.9480928)}
    result = snap_origin([segment], coords, (-105.81945, 39.94776))
    assert result.status == "resolved"
    assert result.selected is not None
    assert result.selected.offset_ft == pytest.approx(43.73352398414639, abs=1e-7)
    assert result.selected.distance_ft == pytest.approx(40.72329441482667, abs=2e-7)
    assert result.selected.point == pytest.approx((-105.8193047555541, 39.9477597532297), abs=2e-12)
    assert result.selected.offset_bounds_ft is not None
    assert result.selected.offset_bounds_ft[0] <= 43.73352398414639 <= result.selected.offset_bounds_ft[1]
    assert result.selected.offset_bounds_ft[1] - result.selected.offset_bounds_ft[0] <= 1e-6


def test_f01_reversed_source_orientation_preserves_root_and_offset_uncertainty():
    length = 165.05728614127887
    segment = Segment("way/1281864112/segment/0", "11896041506", "11896041505", length, "both")
    coords = {"11896041505": (-105.8193051, 39.9476397),
              "11896041506": (-105.8193038, 39.9480928)}
    result = snap_origin([segment], coords, (-105.81945, 39.94776))
    assert result.selected is not None
    expected_reverse_offset = length - 43.73352398414639
    assert result.selected.offset_ft == pytest.approx(expected_reverse_offset, abs=1e-7)
    assert result.selected.offset_bounds_ft is not None
    assert result.selected.offset_bounds_ft[0] <= expected_reverse_offset <= result.selected.offset_bounds_ft[1]
    assert result.selected.offset_bounds_ft[1] - result.selected.offset_bounds_ft[0] <= 1e-6


@pytest.mark.parametrize("direction, expected", [("both", 20), ("forward", 10), ("reverse", 10)])
def test_traversal_uses_exact_foot_budget_and_direction(direction, expected):
    segment = Segment("s", "a", "b", 20, direction)
    projection = Projection("s", 0.5, 10, 0, 0, 0, (0, 0), None)
    result = traverse_reference([segment], projection, 10)
    assert result.computation_status == "incomplete"
    assert result.intervals_ft == {"s": [(0, 20)]} if direction == "both" else (
        {"s": [(10, 20)]} if direction == "forward" else {"s": [(0, 10)]}
    )
    assert result.unique_source_length_ft == expected

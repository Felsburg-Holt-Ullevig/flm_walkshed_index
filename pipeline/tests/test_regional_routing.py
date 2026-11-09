from __future__ import annotations

import json

import pytest
from pyproj import Geod

from flm_pipeline.regional_routing import (
    _checks_pass,
    _costs_by_interval,
    _sample_origins,
    _write_inspection_gpkg,
    geodesic_bbox_clip,
)
from flm_pipeline.routing import Origin, Readiness, Segment, traverse


def test_parent_acceptance_requires_boolean_checks_and_separate_export_details():
    assert _checks_pass({"worker_exit_zero": True, "gpkg_reopened": True}) is True
    assert _checks_pass({"worker_exit_zero": True, "gpkg_layers": {"nodes": 2}}) is False
    assert _checks_pass({"worker_exit_zero": 1}) is False


def test_geodesic_bbox_clip_finds_intersection_when_both_endpoints_are_outside():
    start = (-105.01, 39.75)
    end = (-104.99, 39.75)
    bbox = (-105.001, 39.74, -104.999, 39.76)

    intervals, intersects = geodesic_bbox_clip(start, end, bbox, sample_step_ft=100)

    _, _, full_m = Geod(ellps="WGS84").inv(*start, *end)
    full_ft = full_m / 0.3048
    assert intersects is True
    assert len(intervals) == 1
    assert intervals[0][0] == pytest.approx(full_ft * 0.45, abs=0.02)
    assert intervals[0][1] == pytest.approx(full_ft * 0.55, abs=0.02)


def test_geodesic_bbox_clip_keeps_boundary_touch_without_positive_length():
    start = (-105.01, 39.75)
    end = (-105.0, 39.75)
    bbox = (-105.0, 39.74, -104.99, 39.76)

    intervals, intersects = geodesic_bbox_clip(start, end, bbox)

    assert intersects is True
    assert intervals == []


def test_geodesic_bbox_clip_rejects_distant_source_segment():
    intervals, intersects = geodesic_bbox_clip(
        (-105.01, 39.75), (-105.0, 39.75), (-104.9, 39.7, -104.8, 39.8)
    )

    assert intervals == []
    assert intersects is False


def test_origin_sample_is_stable_and_starts_with_accepted_anchor():
    coords = {
        str(i): (-105.04 + i * 0.0005, 39.72 + (i % 10) * 0.0005)
        for i in range(100)
    }

    first = _sample_origins(coords, "0", (-105.04, 39.72, -104.97, 39.79), count=10)
    second = _sample_origins(coords, "0", (-105.04, 39.72, -104.97, 39.79), count=10)

    assert first == second
    assert first[0] == "0"
    assert len(set(first)) == 10


def test_interval_costs_follow_source_direction_and_node_costs():
    segments = [Segment("way/1/segment/0", "a", "b", 100, "forward")]
    result = _costs_by_interval(segments, {"a": 12.0}, {"way/1/segment/0": [(25, 75)]}, 0.2)

    assert result == [{
        "candidate_id": "way/1/segment/0",
        "from_offset_ft": 25,
        "to_offset_ft": 75,
        "length_ft": 50,
        "seconds_at_from_offset": 17.0,
        "seconds_at_to_offset": 27.0,
    }]


def test_interval_costs_fail_if_interval_has_no_reached_allowed_endpoint():
    segments = [Segment("way/1/segment/0", "a", "b", 100, "reverse")]

    with pytest.raises(ValueError, match="directionally allowed endpoint"):
        _costs_by_interval(segments, {"a": 0.0}, {"way/1/segment/0": [(20, 30)]}, 0.2)


def test_geopackage_export_reopens_origin_nodes_intervals_costs_and_empty_connectors(tmp_path):
    geod = Geod(ellps="WGS84")
    origin = (-105.0, 39.75)
    lon, lat, _ = geod.fwd(*origin, 90, 100 * 0.3048)
    coordinates = {"a": origin, "b": (lon, lat)}
    segments = [Segment("way/1/segment/0", "a", "b", 100, "both")]
    result = traverse(segments, Origin(node="a"), 20, 0.2, Readiness(("unknown_candidates",), "not_established"))
    summary = {}
    accepted_origin = {"id": "origin-1", "source_node_id": "a"}

    _write_inspection_gpkg(tmp_path / "inspection.gpkg", accepted_origin, coordinates,
                           {"result": result}, segments, (-105.1, 39.7, -104.9, 39.8), 0.2, summary)

    assert summary["gpkg_reopen_checks"]["reachable_interval_ids_geometry_lengths_and_costs"] is True
    assert summary["gpkg_layers"]["origin_access"] == 1

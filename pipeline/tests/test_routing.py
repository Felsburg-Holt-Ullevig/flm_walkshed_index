from dataclasses import replace
import math

import pytest

from flm_pipeline.routing import Origin, Readiness, Segment, combined_intervals, traverse
from flm_pipeline.routing_geometry import interpolate, project, snap_origin
from flm_pipeline.routing_adapter import compare_core
from test_routing_references import load_accepted_references

CLOSED = Readiness(coverage="synthetic_closed")
_, REFERENCES, SETTINGS = load_accepted_references()
SCALE = float(REFERENCES["seconds_per_foot"])


@pytest.mark.parametrize("case", REFERENCES["cases"], ids=lambda c: c["id"])
def test_literal_metric_results(case):
    segments = [Segment(e["id"], e["from"], e["to"], e["length_ft"], e["direction"]) for e in case["edges"]]
    result = traverse(segments, Origin(**case["origin"]), case["budget_distance_equivalent_ft"] * SCALE, SCALE, CLOSED)
    assert result.computation_status == case["expected_status"]
    expected_nodes = case["expected_node_distances_ft"]
    if expected_nodes is None:
        assert result.node_seconds is result.intervals_ft is result.unique_source_length_ft is None
        return
    assert result.node_seconds == pytest.approx({k: v * SCALE for k, v in expected_nodes.items()}, abs=1e-9)
    assert result.intervals_ft.keys() == case["expected_intervals_ft"].keys()
    for key, expected in case["expected_intervals_ft"].items():
        assert len(result.intervals_ft[key]) == len(expected)
        for actual, wanted in zip(result.intervals_ft[key], expected):
            assert actual == pytest.approx(wanted, abs=1e-8)
    assert result.unique_source_length_ft == pytest.approx(case["expected_unique_source_length_ft"], abs=1e-8)
    if "expected_network_origin_reached" in case:
        assert result.network_origin_reached is case["expected_network_origin_reached"]
    assert traverse(list(reversed(segments)), Origin(**case["origin"]), case["budget_distance_equivalent_ft"] * SCALE, SCALE, CLOSED) == result
    assert combined_intervals([result, result]) == result.intervals_ft
    larger = traverse(segments, Origin(**case["origin"]), (case["budget_distance_equivalent_ft"] + 100) * SCALE, SCALE, CLOSED)
    for key, intervals in result.intervals_ft.items():
        for lo, hi in intervals:
            assert any(a <= lo and b >= hi for a, b in larger.intervals_ft[key])


def test_strict_budget_and_failure_states():
    segments = [Segment("AB", "A", "B", 100), Segment("BC", "B", "C", 100)]
    for distance in (99, 99.999, 100, 100.001, 101):
        result = traverse(segments, Origin(node="A"), distance * SCALE, SCALE, CLOSED)
        assert result.unique_source_length_ft == pytest.approx(distance)
        assert ("B" in result.node_seconds) == (distance >= 100)
    for budget in (-1, float("nan"), float("inf"), True):
        assert traverse(segments, Origin(node="A"), budget, SCALE).computation_status == "failed"
    assert traverse(segments * 2, Origin(node="A"), 100, SCALE).computation_status == "failed"
    assert traverse(segments, Origin(segment="unknown"), 100, SCALE).computation_status == "failed"
    assert traverse(segments, Origin(node="A"), 100, SCALE, Readiness(in_domain=False)).computation_status == "out_of_coverage"
    result = traverse(segments, Origin(node="A"), 100 * SCALE, SCALE, Readiness(("unknown",), "not_established", ("B",)))
    assert result.computation_status == "incomplete" and result.policy_readiness == "blocked"
    assert result.frontier == {"B": 0} and result.coverage_readiness == "not_established"
    result = traverse(segments, Origin(node="A"), 101 * SCALE, SCALE, Readiness(frontier_nodes=("B",)))
    assert result.computation_status == result.coverage_readiness == "incomplete_coverage"


def test_planar_snap_ties_limits_and_shared_nodes():
    ab = Segment("AB", "A", "B", 100)
    xy = {"A": (0, 0), "B": (100, 0), "C": (100, 100), "D": (100, 0)}
    snapped = snap_origin([ab], xy, (50, 10))
    assert snapped.origin == Origin(segment="AB", offset_ft=50, access_distance_ft=10)
    assert snap_origin([ab], xy, (50, 100)).status == "resolved"
    assert snap_origin([ab], xy, (50, 100.01)).status == "off_network"
    shared = [ab, Segment("BC", "B", "C", 100)]
    assert snap_origin(shared, xy, (100, 0)).status == "resolved"
    disjoint = [ab, Segment("DC", "D", "C", 100)]
    assert snap_origin(disjoint, xy, (100, 0)).status == "ambiguous_origin"
    assert [p.candidate_id for p in snap_origin(disjoint, xy, (100, 0)).projections] == ["AB", "DC"]
    assert snap_origin(disjoint, xy, (100, 0), selected_id="DC").status == "resolved"
    with pytest.raises(ValueError):
        snap_origin(disjoint, xy, (100, 0), selected_id="excluded")
    # Endpoint source identity gives access to incident arcs even when the
    # selected segment permits travel only toward that endpoint.
    endpoint = traverse([replace(ab, direction="forward"), shared[1]], Origin(segment="AB", offset_ft=100), 20, 1, CLOSED)
    assert endpoint.intervals_ft == {"BC": [(0, 20)]}


def test_geographic_projection_and_clipped_points():
    length = (6378137 * math.pi / 180 * 0.001) / 0.3048
    start, end = (0, 0), (0.001, 0)
    p = project("equator", "1", "2", start, end, (0.0005, 0), geographic=True)
    assert p.distance_ft <= 0.001
    assert p.offset_ft == pytest.approx(length / 2, abs=0.001)
    assert interpolate(start, end, length / 4, geographic=True) == pytest.approx((0.00025, 0), abs=1e-12)
    p = project("equator", "1", "2", start, end, (0, 0), geographic=True)
    assert p.endpoint_node == "1" and p.offset_ft == p.distance_ft == 0
    with pytest.raises(ValueError):
        project("bad", "1", "2", start, end, (0, 100), geographic=True)


def test_expanded_core_comparison_retains_differences():
    observation = {"source_sha256": "source", "policy_sha256": "policy", "origin": {"node": "1"}, "core_bbox": [0, 0, 1, 1],
                   "candidates": {"AB": "include"}, "node_seconds": {"1": 0}, "intervals_ft": {"AB": [(0, 10)]}}
    assert compare_core(observation, observation)["coverage_readiness"] == "not_established"
    expanded = {**observation, "intervals_ft": {"AB": [(0, 5), (6, 10)]}}
    assert compare_core(observation, expanded)["differences"][0]["category"] == "intervals_ft"
    with pytest.raises(ValueError):
        compare_core(observation, {**observation, "source_sha256": "other"})


def test_snap_direction_connector_and_near_tie():
    xy = {"A": (0, 0), "B": (100, 0), "C": (0, 20.01), "D": (100, 20.01)}
    ab = Segment("AB", "A", "B", 100, "forward")
    cd = Segment("CD", "C", "D", 100)
    snap = snap_origin([ab], xy, (50, 10))
    result = traverse([ab], snap.origin, 20 * SCALE, SCALE, CLOSED)
    assert result.intervals_ft == {"AB": [(50, 60)]}
    assert result.connector_length_ft == 10
    assert snap_origin([ab, cd], xy, (50, 10)).status == "ambiguous_origin"
    xy["C"], xy["D"] = (0, 20.011), (100, 20.011)
    assert snap_origin([ab, cd], xy, (50, 10)).selected.candidate_id == "AB"
    with pytest.raises(ValueError):
        snap_origin([replace(ab, length_ft=99)], xy, (50, 10))


def test_geographic_off_axis_and_dateline_projection():
    from flm_pipeline.routing_geometry import GEOD
    for start, end, midpoint in (((0, 0), (0.001, 0), (0.0005, 0)),
                                 ((179.999, 0), (-179.999, 0), (180, 0))):
        lon, lat, _ = GEOD.fwd(*midpoint, 0, 10 * 0.3048)
        projection = project("AB", "A", "B", start, end, (lon, lat), geographic=True)
        length = GEOD.inv(*start, *end)[2] / 0.3048
        assert projection.offset_ft == pytest.approx(length / 2, abs=0.01)
        assert projection.distance_ft == pytest.approx(10, abs=0.01)
        assert GEOD.inv(*projection.point, *midpoint)[2] / 0.3048 <= 0.01

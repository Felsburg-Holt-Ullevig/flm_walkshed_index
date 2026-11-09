from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import tomllib
from typing import Any

import osmium
import pytest
from shapely.geometry import LineString

from flm_pipeline.classification import run_classification
from flm_pipeline.extractor import ExtractionFailure, _coordinates
from flm_pipeline.graph import _inspect_gpkg, build_graph, validate_graph
from flm_pipeline.pedestrian_config import load_pedestrian_settings
from test_extractor import _invoke_extract, _prepare_inputs


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "pipeline" / "fixtures"
POLICY_CONFIG = ROOT / "pipeline" / "config" / "pedestrian-policy.example.toml"
SOURCE_CASES = FIXTURES / "routing-source-cases-v1.json"
METRIC_REFERENCES = FIXTURES / "routing-references-v1.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_accepted_references(file_overrides: dict[str, Path] | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Load only the reference/configuration bytes covered by the acceptance manifest."""
    manifest_path = ROOT / "pipeline" / "fixtures" / "routing-reference-acceptance-v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != "routing-reference-acceptance-1" or manifest.get("status") != "accepted_experimental":
        raise ValueError("Routing references are not accepted for experimental testing")

    expected_files = manifest.get("sha256")
    required_files = {
        "pipeline/routing-reference-spec.md",
        "pipeline/fixtures/routing-references-v1.json",
        "pipeline/config/routing-benchmarks.v1.toml",
    }
    if not isinstance(expected_files, dict) or set(expected_files) != required_files:
        raise ValueError("Routing reference acceptance manifest has an invalid file list")
    for relative, expected_hash in expected_files.items():
        path = (file_overrides or {}).get(relative, ROOT / Path(relative))
        if relative not in (file_overrides or {}):
            try:
                path.resolve().relative_to(ROOT.resolve())
            except ValueError as error:
                raise ValueError("Accepted routing reference path leaves the repository") from error
        if not path.is_file() or _sha256(path) != expected_hash:
            raise ValueError(f"Routing reference bytes do not match accepted manifest: {relative}")

    spec_path = (file_overrides or {}).get("pipeline/routing-reference-spec.md", ROOT / "pipeline" / "routing-reference-spec.md")
    metric_path = (file_overrides or {}).get("pipeline/fixtures/routing-references-v1.json", ROOT / "pipeline" / "fixtures" / "routing-references-v1.json")
    settings_path = (file_overrides or {}).get("pipeline/config/routing-benchmarks.v1.toml", ROOT / "pipeline" / "config" / "routing-benchmarks.v1.toml")
    spec_text = spec_path.read_text(encoding="utf-8")
    metric_data = json.loads(metric_path.read_text(encoding="utf-8"))
    settings = tomllib.loads(settings_path.read_text(encoding="utf-8"))
    version_line = next((line for line in spec_text.splitlines() if line.startswith("Version:")), "")
    if "routing-references-1" not in version_line or "accepted experimental" not in version_line:
        raise ValueError("Routing reference specification is draft or has an unsupported version")
    if metric_data.get("version") != "routing-references-1" or metric_data.get("status") != "accepted_experimental":
        raise ValueError("Metric references are draft or have an unsupported version")
    if settings.get("benchmark_version") != "routing-benchmarks-1" or settings.get("status") != "accepted_experimental":
        raise ValueError("Routing benchmark settings are draft or have an unsupported version")
    if settings.get("complete_regional_runs_enabled") is not False or settings.get("coverage_status") != "not_established":
        raise ValueError("Accepted settings must keep complete regional routing disabled")
    return manifest, metric_data, settings


def _read_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write_source_pbf(path: Path, nodes: list[dict[str, Any]], ways: list[dict[str, Any]]) -> None:
    """Materialize literal fixture records as a small PBF for the production reader."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with osmium.SimpleWriter(path, overwrite=True) as writer:
        for row in nodes:
            writer.add_node(osmium.osm.mutable.Node(
                id=int(row["id"]), location=(float(row["lon"]), float(row["lat"])), tags=row["tags"]
            ))
        for row in ways:
            writer.add_way(osmium.osm.mutable.Way(
                id=int(row["id"]), nodes=[int(ref) for ref in row["node_refs"]], tags=row["tags"]
            ))


def _way_index(ways: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in ways}


def _source_pairs(ways: list[dict[str, Any]], way_ids: list[str]) -> list[tuple[str, str, str]]:
    index = _way_index(ways)
    result: list[tuple[str, str, str]] = []
    for way_id in way_ids:
        refs = index[way_id]["node_refs"]
        result.extend((way_id, refs[position], refs[position + 1]) for position in range(len(refs) - 1))
    return result


def _components(pairs: list[tuple[str, str]]) -> list[list[str]]:
    adjacency: dict[str, set[str]] = {}
    for left, right in pairs:
        adjacency.setdefault(left, set()).add(right)
        adjacency.setdefault(right, set()).add(left)
    pending = set(adjacency)
    groups: list[list[str]] = []
    while pending:
        first = min(pending, key=lambda value: (len(value), value))
        reached: set[str] = set()
        frontier = [first]
        while frontier:
            current = frontier.pop()
            if current in reached:
                continue
            reached.add(current)
            frontier.extend(adjacency[current] - reached)
        pending.difference_update(reached)
        groups.append(sorted(reached, key=lambda value: (len(value), value)))
    return groups


def _expected_candidate_map(fixture: dict[str, Any]) -> dict[str, tuple[str, str]]:
    groups = fixture["expected_candidates"]
    mapping: dict[str, tuple[str, str]] = {}
    for group, status, direction in (
        ("include_both", "include", "both"),
        ("include_forward", "include", "forward"),
        ("include_reverse", "include", "reverse"),
        ("unknown", "unknown", "unknown"),
        ("exclude_wall", "exclude", "none"),
        ("exclude_private", "exclude", "none"),
        ("exclude_zero_length", "exclude", "none"),
    ):
        for candidate_id in groups[group]:
            if candidate_id in mapping:
                raise AssertionError(f"Duplicate expected candidate: {candidate_id}")
            mapping[candidate_id] = (status, direction)
    return mapping


def _literal_segment_map(fixture: dict[str, Any]) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for way in fixture["ways"]:
        for sequence, (from_id, to_id) in enumerate(zip(way["node_refs"], way["node_refs"][1:])):
            result[f"way/{way['id']}/segment/{sequence}"] = (from_id, to_id)
    return result


def _assert_literal_source_topology(fixture: dict[str, Any]) -> None:
    """Check fixture references and declared topology before invoking production code."""
    nodes = {row["id"]: row for row in fixture["nodes"]}
    ways = _way_index(fixture["ways"])
    literal_segments = _literal_segment_map(fixture)
    expected_candidates = _expected_candidate_map(fixture)
    assert set(expected_candidates) == set(literal_segments)

    for case_name, case in fixture["topology_cases"].items():
        way_ids = case["way_ids"]
        pairs = _source_pairs(fixture["ways"], way_ids)
        if "expected_segments" in case:
            assert [[left, right] for _, left, right in pairs] == case["expected_segments"], case_name
        if "expected_components" in case:
            actual_components = _components([(left, right) for _, left, right in pairs])
            expected_components = sorted(case["expected_components"], key=lambda group: (len(group[0]), group[0]))
            assert actual_components == expected_components, case_name
        if case_name == "directional_alternatives":
            expected = {tuple(pair) for pair in case["expected_arcs"]}
            actual: set[tuple[str, str]] = set()
            for candidate_id, (status, direction) in expected_candidates.items():
                way_id = candidate_id.split("/")[1]
                if way_id not in way_ids or status != "include":
                    continue
                left, right = literal_segments[candidate_id]
                if direction in {"both", "forward"}:
                    actual.add((left, right))
                if direction in {"both", "reverse"}:
                    actual.add((right, left))
            assert actual == expected
        if case_name in {"coincident_endpoint_ids", "coincident_midpoint_distinct_ids"}:
            left_id, right_id = case["coincident_node_ids"]
            assert left_id != right_id and (nodes[left_id]["lon"], nodes[left_id]["lat"]) == (nodes[right_id]["lon"], nodes[right_id]["lat"])
        if case_name == "parallel_source_segments":
            assert sorted(f"way/{way_id}/segment/0" for way_id in way_ids) == sorted(case["expected_candidate_ids"])
        if case_name == "shared_junction_node":
            shared = case["shared_node_id"]
            assert sum(shared in ways[way_id]["node_refs"] for way_id in way_ids) == 2
        if case_name == "geometric_crossing_without_shared_node":
            first, second = (ways[way_id] for way_id in way_ids)
            first_line = LineString([(nodes[node_id]["lon"], nodes[node_id]["lat"]) for node_id in first["node_refs"]])
            second_line = LineString([(nodes[node_id]["lon"], nodes[node_id]["lat"]) for node_id in second["node_refs"]])
            assert first_line.crosses(second_line)
            assert not set(first["node_refs"]) & set(second["node_refs"])


def _assert_graph_matches_fixture(
    fixture: dict[str, Any],
    nodes: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    arcs: list[dict[str, Any]],
) -> None:
    expected_pairs = _literal_segment_map(fixture)
    expected_candidates = _expected_candidate_map(fixture)
    actual_pairs = {row["candidate_id"]: (row["from_node_id"], row["to_node_id"]) for row in segments}
    assert actual_pairs == expected_pairs, "Graph segment endpoints differ from literal ordered source references"
    actual_results = {row["candidate_id"]: (row["eligibility"], row["direction"]) for row in segments}
    assert actual_results == expected_candidates, "Graph included, excluded, or unknown candidate differs from accepted fixture expectation"

    expected_arcs: dict[str, tuple[str, str, str]] = {}
    for candidate_id, (status, direction) in expected_candidates.items():
        if status != "include":
            continue
        left, right = expected_pairs[candidate_id]
        if direction in {"both", "forward"}:
            expected_arcs[f"{candidate_id}/forward"] = (candidate_id, left, right)
        if direction in {"both", "reverse"}:
            expected_arcs[f"{candidate_id}/reverse"] = (candidate_id, right, left)
    actual_arcs = {
        row["edge_id"]: (row["candidate_id"], row["from_node_id"], row["to_node_id"])
        for row in arcs
    }
    assert actual_arcs == expected_arcs, "Graph arcs differ from literal source identity and direction expectations"
    expected_nodes = {
        endpoint
        for candidate_id, pair in expected_pairs.items()
        if expected_candidates[candidate_id][0] == "include"
        for endpoint in pair
    }
    assert {row["node_id"] for row in nodes} == expected_nodes

    for case_name, case in fixture["topology_cases"].items():
        selected_ways = set(case["way_ids"])
        selected_arcs = [row for row in arcs if row["way_id"] in selected_ways]
        observed = _components([(row["from_node_id"], row["to_node_id"]) for row in selected_arcs])
        assert observed == case["expected_components"], case_name


def test_accepted_reference_loader_rejects_changed_or_draft_inputs(tmp_path: Path) -> None:
    load_accepted_references()
    changed_fixture = tmp_path / "changed-reference.json"
    changed_fixture.write_bytes(METRIC_REFERENCES.read_bytes())
    payload = json.loads(changed_fixture.read_text(encoding="utf-8"))
    payload["status"] = "proposed_requires_owner_acceptance"
    changed_fixture.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="do not match accepted manifest"):
        load_accepted_references({"pipeline/fixtures/routing-references-v1.json": changed_fixture})


def test_metric_reference_fixture_is_structurally_self_consistent() -> None:
    _, fixture, settings = load_accepted_references()
    cases = fixture["cases"]
    assert len(cases) == 21
    assert settings["time_budget_seconds"] == 600
    assert math.isclose(float(settings["speed_mph"]), 4500 / 1609.344, rel_tol=0, abs_tol=1e-15)
    assert settings["origins"][0]["source_node_id"] == "7581419196"
    assert settings["origins"][0]["station_entrance_status"] == "not_verified"
    assert settings["origins"][0]["execution_status"] == "authorized_for_task_4_3_diagnostic_only"
    edge_experiment = settings["edge_origin_experiment"]
    assert edge_experiment["maximum_snap_distance_ft"] == 100
    assert edge_experiment["access_cost_model"] == "geodesic_distance_at_base_walking_speed"
    assert edge_experiment["tie_distance_ft"] == 0.01
    assert edge_experiment["tie_behavior"] == "ambiguous_origin_requires_explicit_candidate"
    assert edge_experiment["allowed_candidates"] == "included_only"
    assert edge_experiment["implementation_status"] == "authorized_for_task_4_3_not_implemented"

    ids = [case["id"] for case in cases]
    expected_ids = {
        "F01", "F02", "F03", "F04", "F05", "F06", "F06-alternative",
        "F07", "F07-alternative", "F08", "F09", "F10", "F11", "F12",
        "F13", "F14", "F15", "F15-alternative", "F16", "F17", "F17-alternative",
    }
    assert len(ids) == len(set(ids)) and set(ids) == expected_ids
    for case in cases:
        edge_ids = [edge["id"] for edge in case["edges"]]
        assert len(edge_ids) == len(set(edge_ids)), case["id"]
        edge_lengths = {}
        for edge in case["edges"]:
            length = edge["length_ft"]
            assert isinstance(length, (int, float)) and not isinstance(length, bool) and math.isfinite(length) and length > 0
            assert edge["direction"] in {"both", "forward", "reverse"}
            edge_lengths[edge["id"]] = float(length)
        intervals_by_edge = case["expected_intervals_ft"]
        if intervals_by_edge is None:
            assert case["expected_status"] == "no_network"
            assert case["expected_unique_source_length_ft"] is None
            assert case["expected_node_distances_ft"] is None
            continue
        covered = 0.0
        for edge_id, intervals in intervals_by_edge.items():
            assert edge_id in edge_lengths
            last_end = -math.inf
            for start, end in intervals:
                assert 0 <= start < end <= edge_lengths[edge_id]
                assert start >= last_end
                last_end = end
                covered += end - start
        assert math.isclose(covered, case["expected_unique_source_length_ft"], rel_tol=0, abs_tol=1e-8)
        for node, distance in case["expected_node_distances_ft"].items():
            assert isinstance(node, str) and 0 <= distance <= case["budget_distance_equivalent_ft"]


def test_literal_source_fixture_runs_through_extractor_classifier_and_graph(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    load_accepted_references()
    fixture = json.loads(SOURCE_CASES.read_text(encoding="utf-8"))
    assert fixture["version"] == "routing-source-fixtures-1" and fixture["status"] == "task_4_2_structural_fixture"
    _assert_literal_source_topology(fixture)

    pbf = tmp_path / "routing-reference-source.osm.pbf"
    _write_source_pbf(pbf, fixture["nodes"], fixture["ways"])
    config_path, inventory_path, inventory_report_path = _prepare_inputs(tmp_path, pbf)
    extract_code, extraction_result = _invoke_extract(config_path, inventory_path, inventory_report_path, capsys)
    assert extract_code == 0 and extraction_result["status"] == "pass", extraction_result
    extraction = ROOT / extraction_result["output_directory"]
    extraction_report = json.loads((extraction / "run-report.json").read_text(encoding="utf-8"))
    assert all(extraction_report["checks"].values())

    source_nodes = {row["osm_id"]: row for row in _read_rows(extraction / "nodes.jsonl")}
    expected_nodes = {
        row["id"]: {"osm_id": row["id"], "lon": row["lon"], "lat": row["lat"], "tags": row["tags"]}
        for row in fixture["nodes"]
    }
    assert source_nodes == expected_nodes
    source_ways = {row["osm_id"]: row for row in _read_rows(extraction / "ways.jsonl")}
    expected_ways = {
        row["id"]: {"osm_id": row["id"], "node_refs": row["node_refs"], "tags": row["tags"]}
        for row in fixture["ways"]
    }
    assert source_ways == expected_ways

    classification_code, classification_result = run_classification(
        extraction,
        POLICY_CONFIG,
        tmp_path / "classified",
        staging_root=tmp_path / "classification-staging",
    )
    assert classification_code == 0, classification_result
    classification = ROOT / classification_result["run_report"].rsplit("/", 1)[0]
    classified_nodes = {
        row["source"]["osm_id"]: row for row in _read_rows(classification / "nodes-classified.jsonl")
    }
    policy_cases = fixture["policy_cases"]
    assert classified_nodes[policy_cases["wall_node_id"]]["evaluation"]["disposition"] == "block"
    assert classified_nodes[policy_cases["kerb_node_id"]]["evaluation"]["disposition"] == "pass"
    assert classified_nodes[policy_cases["gate_node_id"]]["evaluation"]["disposition"] == "unknown"

    stage = tmp_path / "graph-stage"
    report = build_graph(extraction, classification, POLICY_CONFIG, stage)
    assert report["status"] == "incomplete_unknown_policy"
    assert report["analytical_promotion"] == "blocked"
    assert all(report["checks"].values())
    validated_counts = validate_graph(stage, load_pedestrian_settings(POLICY_CONFIG).speed_mph)
    assert validated_counts == {key: value for key, value in report["counts"].items() if key != "duplicate_geometry_candidates"}
    _inspect_gpkg(stage, write=False)

    graph_nodes = _read_rows(stage / "nodes.jsonl")
    graph_segments = _read_rows(stage / "segments.jsonl")
    graph_arcs = _read_rows(stage / "arcs.jsonl")
    _assert_graph_matches_fixture(fixture, graph_nodes, graph_segments, graph_arcs)
    # Exercise traversal through the actual PBF -> canonical -> policy -> graph
    # chain, with an independent closed-form WGS84 equatorial reference.
    from flm_pipeline.routing import Origin, Readiness, traverse
    from flm_pipeline.routing_adapter import load_graph
    (stage / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
    routing_segments, coordinates, readiness, reopened = load_graph(stage)
    assert readiness.policy_blockers and readiness.coverage == "not_established"
    assert reopened["implementation_identity"] == report["implementation_identity"]
    equatorial_ft = (6378137 * math.pi / 180 * 0.001) / 0.3048
    unit_seconds = 0.24384
    routed = traverse(routing_segments, Origin(node="1001"), equatorial_ft * 1.5 * unit_seconds,
                      unit_seconds, readiness)
    assert routed.computation_status == "incomplete"
    assert set(routed.node_seconds) == {"1001", "1002"}
    assert routed.node_seconds["1002"] == pytest.approx(equatorial_ft * unit_seconds, abs=1e-6)
    assert routed.unique_source_length_ft == pytest.approx(equatorial_ft * 1.5, abs=1e-6)
    assert routed.intervals_ft["way/1101/segment/1"][0] == pytest.approx((0, equatorial_ft / 2), abs=1e-6)
    for source, reachable in (("1301", {"1301", "1302"}), ("1302", {"1302"}),
                              ("1401", {"1401"}), ("1402", {"1401", "1402"}),
                              ("1501", {"1501", "1502"})):
        result = traverse(routing_segments, Origin(node=source), equatorial_ft * 3 * unit_seconds,
                          unit_seconds, Readiness(coverage="synthetic_closed"))
        assert set(result.node_seconds) == reachable
    # Frozen graph corruption fails before it can become a traversal result.
    nodes_path = stage / "nodes.jsonl"
    saved = nodes_path.read_bytes()
    nodes_path.write_bytes(saved + b"\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_graph(stage)
    nodes_path.write_bytes(saved)
    segments = {row["candidate_id"]: row for row in graph_segments}
    policy_cases = fixture["policy_cases"]
    assert "G_ZERO_LENGTH" in segments[policy_cases["distinct_id_zero_length_candidate_id"]]["reason_codes"]
    assert "G_ZERO_LENGTH" in segments[policy_cases["same_id_zero_length_candidate_id"]]["reason_codes"]
    assert segments[f"way/{policy_cases['private_way_id']}/segment/0"]["eligibility"] == "exclude"
    assert segments["way/2411/segment/0"]["eligibility"] == "unknown"
    assert segments["way/2311/segment/0"]["eligibility"] == "include"
    assert any(row["way_id"] == "1712" for row in graph_arcs)

    equatorial_segment = segments["way/1101/segment/0"]
    expected_feet = (6378137 * math.pi / 180 * 0.001) / 0.3048
    assert math.isclose(equatorial_segment["length_ft"], expected_feet, rel_tol=0, abs_tol=1e-6)
    assert math.isclose(equatorial_segment["base_seconds"], expected_feet * 0.24384, rel_tol=0, abs_tol=1e-9)
    assert segments["way/2611/segment/0"]["to_node_id"] == policy_cases["large_id"]

    # Temporary in-memory faults exercise the independent acceptance assertions.
    false_junction_segments = deepcopy(graph_segments)
    next(row for row in false_junction_segments if row["candidate_id"] == "way/1911/segment/0")["to_node_id"] = "1907"
    with pytest.raises(AssertionError, match="literal ordered source references"):
        _assert_graph_matches_fixture(fixture, graph_nodes, false_junction_segments, graph_arcs)

    forbidden_edge_segments = deepcopy(graph_segments)
    next(row for row in forbidden_edge_segments if row["candidate_id"] == "way/2211/segment/0").update(eligibility="include", direction="both")
    with pytest.raises(AssertionError, match="candidate differs"):
        _assert_graph_matches_fixture(fixture, graph_nodes, forbidden_edge_segments, graph_arcs)

    # The original output remains intact and passes after both temporary faults are discarded.
    _assert_graph_matches_fixture(fixture, graph_nodes, graph_segments, graph_arcs)


@pytest.mark.parametrize("case_name,expected_error", [
    ("missing_node_reference", "unresolved"),
    ("duplicate_node_id", "Duplicate node identity"),
])
def test_malformed_pbf_source_fails_extraction(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case_name: str, expected_error: str
) -> None:
    fixture = json.loads(SOURCE_CASES.read_text(encoding="utf-8"))
    malformed = fixture["malformed_source_cases"][case_name]
    pbf = tmp_path / f"{case_name}.osm.pbf"
    _write_source_pbf(pbf, malformed["nodes"], malformed.get("ways", []))
    config_path, inventory_path, inventory_report_path = _prepare_inputs(tmp_path, pbf)
    code, result = _invoke_extract(config_path, inventory_path, inventory_report_path, capsys)
    assert code == 1 and result["status"] == "fail", result
    assert expected_error.casefold() in json.dumps(result).casefold()


def test_nonfinite_decoded_coordinate_fails_extractor_validation() -> None:
    class NonfiniteLocation:
        @staticmethod
        def valid() -> bool:
            return True

        lon = float("nan")
        lat = 0.0

    class Node:
        location = NonfiniteLocation()

    with pytest.raises(ExtractionFailure, match="Invalid coordinates"):
        _coordinates(Node(), "3301", "synthetic-nonfinite-test")

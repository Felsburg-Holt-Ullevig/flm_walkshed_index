from __future__ import annotations

import json
from pathlib import Path

import pytest

from flm_pipeline.classification import _hash_file, _json_bytes, _write_json, run_classification
from flm_pipeline.graph import GraphError, _inspect_gpkg, base_seconds, build_graph, relation_audit, run_graph, validate_graph
from test_classification import _fixture_extraction, _write_source_file


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "pipeline/config/pedestrian-policy.example.toml"
SPEED = 4500 / 1609.344


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write_rows(path, rows):
    path.write_bytes(b"".join(_json_bytes(row) + b"\n" for row in rows))


def source_fixture(tmp_path, *, empty=False, restriction=False, isolated=False, large_id=False, kerb=False):
    extraction = _fixture_extraction(tmp_path)
    xy = [(0, 0), (.001, 0), (.002, 0), (.001, 0), (.001, -.001), (.001, .001), (.003, 0), (.004, 0), (.005, 0), (.002, 0)]
    nodes = [{"osm_id": str(i), "lon": lon, "lat": lat, "tags": {}} for i, (lon, lat) in enumerate(xy, 1)]
    nodes[6]["tags"] = {"barrier": "wall"}
    nodes[7]["tags"] = {"barrier": "gate"}
    if kerb:
        nodes[1]["tags"] = {"barrier": "kerb", "kerb": "raised", "wheelchair": "no"}
    # Shared node 2; coincident but distinct node 4 on bridge; no planar crossing links.
    specs = [
        ("10", ["1", "2", "3"], {}),
        ("11", ["5", "4", "6"], {"bridge": "yes", "layer": "1"}),
        ("12", ["1", "2"], {}),  # parallel source segment
        ("13", ["3", "9"], {"oneway:foot": "-1"}),
        ("14", ["1", "5"], {"oneway:foot": "yes"}),
        ("15", ["3", "7"], {}),  # physical barrier
        ("16", ["3", "8"], {}),  # unresolved gate
        ("17", ["3", "10"], {}),  # distinct IDs, zero geodesic length
        ("18", ["1", "1"], {}),
        ("19", ["5", "9"], {"foot": "no"}),
    ]
    ways = [{"osm_id": way, "node_refs": refs, "tags": {"highway": "residential", **tags}} for way, refs, tags in specs]
    if isolated:
        ways = [way for way in ways if way["osm_id"] != "14"]
    if large_id:
        nodes[8]["osm_id"] = "9007199254740993"
        nodes.sort(key=lambda node: int(node["osm_id"]))
        for way in ways:
            way["node_refs"] = ["9007199254740993" if ref == "9" else ref for ref in way["node_refs"]]
    relations = [{"osm_id": "30", "members": [{"type": "way", "ref": "10", "role": "from", "resolved": True}], "tags": {"type": "restriction", "restriction": "no_left_turn"}}] if restriction else []
    if empty:
        nodes, ways, relations = [], [], []
    metadata = json.loads((extraction / "extraction.json").read_text())
    metadata["files"] = {name: _write_source_file(extraction / name, rows) for name, rows in (("nodes.jsonl", nodes), ("ways.jsonl", ways), ("relations.jsonl", relations))}
    metadata["counts"].update(emitted_nodes=len(nodes), selected_ways=len(ways), emitted_relations=len(relations), unique_required_way_nodes=len({ref for way in ways for ref in way["node_refs"]}), complete_way_node_reference_total=sum(len(way["node_refs"]) for way in ways))
    _write_json(extraction / "extraction.json", metadata)
    report = json.loads((extraction / "run-report.json").read_text())
    report["output_hashes"] = {name: item["sha256"] for name, item in metadata["files"].items()}
    report["output_hashes"]["extraction.json"] = _hash_file(extraction / "extraction.json")
    _write_json(extraction / "run-report.json", report)
    code, result = run_classification(extraction, POLICY, tmp_path / "classified", staging_root=tmp_path / "stage")
    assert code == 0, result
    return extraction, ROOT / result["run_report"].rsplit("/", 1)[0]


@pytest.fixture
def built(tmp_path):
    extraction, classification = source_fixture(tmp_path, restriction=True)
    stage = tmp_path / "graph"
    report = build_graph(extraction, classification, POLICY, stage)
    return extraction, classification, stage, report


def test_topology_directions_barriers_zero_lengths_and_gis(built):
    _, _, stage, report = built
    arcs = {row["edge_id"]: row for row in read_rows(stage / "arcs.jsonl")}
    nodes = {row["node_id"] for row in read_rows(stage / "nodes.jsonl")}
    assert {"2", "4"} <= nodes
    assert "7" not in nodes and "8" not in nodes and "10" not in nodes
    assert "way/10/segment/0/forward" in arcs and "way/12/segment/0/forward" in arcs
    assert arcs["way/13/segment/0/reverse"]["from_node_id"] == "9"
    assert "way/13/segment/0/forward" not in arcs
    assert "way/14/segment/0/reverse" not in arcs
    assert not any(row["way_id"] in {"15", "16", "17", "18", "19"} for row in arcs.values())
    adjacency = {}
    for row in arcs.values():
        adjacency.setdefault(row["from_node_id"], set()).add(row["to_node_id"])
    reached, pending = set(), ["2"]
    while pending:
        node = pending.pop()
        if node not in reached:
            reached.add(node)
            pending.extend(adjacency.get(node, set()) - reached)
    assert reached == {"1", "2", "3", "4", "5", "6"}  # explicit 1 -> 5 connects bridge via its endpoint
    # No edge joins coincident IDs 2 and 4; connection is through source references 1 and 5.
    assert all({row["from_node_id"], row["to_node_id"]} != {"2", "4"} for row in arcs.values())
    segments = {row["way_id"]: row for row in read_rows(stage / "segments.jsonl")}
    for way in ("17", "18"):
        assert segments[way]["eligibility"] == "exclude"
        assert "G_ZERO_LENGTH" in segments[way]["reason_codes"]
        assert segments[way]["base_seconds"] is None
    assert report["counts"]["directed_arcs"] == 12
    assert report["counts"]["candidates_by_eligibility"] == {"exclude": 4, "include": 7, "unknown": 1}
    assert report["relations"]["unsupported"] == 1
    assert report["status"] == "incomplete_unknown_policy" and report["analytical_promotion"] == "blocked"
    assert all(report["checks"].values())
    _inspect_gpkg(stage, write=False)


def test_grade_crossing_and_coincident_ids_remain_disconnected_without_source_link(tmp_path):
    extraction, classification = source_fixture(tmp_path, isolated=True)
    stage = tmp_path / "graph"
    build_graph(extraction, classification, POLICY, stage)
    arcs = read_rows(stage / "arcs.jsonl")
    bridge = [a for a in arcs if a["way_id"] == "11"]
    assert {a["from_node_id"] for a in bridge} == {"4", "5", "6"}
    assert not any(a["from_node_id"] in {"1", "2", "3"} or a["to_node_id"] in {"1", "2", "3"} for a in bridge)
    assert not any((a["from_node_id"] in {"1", "2", "3"}) != (a["to_node_id"] in {"1", "2", "3"}) for a in arcs if a["way_id"] != "13")


@pytest.mark.parametrize("length,speed", [(float("nan"), SPEED), (-1, SPEED), (1, 0), (1, float("inf")), (True, SPEED)])
def test_invalid_cost_inputs_fail(length, speed):
    with pytest.raises(GraphError):
        base_seconds(length, speed)


def test_independent_cost_examples():
    assert base_seconds(328.0839895013123, SPEED) == pytest.approx(80, rel=1e-12, abs=1e-9)
    assert base_seconds(1230.3149606299212, SPEED) == pytest.approx(300, rel=1e-12, abs=1e-9)


@pytest.mark.parametrize("tags,blocked", [
    ({"type": "route"}, False), ({"type": "restriction"}, True),
    ({"type": "restriction", "except": "bicycle;foot"}, False),
    ({"type": "restriction", "except": " foot"}, True),
    ({"restriction:foot": ""}, True),
    ({"restriction:foot:conditional": "no @ (Mo-Fr)", "except": "foot"}, True),
])
def test_relation_policy_exact_foot_exemptions(tags, blocked):
    assert relation_audit({"osm_id": "1", "tags": tags, "members": []})["unsupported"] is blocked


@pytest.mark.parametrize("mutation", ["cost", "endpoint", "direction", "geometry", "extra_arc", "duplicate_node", "zero", "missing_node", "length"])
def test_structural_validator_rejects_corruption(built, mutation):
    _, _, stage, _ = built
    path = stage / "arcs.jsonl"
    rows = read_rows(path)
    if mutation == "cost":
        rows[0]["base_seconds"] = -1
    elif mutation == "endpoint":
        rows[0]["to_node_id"] = "999"
    elif mutation == "direction":
        rows[0]["direction"] = "reverse"
    elif mutation == "geometry":
        rows[0]["coordinates"].reverse()
    elif mutation == "extra_arc":
        rows.append(rows[0])
    elif mutation in {"duplicate_node", "missing_node"}:
        path = stage / "nodes.jsonl"
        rows = read_rows(path)
        rows = rows + [rows[0]] if mutation == "duplicate_node" else rows[1:]
    else:
        path = stage / "segments.jsonl"
        rows = read_rows(path)
        rows[0]["length_ft"] = 0 if mutation == "zero" else float("inf")
        if mutation == "length":
            # Noncanonical NaN/Infinity must be rejected before numeric comparisons.
            path.write_text("\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows) + "\n")
            with pytest.raises(RuntimeError):
                validate_graph(stage, SPEED)
            return
    write_rows(path, rows)
    with pytest.raises(GraphError):
        validate_graph(stage, SPEED)


def test_empty_graph_explicit_counts_and_layers(tmp_path):
    extraction, classification = source_fixture(tmp_path, empty=True)
    stage = tmp_path / "graph"
    report = build_graph(extraction, classification, POLICY, stage)
    assert report["counts"]["directed_arcs"] == report["counts"]["nodes"] == 0
    assert report["status"] == "empty"
    assert report["analytical_promotion"] == "blocked_empty"
    _inspect_gpkg(stage, write=False)


def test_stale_or_corrupt_classification_rejected(tmp_path):
    extraction, classification = source_fixture(tmp_path)
    report_path = classification / "run-report.json"
    report = json.loads(report_path.read_text())
    report["implementation_identity"]["sha256"] = "0" * 64
    _write_json(report_path, report)
    with pytest.raises(GraphError, match="stale"):
        build_graph(extraction, classification, POLICY, tmp_path / "stale")


def test_repeat_semantics_and_supervised_cli(tmp_path):
    extraction, classification = source_fixture(tmp_path)
    stage = tmp_path / "direct"
    report = build_graph(extraction, classification, POLICY, stage)
    code, result = run_graph(extraction, classification, POLICY, tmp_path / "supervised")
    assert code == 0, result
    other = ROOT / result["run_report"]
    reopened = json.loads(other.read_text())
    assert reopened["supervision"]["child_cleanup_complete"]
    for name in ("arcs.jsonl", "nodes.jsonl", "segments.jsonl", "relations-audit.jsonl"):
        assert _hash_file(stage / name) == _hash_file(other.parent / name) == report["output_files"][name]["sha256"]


def test_gis_corruption_is_rejected(built):
    import pyogrio
    _, _, stage, _ = built
    frame = pyogrio.read_dataframe(stage / "routing.gpkg", layer="routing_arcs")
    frame.loc[0, "base_seconds"] = -1
    pyogrio.write_dataframe(frame, stage / "routing.gpkg", layer="routing_arcs", driver="GPKG")
    with pytest.raises(GraphError, match="GIS field mismatch"):
        _inspect_gpkg(stage, write=False)


def test_classification_candidate_replay_rejects_forged_eligibility(tmp_path):
    extraction, classification = source_fixture(tmp_path)
    candidate_path = classification / "candidates-classified.jsonl"
    rows = read_rows(candidate_path)
    rows[0]["eligibility"] = "exclude"
    write_rows(candidate_path, rows)
    report_path = classification / "run-report.json"
    report = json.loads(report_path.read_text())
    report["output_files"][candidate_path.name].update(sha256=_hash_file(candidate_path), bytes=candidate_path.stat().st_size)
    _write_json(report_path, report)
    with pytest.raises(GraphError, match="disagrees with source"):
        build_graph(extraction, classification, POLICY, tmp_path / "forged")


def test_failed_worker_never_promotes(tmp_path, monkeypatch):
    import flm_pipeline.cli as cli
    monkeypatch.setattr(cli, "_supervise", lambda *args: {"exit_code": 1, "failure_reason": "stage exceeded 1200 seconds"})
    output = tmp_path / "output"
    code, report = run_graph(tmp_path, tmp_path, POLICY, output)
    assert code == 1 and not output.exists()
    assert Path(report["staging_directory"], "run-report.json").exists()


def test_raw_destination_rejected(tmp_path):
    with pytest.raises(GraphError, match="outside data/raw"):
        run_graph(tmp_path, tmp_path, POLICY, ROOT / "data/raw/graph")


def test_large_string_ids_survive_jsonl_and_gis(tmp_path):
    import pyogrio
    extraction, classification = source_fixture(tmp_path, large_id=True)
    stage = tmp_path / "large"
    build_graph(extraction, classification, POLICY, stage)
    frame = pyogrio.read_dataframe(stage / "routing.gpkg", layer="routing_nodes")
    assert "9007199254740993" in set(frame["node_id"])
    assert all(isinstance(value, str) for value in frame["node_id"])


def test_kerb_preserves_shared_junction_and_incident_segments(tmp_path):
    extraction, classification = source_fixture(tmp_path, kerb=True)
    stage = tmp_path / "kerb-graph"
    report = build_graph(extraction, classification, POLICY, stage)
    assert report["counts"]["directed_arcs"] == 12
    arcs = read_rows(stage / "arcs.jsonl")
    assert {a["to_node_id"] for a in arcs if a["from_node_id"] == "2"} == {"1", "3"}
    assert all(a["from_node_id"] != "4" for a in arcs if a["way_id"] == "10")
    candidates = read_rows(stage / "segments.jsonl")
    assert all("B_KERB_PASS" in s["reason_codes"] for s in candidates if "2" in {s["from_node_id"], s["to_node_id"]})

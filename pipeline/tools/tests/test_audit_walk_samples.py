"""Synthetic source-boundary and serialized-tile audits."""
import json
import math
from pathlib import Path
import sys

import pytest
from pyproj import Geod

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "pipeline" / "tools"))
from audit_walk_samples import SampleAuditError, _all_checks_pass, _summary, _validate_case_ids, audit_source_graph, measure_tile_sizes  # noqa: E402

sys.path.insert(0, str(ROOT / "pipeline" / "src"))
from flm_pipeline.walk_tiles import build_from_records, verify_records  # noqa: E402

GEOD = Geod(ellps="WGS84")
BBOX = [10.0, 10.0, 10.01, 10.01]


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def _fixture(tmp_path):
    extraction, graph, tiles = (tmp_path / name for name in ("extraction", "graph", "tiles"))
    extraction.mkdir(); graph.mkdir()
    source_nodes = [
        {"osm_id": "1", "lon": 10.005, "lat": 10.005, "tags": {}},
        {"osm_id": "2", "lon": 10.015, "lat": 10.005, "tags": {}},
        {"osm_id": "3", "lon": 10.025, "lat": 10.005, "tags": {}},
    ]
    source_way = {"osm_id": "10", "node_refs": ["1", "2", "3"], "tags": {"highway": "residential", "name": "Audit Way"}}
    _write_jsonl(extraction / "nodes.jsonl", source_nodes)
    _write_jsonl(extraction / "ways.jsonl", [source_way])
    coords = [[10.005, 10.005], [10.015, 10.005], [10.025, 10.005]]
    graph_segments = []
    tile_segments = []
    for sequence, direction in enumerate(("both", "reverse")):
        points = coords[sequence:sequence + 2]
        length = GEOD.inv(*points[0], *points[1])[2] / 0.3048
        row = {
            "candidate_id": f"way/10/segment/{sequence}", "way_id": "10", "sequence": sequence,
            "from_node_id": str(sequence + 1), "to_node_id": str(sequence + 2),
            "coordinates": points, "length_ft": length, "eligibility": "include", "direction": direction,
            "base_seconds": length * 3600 / (2.8 * 5280),
        }
        graph_segments.append(row)
        tile_segments.append({key: row[key] for key in (
            "candidate_id", "way_id", "sequence", "from_node_id", "to_node_id", "direction", "length_ft", "coordinates")})
    graph_nodes = [
        {"node_id": node_id, "lon": source_nodes[int(node_id) - 1]["lon"], "lat": source_nodes[int(node_id) - 1]["lat"]}
        for node_id in ("1", "2", "3")
    ]
    graph_arcs = []
    for row in graph_segments:
        for direction in ("forward", "reverse"):
            if row["direction"] not in {"both", direction}:
                continue
            reverse = direction == "reverse"
            graph_arcs.append({
                "edge_id": row["candidate_id"] + "/" + direction,
                "candidate_id": row["candidate_id"], "way_id": row["way_id"], "sequence": row["sequence"],
                "direction": direction,
                "from_node_id": row["to_node_id"] if reverse else row["from_node_id"],
                "to_node_id": row["from_node_id"] if reverse else row["to_node_id"],
                "coordinates": list(reversed(row["coordinates"])) if reverse else row["coordinates"],
                "length_ft": row["length_ft"], "base_seconds": row["base_seconds"],
            })
    _write_jsonl(graph / "segments.jsonl", graph_segments)
    _write_jsonl(graph / "nodes.jsonl", graph_nodes)
    _write_jsonl(graph / "arcs.jsonl", graph_arcs)
    nodes = [{"node_id": str(i), "coordinate": coords[i - 1]} for i in (1, 2, 3)]
    ways = {"10": source_way}
    manifest = build_from_records(
        tile_segments, nodes, graph_arcs, ways,
        source_release_id="osm-test", excluded_count=0, unknown_count=0,
        output_dir=tiles, release_id="audit-test")
    return extraction, graph, tiles, manifest


def test_audit_reconciles_whole_ways_and_counts_boundary_segments(tmp_path):
    extraction, graph, tiles, manifest = _fixture(tmp_path)

    segments, nodes, arcs, ways, counts, lengths = audit_source_graph(extraction, graph, BBOX)
    verified = verify_records(segments, nodes, arcs, ways, tiles, manifest)

    assert counts["source_ways"] == 1
    assert counts["source_candidates"] == counts["included_segments"] == 2
    assert counts["included_segments_crossing_bbox"] == 1
    assert counts["included_segments_outside_bbox"] == 1
    assert counts["included_segments_inside_bbox"] == 0
    assert counts["directed_arcs"] == 3
    assert lengths["graph_recorded"]["include"] == math.fsum(row["length_ft"] for row in segments)
    assert counts["source_ways_with_node_inside_bbox"] == 1
    assert lengths["maximum_absolute_segment_difference_ft"] < 1e-9
    assert verified["unique_segments"] == 2


def test_audit_rejects_source_length_or_candidate_set_mismatch(tmp_path):
    extraction, graph, _, _ = _fixture(tmp_path)
    rows = [json.loads(line) for line in (graph / "segments.jsonl").read_text().splitlines()]
    rows[0]["length_ft"] += 0.01
    _write_jsonl(graph / "segments.jsonl", rows)
    with pytest.raises(SampleAuditError, match="length_ft"):
        audit_source_graph(extraction, graph, BBOX)


def test_audit_rejects_a_missing_whole_way_segment(tmp_path):
    extraction, graph, _, _ = _fixture(tmp_path)
    rows = [json.loads(line) for line in (graph / "segments.jsonl").read_text().splitlines()]
    _write_jsonl(graph / "segments.jsonl", rows[:1])
    with pytest.raises(SampleAuditError, match="candidate set"):
        audit_source_graph(extraction, graph, BBOX)


def test_audit_rejects_way_without_node_in_written_bbox(tmp_path):
    extraction, graph, _, _ = _fixture(tmp_path)
    with pytest.raises(SampleAuditError, match="no node inside"):
        audit_source_graph(extraction, graph, [11.0, 10.0, 11.01, 10.01])


def test_audit_checks_graph_base_seconds_against_exact_speed(tmp_path):
    extraction, graph, _, _ = _fixture(tmp_path)
    rows = [json.loads(line) for line in (graph / "segments.jsonl").read_text().splitlines()]
    rows[0]["base_seconds"] += 1
    _write_jsonl(graph / "segments.jsonl", rows)
    with pytest.raises(SampleAuditError, match="base_seconds"):
        audit_source_graph(extraction, graph, BBOX)


def test_tile_size_summary_measures_manifest_and_deterministic_file_gzip(tmp_path):
    _, _, tiles, manifest = _fixture(tmp_path)

    sizes = measure_tile_sizes(tiles)
    assert sizes["tile_count"] == len(manifest["tiles"])
    assert sizes["manifest_bytes"] == (tiles / "manifest.json").stat().st_size
    assert sizes["network_files"]["total_bytes"] == sum((tiles / entry["path"]).stat().st_size for entry in manifest["tiles"])
    assert sizes["per_file_gzip"]["total_bytes"] > 0
    assert sizes["individually_gzipped_payload_bytes_estimate"] == sizes["manifest_gzip_bytes"] + sizes["per_file_gzip"]["total_bytes"]
    assert sizes["largest_tiles"] == sorted(sizes["largest_tiles"], key=lambda row: (-row["bytes"], row["path"]))


def test_network_files_must_match_manifest(tmp_path):
    _, _, tiles, _ = _fixture(tmp_path)
    (tiles / "network" / "extra.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SampleAuditError, match="network files differ"):
        measure_tile_sizes(tiles)


def test_nearest_rank_p95_summary():
    result = _summary(list(range(1, 21)))
    assert result["total_bytes"] == 210
    assert result["median_bytes"] == 10.5
    assert result["p95_nearest_rank_bytes"] == 19


def test_report_checks_must_all_pass():
    assert _all_checks_pass({"checks": {"source": True, "tiles": True}}, "fixture") == 2
    with pytest.raises(SampleAuditError, match="checks failed"):
        _all_checks_pass({"checks": {"source": True, "tiles": False}}, "fixture")


def test_sample_index_must_have_exactly_three_approved_cases():
    _validate_case_ids({case: {} for case in ("G01", "B01", "F01")})
    with pytest.raises(SampleAuditError, match="exactly G01"):
        _validate_case_ids({"G01": {}, "B01": {}})

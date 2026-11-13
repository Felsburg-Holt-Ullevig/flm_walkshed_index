"""Synthetic checks for regional sample bounds and source-preserving selection."""
import json

import pytest

from flm_pipeline.walk_samples import WalkSampleError, build_sample_records, sample_bbox


@pytest.mark.parametrize("origin", [(-104.6928167, 40.4249), (-105.06877, 39.91758), (-105.81945, 39.94776)])
def test_sample_bbox_covers_at_least_approved_margin(origin):
    bbox, minimum = sample_bbox(origin)
    assert len(bbox) == 4
    assert bbox[0] < origin[0] < bbox[2]
    assert bbox[1] < origin[1] < bbox[3]
    assert minimum >= 5000


def test_sample_bbox_rejects_invalid_origin():
    with pytest.raises(WalkSampleError):
        sample_bbox((float("nan"), 40))


def _jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_selects_complete_touched_ways_and_keeps_dispositions(tmp_path):
    extraction = tmp_path / "extraction"
    graph = tmp_path / "graph"
    extraction.mkdir()
    graph.mkdir()
    nodes = [
        {"osm_id": "1", "lon": -105.01, "lat": 40, "tags": {}},
        {"osm_id": "2", "lon": -104.99, "lat": 40, "tags": {}},
        {"osm_id": "3", "lon": -104.98, "lat": 40, "tags": {}},
        {"osm_id": "4", "lon": -105.2, "lat": 40, "tags": {}},
        {"osm_id": "5", "lon": -105.19, "lat": 40, "tags": {}},
    ]
    ways = [
        {"osm_id": "10", "node_refs": ["1", "2", "3"], "tags": {"highway": "residential", "name": "Main"}},
        {"osm_id": "11", "node_refs": ["4", "5"], "tags": {"highway": "service"}},
    ]
    _jsonl(extraction / "nodes.jsonl", nodes)
    _jsonl(extraction / "ways.jsonl", ways)
    coordinates = [[-105.01, 40], [-104.99, 40]]
    first = {"candidate_id": "way/10/segment/0", "way_id": "10", "sequence": 0,
             "from_node_id": "1", "to_node_id": "2", "direction": "both", "length_ft": 100,
             "coordinates": coordinates, "eligibility": "include"}
    second = {"candidate_id": "way/10/segment/1", "way_id": "10", "sequence": 1,
              "from_node_id": "2", "to_node_id": "3", "direction": "forward", "length_ft": 100,
              "coordinates": [[-104.99, 40], [-104.98, 40]], "eligibility": "unknown"}
    _jsonl(graph / "segments.jsonl", [first, second])
    arcs = [
        {"candidate_id": first["candidate_id"], "edge_id": first["candidate_id"] + "/forward", "direction": "forward", "from_node_id": "1", "to_node_id": "2"},
        {"candidate_id": first["candidate_id"], "edge_id": first["candidate_id"] + "/reverse", "direction": "reverse", "from_node_id": "2", "to_node_id": "1"},
    ]
    _jsonl(graph / "arcs.jsonl", arcs)
    selected, selected_nodes, selected_arcs, selected_ways, counts = build_sample_records(
        graph, extraction, (-105.02, 39.99, -104.97, 40.01))
    assert [row["candidate_id"] for row in selected] == [first["candidate_id"]]
    assert {row["node_id"] for row in selected_nodes} == {"1", "2"}
    assert len(selected_arcs) == 2
    assert set(selected_ways) == {"10"}
    assert counts["excluded_segments"] == 0
    assert counts["unknown_segments"] == 1


def test_missing_source_node_is_rejected(tmp_path):
    extraction = tmp_path / "extraction"
    graph = tmp_path / "graph"
    extraction.mkdir(); graph.mkdir()
    _jsonl(extraction / "nodes.jsonl", [])
    _jsonl(extraction / "ways.jsonl", [{"osm_id": "1", "node_refs": ["missing"], "tags": {}}])
    _jsonl(graph / "segments.jsonl", [])
    _jsonl(graph / "arcs.jsonl", [])
    with pytest.raises(WalkSampleError, match="missing source node"):
        build_sample_records(graph, extraction, (-106, 39, -104, 41))

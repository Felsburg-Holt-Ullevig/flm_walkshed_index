"""Disk reconstruction and inspection-export checks for Step 3."""
import json
import hashlib

import pytest

from flm_pipeline.walk_tiles import build_from_records, WalkTilesError
from flm_pipeline.walk_reference_output import CASES, BUDGETS, load_network, _write_gpkg


def fixture(tmp_path):
    tile_dir = tmp_path / "tiles"
    graph = tmp_path / "graph"
    extraction = tmp_path / "extract"
    graph.mkdir(); extraction.mkdir()
    segment = {"candidate_id": "way/1/segment/0", "way_id": "1", "sequence": 0,
        "from_node_id": "a", "to_node_id": "b", "coordinates": [[-105.001, 39.75], [-104.999, 39.75]],
        "length_ft": 600, "direction": "both", "eligibility": "include"}
    nodes = [{"node_id": "a", "coordinate": segment["coordinates"][0]}, {"node_id": "b", "coordinate": segment["coordinates"][1]}]
    arcs = [{"edge_id": "f", "candidate_id": segment["candidate_id"], "direction": "forward", "from_node_id": "a", "to_node_id": "b"},
            {"edge_id": "r", "candidate_id": segment["candidate_id"], "direction": "reverse", "from_node_id": "b", "to_node_id": "a"}]
    way = {"osm_id": "1", "node_refs": ["a", "b"], "tags": {"highway": "footway"}}
    build_from_records([segment], nodes, arcs, {"1": way}, source_release_id="synthetic", excluded_count=0,
                       unknown_count=0, output_dir=tile_dir, release_id="synthetic")
    def jsonl(path, rows):
        path.write_text("".join(json.dumps(r)+"\n" for r in rows), encoding="utf-8")
    jsonl(graph / "segments.jsonl", [segment])
    jsonl(graph / "nodes.jsonl", [{"node_id": n["node_id"], "lon": n["coordinate"][0], "lat": n["coordinate"][1]} for n in nodes])
    jsonl(graph / "arcs.jsonl", arcs)
    (graph / "routing.gpkg").write_bytes(b"synthetic-placeholder-not-a-gis-validation")
    def file_metadata(path):
        return {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (graph / "run-report.json").write_text(json.dumps({"report_version": "experimental-routing-graph-1",
        "coverage": {"extract_bbox": [-105.01, 39.74, -104.99, 39.76]}, "checks": {"synthetic": True},
        "output_files": {path.name: file_metadata(path) for path in graph.iterdir()}}))
    jsonl(extraction / "ways.jsonl", [way])
    jsonl(extraction / "nodes.jsonl", [])
    jsonl(extraction / "relations.jsonl", [])
    (extraction / "extraction.json").write_text(json.dumps({
        "files": {path.name: file_metadata(path) for path in extraction.iterdir()}}))
    return tile_dir, graph, extraction


def test_approved_points_and_exact_imperial_budgets():
    assert [c[0] for c in CASES] == ["D01", "G01", "B01", "C01", "F01", "D02"]
    assert CASES[0][2] == (-105.0004685, 39.7529095)
    assert CASES[-1][2] == (-105.049, 39.748)
    assert BUDGETS == ((5, 1232), (10, 2464), (15, 3696))


def test_load_network_reconstructs_source_identity_and_whole_boundary_segments(tmp_path):
    tiles, graph, extract = fixture(tmp_path)
    network = load_network(tiles, graph_directory=graph, extraction_directory=extract)
    assert network["segments"] == network["source_segments"]
    assert network["verification"]["length_difference_ft"] == 0
    assert network["verification"]["unique_segments"] == 1
    assert network["verification"]["tile_count"] == 4  # longitude edge and exact latitude edge


def test_load_network_rejects_tile_corruption(tmp_path):
    tiles, graph, extract = fixture(tmp_path)
    file = next((tiles / "network").glob("*.json"))
    payload = json.loads(file.read_text())
    payload["segments"][0]["len_ft"] = 601
    file.write_text(json.dumps(payload))
    with pytest.raises(WalkTilesError):
        load_network(tiles, graph_directory=graph, extraction_directory=extract)


def test_load_network_rejects_changed_source_bytes(tmp_path):
    tiles, graph, extract = fixture(tmp_path)
    source = graph / "segments.jsonl"
    source.write_text(source.read_text()+"\n")
    with pytest.raises(ValueError, match="source graph file changed"):
        load_network(tiles, graph_directory=graph, extraction_directory=extract)


def test_reference_refuses_existing_destination_before_loading_inputs(tmp_path):
    from flm_pipeline.walk_reference_output import run_reference
    output = tmp_path / "existing"
    output.mkdir()
    with pytest.raises(ValueError, match="already exists"):
        run_reference(tmp_path / "absent-index.json", output)


def test_gpkg_reopens_every_record_and_preserves_rejection_without_zero_result(tmp_path):
    tiles, graph, extract = fixture(tmp_path)
    network = load_network(tiles, graph_directory=graph, extraction_directory=extract)
    selected = {"candidate_id": "way/1/segment/0", "distance_ft": 20, "offset_ft": 100, "point": [-105.0006, 39.75]}
    cases = [{"id": "test", "name": "synthetic", "network_key": "test", "origin_lonlat": [-105.0006, 39.7501],
        "snap": {"status": "resolved", "selected": selected},
        "answers": [{"minutes": 5, "intervals_ft": {"way/1/segment/0": [[100, 300]]}}]},
        {"id": "rejected", "name": "invalid origin", "origin_lonlat": [-105, 39.76],
         "snap": {"status": "off_network", "selected": None}, "answers": []}]
    assert _write_gpkg(tmp_path / "view.gpkg", cases, {"test": network}) == {
        "origins": 2, "snaps": 1, "connectors": 1, "reached_streets": 1}


def test_gpkg_densification_uses_exact_source_interval_endpoints(tmp_path):
    import geopandas as gpd

    length = 238.63392127293903
    coords = [[-105.001, 39.75], [-105.0, 39.75]]
    network = {"records": {"edge": {"coords": coords, "len_ft": length,
        "from": "a", "to": "b", "dir": "both"}}}
    case = {"id": "endpoint", "name": "upper endpoint", "network_key": "test",
        "origin_lonlat": [-105.0005, 39.7501],
        "snap": {"status": "resolved", "selected": {"candidate_id": "edge", "distance_ft": 10,
            "offset_ft": 0, "point": coords[0]}},
        "answers": [{"minutes": 5, "intervals_ft": {"edge": [[0, length]]}}]}
    output = tmp_path / "endpoint.gpkg"
    _write_gpkg(output, [case], {"test": network})
    reached = gpd.read_file(output, layer="reached_streets", engine="pyogrio")
    assert reached.loc[0, "from_ft"] == 0
    assert reached.loc[0, "to_ft"] == length
    assert list(reached.loc[0, "geometry"].coords)[-1] == tuple(coords[-1])

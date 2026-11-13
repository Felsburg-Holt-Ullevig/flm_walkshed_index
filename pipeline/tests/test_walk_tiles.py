from __future__ import annotations

"""Independent synthetic checks for the step 1–2 walk-tile builder."""

import json
import math
from pathlib import Path

import pytest

from flm_pipeline.walk_tiles import WalkTilesError, build_from_records, tiles_for_coordinates, verify_records


ROOT = Path(__file__).resolve().parents[2]


def test_single_cell_segment_has_one_explicit_cell() -> None:
    assert tiles_for_coordinates([[-105.0692065, 39.7260518], [-105.0696324, 39.7260186]]) == [
        (7493, 12972)
    ]


@pytest.mark.parametrize(
    ("coordinates", "expected"),
    [
        # A horizontal line on latitude 39.73 is included on both row edges.
        ([[-105.075, 39.73], [-105.065, 39.73]], [(7492, 12972), (7492, 12973), (7493, 12972), (7493, 12973)]),
        # A vertical line on longitude -105.07 is included on both column edges.
        ([[-105.07, 39.725], [-105.07, 39.735]], [(7492, 12972), (7492, 12973), (7493, 12972), (7493, 12973)]),
        # The endpoint at (-105.07, 39.73) touches all four closed cells.
        ([[-105.075, 39.725], [-105.07, 39.73]], [(7492, 12972), (7492, 12973), (7493, 12972), (7493, 12973)]),
        # A point-only segment at a grid corner still belongs to all four cells.
        ([[-105.07, 39.73], [-105.07, 39.73]], [(7492, 12972), (7492, 12973), (7493, 12972), (7493, 12973)]),
    ],
)
def test_closed_cell_edge_and_corner_membership(coordinates, expected) -> None:
    assert tiles_for_coordinates(coordinates) == expected


def test_diagonal_bbox_does_not_add_untouched_cells() -> None:
    # The line spans a 3-by-3 bounding box; only its diagonal and corner-touch cells intersect it.
    assert tiles_for_coordinates([[0.001, 0.001], [0.029, 0.029]]) == [
        (18000, 9000), (18000, 9001), (18001, 9000),
        (18001, 9001), (18001, 9002), (18002, 9001), (18002, 9002),
    ]


def test_negative_longitudes_and_exact_denver_grid_line() -> None:
    assert tiles_for_coordinates([[-105.082, 39.721], [-105.081, 39.722]]) == [(7491, 12972)]
    # Segment lies on longitude -105.08, a Denver sample grid line.
    assert tiles_for_coordinates([[-105.08, 39.721], [-105.08, 39.722]]) == [
        (7491, 12972), (7492, 12972)
    ]


@pytest.mark.parametrize(
    "coordinates",
    [
        [],
        [[0, 0]],
        [[0, 0], [1, 2, 3]],
        [[True, 0], [1, 2]],
        [[math.nan, 0], [1, 2]],
        [[math.inf, 0], [1, 2]],
        [[0.00000001, 0], [1, 2]],  # exceeds the source's seven-place precision
        [[181, 0], [1, 2]],
    ],
)
def test_bad_coordinates_are_rejected(coordinates) -> None:
    with pytest.raises(WalkTilesError):
        tiles_for_coordinates(coordinates)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def _build_synthetic(output: Path):
    coordinates = {
        "1": [-105.075, 39.725],
        "2": [-105.065, 39.735],
        "3": [-105.065, 39.725],
        "4": [-105.065, 39.725],  # coincident but separate source node
        "5": [-105.075, 39.735],
    }
    nodes = [{"node_id": node_id, "coordinate": xy} for node_id, xy in coordinates.items()]
    ways = {
        "10": {"osm_id": "10", "node_refs": ["1", "2", "3"], "tags": {"highway": "residential", "name": "Main", "sidewalk": "both"}},
        "11": {"osm_id": "11", "node_refs": ["1", "2"], "tags": {"highway": "path", "footway": "sidewalk"}},
        "12": {"osm_id": "12", "node_refs": ["4", "5"], "tags": {"highway": "footway", "oneway:foot": "yes"}},
        "13": {"osm_id": "13", "node_refs": ["5", "3"], "tags": {"highway": "steps", "oneway:foot": "-1"}},
    }
    # Parallel source segments 10 and 11 deliberately share their source node pair.
    segments = [
        {"candidate_id": "way/10/segment/0", "way_id": "10", "sequence": 0, "from_node_id": "1", "to_node_id": "2", "direction": "both", "length_ft": 100.25, "coordinates": [coordinates["1"], coordinates["2"]]},
        {"candidate_id": "way/11/segment/0", "way_id": "11", "sequence": 0, "from_node_id": "1", "to_node_id": "2", "direction": "both", "length_ft": 100.25, "coordinates": [coordinates["1"], coordinates["2"]]},
        {"candidate_id": "way/12/segment/0", "way_id": "12", "sequence": 0, "from_node_id": "4", "to_node_id": "5", "direction": "forward", "length_ft": 120.5, "coordinates": [coordinates["4"], coordinates["5"]]},
        {"candidate_id": "way/13/segment/0", "way_id": "13", "sequence": 0, "from_node_id": "5", "to_node_id": "3", "direction": "reverse", "length_ft": 120.5, "coordinates": [coordinates["5"], coordinates["3"]]},
    ]
    # Literal source arc expectations, including parallel links and reversed geometry direction.
    arcs = [
        {"candidate_id": "way/10/segment/0", "direction": "forward", "from_node_id": "1", "to_node_id": "2"},
        {"candidate_id": "way/10/segment/0", "direction": "reverse", "from_node_id": "2", "to_node_id": "1"},
        {"candidate_id": "way/11/segment/0", "direction": "forward", "from_node_id": "1", "to_node_id": "2"},
        {"candidate_id": "way/11/segment/0", "direction": "reverse", "from_node_id": "2", "to_node_id": "1"},
        {"candidate_id": "way/12/segment/0", "direction": "forward", "from_node_id": "4", "to_node_id": "5"},
        {"candidate_id": "way/13/segment/0", "direction": "reverse", "from_node_id": "3", "to_node_id": "5"},
    ]
    for arc in arcs:
        arc["edge_id"] = arc["candidate_id"] + "/" + arc["direction"]
    manifest = build_from_records(
        segments, nodes, arcs, ways, source_release_id="synthetic-source",
        excluded_count=0, unknown_count=0, output_dir=output,
        release_id="synthetic-walk-tiles",
    )
    return segments, nodes, arcs, ways, output, manifest


@pytest.mark.parametrize("defect", ["missing_way", "missing_highway", "nontext_tag", "bad_sequence"])
def test_invalid_source_tag_and_way_joins_are_rejected(tmp_path: Path, defect: str) -> None:
    coordinates = {"1": [-105.075, 39.725], "2": [-105.065, 39.735]}
    nodes = [{"node_id": node_id, "coordinate": xy} for node_id, xy in coordinates.items()]
    segment = {"candidate_id": "way/10/segment/0", "way_id": "10", "sequence": 0, "from_node_id": "1", "to_node_id": "2", "direction": "both", "length_ft": 50.0, "coordinates": [coordinates["1"], coordinates["2"]]}
    ways = {"10": {"osm_id": "10", "node_refs": ["1", "2"], "tags": {"highway": "path"}}}
    if defect == "missing_way":
        ways.clear()
    elif defect == "missing_highway":
        ways["10"]["tags"].pop("highway")
    elif defect == "nontext_tag":
        ways["10"]["tags"]["highway"] = 42
    else:
        segment["sequence"] = 1
    with pytest.raises(WalkTilesError):
        build_from_records([segment], nodes, [], ways, source_release_id="synthetic", excluded_count=0, unknown_count=0, output_dir=tmp_path / "tiles", release_id="synthetic")


def test_missing_endpoint_node_is_rejected_during_disk_verification(tmp_path: Path) -> None:
    segments, nodes, arcs, ways, output, manifest = _build_synthetic(tmp_path / "tiles")
    nodes = [node for node in nodes if node["node_id"] != "4"]
    with pytest.raises(WalkTilesError):
        verify_records(segments, nodes, arcs, ways, output, manifest)


def test_duplicate_source_arc_is_not_hidden_by_set_comparison(tmp_path: Path) -> None:
    segments, nodes, arcs, ways, output, manifest = _build_synthetic(tmp_path / "tiles")
    arcs.append(dict(arcs[0]))
    with pytest.raises(WalkTilesError):
        verify_records(segments, nodes, arcs, ways, output, manifest)


def test_extra_non_json_file_in_network_is_rejected(tmp_path: Path) -> None:
    segments, nodes, arcs, ways, output, manifest = _build_synthetic(tmp_path / "tiles")
    (output / "network" / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(WalkTilesError):
        verify_records(segments, nodes, arcs, ways, output, manifest)


def test_synthetic_build_and_independent_reopen_verification(tmp_path: Path) -> None:
    segments, nodes, arcs, ways, output, manifest = _build_synthetic(tmp_path / "tiles")
    report = verify_records(segments, nodes, arcs, ways, output, manifest)
    assert manifest["default_speed_mph"] == 2.8
    assert "default_speed_m_per_hour" not in manifest
    assert manifest["counts"]["included"] == 4
    assert manifest["counts"]["directed_arcs"] == 6
    assert report["unique_segments"] == 4
    assert report["directed_connections"] == 6
    tiles = {(row["col"], row["row"]): row for row in manifest["tiles"]}
    # The synthetic diagonal's grid-edge/corner cells are specified independently.
    assert (7492, 12972) in tiles
    assert (7493, 12973) in tiles
    assert sum(row["segments"] for row in manifest["tiles"]) == report["segment_copies"]


@pytest.mark.parametrize("speed_field,value", [("default_speed_mph", 2.79617), ("default_speed_m_per_hour", 4500)])
def test_manifest_rejects_unapproved_speed(tmp_path: Path, speed_field: str, value: float) -> None:
    segments, nodes, arcs, ways, output, manifest = _build_synthetic(tmp_path / "tiles")
    manifest.pop("default_speed_mph")
    manifest[speed_field] = value
    (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(WalkTilesError):
        verify_records(segments, nodes, arcs, ways, output, manifest)


@pytest.mark.parametrize("corruption", ["changed_record", "missing_tile", "extra_tile", "missed_neighbor_copy", "changed_manifest"])
def test_disk_corruption_is_detected(tmp_path: Path, corruption: str) -> None:
    segments, nodes, arcs, ways, output, manifest = _build_synthetic(tmp_path / "tiles")
    if corruption == "changed_manifest":
        disk_manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        disk_manifest["counts"]["included"] += 1
        (output / "manifest.json").write_text(json.dumps(disk_manifest), encoding="utf-8")
    elif corruption == "extra_tile":
        (output / "network" / "999_999.json").write_text('{"col":999,"row":999,"segments":[]}\n', encoding="utf-8")
    elif corruption == "missed_neighbor_copy":
        segment_id = "way/10/segment/0"
        tile = next(
            output / entry["path"]
            for entry in manifest["tiles"]
            if any(record["id"] == segment_id for record in json.loads((output / entry["path"]).read_text(encoding="utf-8"))["segments"])
        )
        payload = json.loads(tile.read_text(encoding="utf-8"))
        payload["segments"] = [record for record in payload["segments"] if record["id"] != segment_id]
        tile.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    else:
        tile = next(output / entry["path"] for entry in manifest["tiles"] if entry["segments"] > 0)
        payload = json.loads(tile.read_text(encoding="utf-8"))
        if corruption == "changed_record":
            payload["segments"][0]["len_ft"] += 1
        elif corruption == "missing_tile":
            tile.unlink()
            with pytest.raises(WalkTilesError):
                verify_records(segments, nodes, arcs, ways, output, manifest)
            return
        tile.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    with pytest.raises(WalkTilesError):
        verify_records(segments, nodes, arcs, ways, output, manifest)


def test_builder_refuses_existing_output(tmp_path: Path) -> None:
    output = tmp_path / "tiles"
    output.mkdir()
    (output / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(WalkTilesError):
        _build_synthetic(output)
    assert (output / "keep.txt").read_text(encoding="utf-8") == "keep"

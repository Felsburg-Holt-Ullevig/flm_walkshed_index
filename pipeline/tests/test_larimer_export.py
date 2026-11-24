import pytest
from pyogrio import read_dataframe
from shapely.geometry import LineString

from flm_pipeline.classification import _write_json
from flm_pipeline.graph import build_graph
from flm_pipeline.larimer_export import FILENAME, _verify_layer, _write_layer, export_network
from test_graph import POLICY, source_fixture


def test_export_preserves_one_line_per_segment_and_distinct_endpoint_ids(tmp_path):
    extraction, classified = source_fixture(tmp_path, isolated=True, large_id=True)
    graph_dir = tmp_path / "graph"
    graph = build_graph(extraction, classified, POLICY, graph_dir)
    graph_report = graph_dir / "run-report.json"
    _write_json(graph_report, graph)
    destination = tmp_path / "export"
    example = "way/10/segment/0"
    report = export_network(graph_report, destination, example)

    edges = read_dataframe(destination / FILENAME, layer="pedestrian_edges").set_index("segment_id")
    nodes = read_dataframe(destination / FILENAME, layer="pedestrian_nodes").set_index("node_id")
    assert report["layer_counts"] == {"pedestrian_edges": 6, "pedestrian_nodes": 7}
    assert edges.index.is_unique and edges.loc[example, "direction"] == "both"
    reverse = edges.loc["way/13/segment/0"]
    assert reverse["direction"] == "reverse"
    assert reverse["from_node_id"] == "3" and reverse["to_node_id"] == "9007199254740993"
    assert list(reverse.geometry.coords) == [(.002, 0), (.005, 0)]
    assert edges.loc[example, "sidewalk"] is None
    assert nodes.loc["2"].geometry == nodes.loc["4"].geometry
    assert report["topology"]["weakly_connected_components"] == 2

    with pytest.raises(FileExistsError):
        export_network(graph_report, destination, example)
    with (graph_dir / "nodes.jsonl").open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(ValueError, match="Source hash mismatch"):
        export_network(graph_report, tmp_path / "tampered-export", example)
    assert not (tmp_path / "tampered-export").exists()


def test_readback_preserves_null_and_populated_text(tmp_path):
    gpkg = tmp_path / FILENAME
    line = LineString([(0, 0), (1, 0)])
    rows = [
        {"name": None, "geometry": line},
        {"name": "Named Trail", "geometry": line},
    ]
    _write_layer(gpkg, "pedestrian_edges", rows)
    _verify_layer(gpkg, "pedestrian_edges", rows, "LineString", 2)
    with pytest.raises(ValueError, match="name"):
        _verify_layer(gpkg, "pedestrian_edges", [rows[1], rows[1]], "LineString", 2)

import hashlib
import json
from pandas import isna

from pyogrio import read_dataframe
from shapely.geometry import LineString, Point, box

from flm_pipeline.larimer_compact import COMPACT_FILENAME, _Edge, _vehicle_access_pruning, compact_network
from flm_pipeline.larimer_export import _write_layer


def _input(path):
    nodes = [
        {"node_id": node, "geometry": Point(x, 40.0)}
        for node, x in (("a", -105.0), ("b", -104.999), ("c", -104.998), ("d", -104.997), ("e", -104.99), ("f", -104.9899))
    ]
    common = {"direction": "both", "highway": "residential", "name": "Main", "sidewalk": None, "sidewalk_left": None, "sidewalk_right": None, "sidewalk_both": None}
    edges = []
    for segment, way, start, end, length, highway, name in (
        ("e1", "w1", "a", "b", 100.0, "residential", "Main"),
        ("e2", "w2", "b", "c", 50.0, "residential", "Main"),
        ("e3", "w3", "c", "d", 60.0, "residential", "Other"),
        ("e4", "w4", "e", "f", 50.0, "service", None),
    ):
        attrs = dict(common)
        attrs.update(segment_id=segment, way_id=way, from_node_id=start, to_node_id=end, length_ft=length, highway=highway, name=name)
        x = {"a": -105.0, "b": -104.999, "c": -104.998, "d": -104.997, "e": -104.99, "f": -104.9899}
        attrs["geometry"] = LineString([(x[start], 40.0), (x[end], 40.0)])
        edges.append(attrs)
    _write_layer(path, "pedestrian_edges", edges)
    _write_layer(path, "pedestrian_nodes", nodes)


def test_merges_across_way_boundary_and_prunes_conservative_service_component(tmp_path):
    source = tmp_path / "inclusive.gpkg"
    _input(source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    destination = tmp_path / "compact"
    report = compact_network(source, destination, boundary_bbox=(-105.1, 39.9, -104.9, 40.1))

    after = hashlib.sha256(source.read_bytes()).hexdigest()
    assert before == after
    assert report["counts"] == {"input_edges": 4, "output_edges": 2, "input_nodes": 6, "output_nodes": 3, "ledger_fragments": 3}
    edges = read_dataframe(destination / COMPACT_FILENAME, layer="pedestrian_edges").set_index("segment_id")
    assert "compact/e1" in edges.index and edges.loc["compact/e1", "length_ft"] == 150
    assert edges.loc["compact/e1", "from_node_id"] == "a" and edges.loc["compact/e1", "to_node_id"] == "c"
    assert "e3" in edges.index and "e4" not in edges.index
    assert report["checks"]["source_hash_before_equals_after"] is True


def test_one_way_orientation_is_preserved_when_chain_is_reversed(tmp_path):
    source = tmp_path / "inclusive.gpkg"
    nodes = [{"node_id": n, "geometry": Point(x, 0)} for n, x in (("a", 0), ("b", 0.001), ("c", 0.002))]
    attrs = {"direction": "forward", "highway": "residential", "name": "One Way", "sidewalk": None, "sidewalk_left": None, "sidewalk_right": None, "sidewalk_both": None}
    edges = []
    for segment, way, start, end in (("e1", "w1", "b", "a"), ("e2", "w2", "c", "b")):
        row = dict(attrs, segment_id=segment, way_id=way, from_node_id=start, to_node_id=end, length_ft=100.0, geometry=LineString([(0.001 if start == "b" else 0.002, 0), (0 if end == "a" else 0.001, 0)]))
        edges.append(row)
    _write_layer(source, "pedestrian_edges", edges)
    _write_layer(source, "pedestrian_nodes", nodes)
    report = compact_network(source, tmp_path / "compact")
    # Both source rows permit c -> b -> a, so the output remains forward after
    # the chain is oriented from c to a.
    edges_out = read_dataframe(tmp_path / "compact" / COMPACT_FILENAME, layer="pedestrian_edges")
    assert len(edges_out) == 1
    assert edges_out.iloc[0]["from_node_id"] == "c" and edges_out.iloc[0]["to_node_id"] == "a"
    assert edges_out.iloc[0]["direction"] == "forward"
    assert report["checks"]["original_preserved"] is True


def test_vehicle_access_pruning_preserves_sidewalk_links_and_destinations(tmp_path):
    ways = []
    edges = []

    def add(way, highway, links, *, service=None, restricted=False, **tags):
        tags["highway"] = highway
        if service:
            tags["service"] = service
        if restricted:
            tags["access"] = "private"
        ways.append({
            "osm_id": way,
            "tags": tags,
            "node_refs": list(dict.fromkeys(node for link in links for node in link)),
        })
        if restricted:
            return
        for start, end in links:
            geometry = LineString([(0, 0), (0.001, 0)])
            row = dict(way_id=way, from_node_id=start, to_node_id=end)
            edges.append(_Edge(row, geometry, geometry))

    add("street", "residential", [("road", "roadend")])
    add("sidewalk", "footway", [("walk", "walkend")])
    add("driveway", "service", [("road", "walk"), ("walk", "home")], service="driveway")
    add("parking", "service", [("walk", "stall"), ("walk", "entrance")], service="parking_aisle")
    add("queue", "service", [("road", "queue_end")], service="drive-through")
    add("private_road", "residential", [("private", "private_end")], restricted=True)
    add("private_branch", "service", [("private", "cottage")], service="driveway")
    add("unrelated_island", "service", [("island", "island_end")], service="driveway")
    add("public_service", "service", [("roadend", "public_end")], service="driveway", foot="yes")
    add("through_aisle", "service", [("roadend", "walkend")], service="parking_aisle")

    def write_rows(name, rows):
        (tmp_path / name).write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    write_rows("ways.jsonl", ways)
    write_rows("nodes.jsonl", [{"osm_id": "entrance", "tags": {"entrance": "main"}}])
    write_rows("ways-classified.jsonl", [
        {"evaluation": {
            "osm_id": way["osm_id"],
            "eligibility": "exclude" if way["osm_id"] == "private_road" else "include",
            "reason_codes": ["A_ACCESS_DENY"] if way["osm_id"] == "private_road" else [],
        }}
        for way in ways
    ])

    actions, _, _ = _vehicle_access_pruning(edges, box(-1, -1, 1, 1), tmp_path, tmp_path)
    assert {edges[i].row["to_node_id"]: action for i, action in actions.items()} == {
        "home": "pruned_driveway_tail",
        "stall": "pruned_parking_aisle",
        "queue_end": "pruned_drive_through",
        "cottage": "pruned_driveway_restricted_only",
    }


def test_exported_tags_prevent_merging_different_way_values(tmp_path):
    source = tmp_path / "inclusive.gpkg"
    _input(source)
    ways = [
        {"osm_id": f"w{i}", "node_refs": [], "tags": tags}
        for i, tags in enumerate((
            {"highway": "residential", "foot": "yes"},
            {"highway": "residential"},
            {"highway": "residential"},
            {"highway": "service", "service": "driveway"},
        ), start=1)
    ]
    (tmp_path / "ways.jsonl").write_text("\n".join(map(json.dumps, ways)), encoding="utf-8")
    (tmp_path / "nodes.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "ways-classified.jsonl").write_text("\n".join(
        json.dumps({"evaluation": {"osm_id": way["osm_id"], "eligibility": "include", "reason_codes": []}})
        for way in ways
    ), encoding="utf-8")
    output = tmp_path / "tagged"
    compact_network(
        source, output, boundary_bbox=(-105.1, 39.9, -104.9, 40.1),
        osm_extraction=tmp_path, osm_classification=tmp_path, retain_osm_tags=True,
    )
    edges = read_dataframe(output / COMPACT_FILENAME, layer="pedestrian_edges").set_index("segment_id")
    assert edges.loc["e1", "foot"] == "yes"
    assert isna(edges.loc["e2", "foot"])

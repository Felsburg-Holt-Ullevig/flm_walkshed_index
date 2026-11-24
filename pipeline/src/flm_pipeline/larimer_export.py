"""Export and check the two GIS layers for the Larimer pedestrian pilot."""

from itertools import batched
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

import geopandas as gpd
from pyogrio import list_layers, read_dataframe, read_info, write_dataframe
from shapely.geometry import LineString, Point

from .classification import _hash_file, _jsonl
from .cli import _promote_directory

CRS = "EPSG:4326"
FILENAME = "larimer_pedestrian_network.gpkg"
BATCH_SIZE = 25_000
SIDEWALK = ("sidewalk", "sidewalk:left", "sidewalk:right", "sidewalk:both")


def _object(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(path):
    for _, row in _jsonl(path, path.name):
        yield row


def _edges(path, ways, nodes):
    for segment in _rows(path):
        if segment["eligibility"] != "include":
            continue
        segment_id = segment["candidate_id"]
        start, end = segment["from_node_id"], segment["to_node_id"]
        coordinates = segment["coordinates"]
        if [nodes[start], nodes[end]] != [tuple(xy) for xy in coordinates]:
            raise ValueError(f"Endpoint geometry mismatch for {segment_id}")
        tags = ways[segment["way_id"]]
        yield {
            "segment_id": segment_id,
            "way_id": segment["way_id"],
            "from_node_id": start,
            "to_node_id": end,
            "direction": segment["direction"],
            "length_ft": segment["length_ft"],
            "highway": tags["highway"],
            "name": tags.get("name"),
            **{key.replace(":", "_"): tags.get(key) for key in SIDEWALK},
            "geometry": LineString(coordinates),
        }


def _nodes(nodes):
    for node_id, coordinate in nodes.items():
        yield {"node_id": node_id, "geometry": Point(coordinate)}


def _write_layer(path, layer, rows):
    for index, batch in enumerate(batched(rows, BATCH_SIZE)):
        frame = gpd.GeoDataFrame(batch, geometry="geometry", crs=CRS)
        write_dataframe(frame, path, layer=layer, driver="GPKG", append=index > 0)


def _verify_layer(path, layer, rows, geometry_type, expected_count):
    info = read_info(path, layer=layer, force_feature_count=True)
    if (info["crs"], info["geometry_type"], info["features"]) != (CRS, geometry_type, expected_count):
        raise ValueError(f"CRS, geometry type, or count mismatch for {layer}")
    offset = 0
    for batch in batched(rows, BATCH_SIZE):
        actual_rows = read_dataframe(path, layer=layer, skip_features=offset, max_features=len(batch))
        # The GIS reader can represent a NULL text field as pandas NaN.
        records = actual_rows.astype(object).where(actual_rows.notna(), None).to_dict("records")
        for actual, expected in zip(records, batch, strict=True):
            if actual != expected:
                fields = ", ".join(key for key in expected if actual.get(key) != expected[key])
                raise ValueError(f"Reopened {layer} differs at row {offset + 1}: {fields}")
            offset += 1
    if offset != expected_count:
        raise ValueError(f"Source count mismatch for {layer}")


class _Topology:
    """Count weak components without merging node IDs at the same location."""

    def __init__(self):
        self.parent = {}

    def _root(self, node_id):
        parent = self.parent.setdefault(node_id, node_id)
        while node_id != parent:
            grandparent = self.parent[parent]
            self.parent[node_id] = grandparent
            node_id, parent = parent, grandparent
        return node_id

    def add(self, start, end):
        self.parent[self._root(start)] = self._root(end)


def export_network(graph_report_path: Path, destination: Path, example_id: str):
    """Write to a fresh directory, promoting it only after the GIS checks pass."""
    if re.fullmatch(r"way/[1-9][0-9]*/segment/[0-9]+", example_id) is None:
        raise ValueError("Invalid example segment ID")
    if destination.exists():
        raise FileExistsError(destination)
    graph = _object(graph_report_path)
    if graph["report_version"] != "experimental-routing-graph-1" or not (
        graph["checks"] and all(value is True for value in graph["checks"].values())
    ):
        raise ValueError("A verified Phase 1 graph is required")
    graph_dir = graph_report_path.parent
    ways_path = Path(graph["inputs"]["extraction_directory"]) / "ways.jsonl"
    segments_path = graph_dir / "segments.jsonl"
    nodes_path = graph_dir / "nodes.jsonl"
    hashes = {
        ways_path: graph["inputs"]["extraction_hashes"]["ways.jsonl"],
        segments_path: graph["output_files"]["segments.jsonl"]["sha256"],
        nodes_path: graph["output_files"]["nodes.jsonl"]["sha256"],
    }
    for path, digest in hashes.items():
        if _hash_file(path) != digest:
            raise ValueError(f"Source hash mismatch for {path}")
    ways = {row["osm_id"]: row["tags"] for row in _rows(ways_path)}
    nodes = {row["node_id"]: (row["lon"], row["lat"]) for row in _rows(nodes_path)}
    counts = graph["counts"]
    edge_count = counts["candidates_by_eligibility"]["include"]
    node_count = counts["nodes"]
    topology = _Topology()
    example = {}

    def edges_with_audit():
        for edge in _edges(segments_path, ways, nodes):
            topology.add(edge["from_node_id"], edge["to_node_id"])
            if edge["segment_id"] == example_id:
                if example:
                    raise ValueError("Duplicate example segment")
                example.update({key: value for key, value in edge.items() if key != "geometry"})
            yield edge

    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent, prefix=".larimer-export-") as temporary:
        staging = Path(temporary) / "release"
        staging.mkdir()
        gpkg = staging / FILENAME
        print("Writing pedestrian edges and nodes", flush=True)
        _write_layer(gpkg, "pedestrian_edges", edges_with_audit())
        _write_layer(gpkg, "pedestrian_nodes", _nodes(nodes))
        if not example or topology.parent.keys() != nodes.keys():
            raise ValueError("Example segment missing or endpoint coverage differs")
        if set(list_layers(gpkg)[:, 0]) != {"pedestrian_edges", "pedestrian_nodes"}:
            raise ValueError("Unexpected GeoPackage layers")
        print("Reopening both layers and comparing every row", flush=True)
        _verify_layer(gpkg, "pedestrian_edges", _edges(segments_path, ways, nodes), "LineString", edge_count)
        _verify_layer(gpkg, "pedestrian_nodes", _nodes(nodes), "Point", node_count)
        reopened = read_dataframe(gpkg, layer="pedestrian_edges", where=f"segment_id = '{example_id}'")
        if len(reopened) != 1 or reopened.iloc[0]["direction"] != example["direction"]:
            raise ValueError("Example segment did not reopen exactly once with its saved direction")
        for path, digest in hashes.items():
            if _hash_file(path) != digest:
                raise ValueError(f"Source changed during export: {path}")
        report = {
            "status": "pass",
            "graph_report": str(graph_report_path.resolve()),
            "source": graph["inputs"]["source"],
            "attribution": "© OpenStreetMap contributors, https://www.openstreetmap.org/copyright",
            "policy": graph["policy"],
            "coverage": graph["coverage"],
            "limitations": graph["limitations"],
            "layer_counts": {"pedestrian_edges": edge_count, "pedestrian_nodes": node_count},
            "crs": CRS,
            "topology": {
                "weakly_connected_components": sum(node == parent for node, parent in topology.parent.items()),
                "nodes_beyond_one_per_coordinate": len(nodes) - len(set(nodes.values())),
                "source_duplicate_segment_geometries_by_graph_audit": counts["duplicate_geometry_candidates"],
            },
            "checks": {"source_hashes": True, "all_gis_records_reopened": True, "all_endpoints_resolved": True},
            "example": example,
            "geopackage_sha256": _hash_file(gpkg),
            "geopackage_bytes": gpkg.stat().st_size,
        }
        (staging / "build-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        if destination.exists():
            raise FileExistsError(destination)
        _promote_directory(staging, destination)
    return report

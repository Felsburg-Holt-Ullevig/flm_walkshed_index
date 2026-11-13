"""Independent Denver source-versus-tile walkshed recomputation."""
from __future__ import annotations

from collections import defaultdict
import argparse
import hashlib
import heapq
import json
import math
from pathlib import Path
import sys
import tomllib

from pyproj import Geod

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipeline" / "src"))

from flm_pipeline.routing import Readiness, Segment
from flm_pipeline.walk_reference import snap_origin, traverse_reference


CASE_POINTS = {
    "D01": (-105.0004685, 39.7529095),
    "C01": (-104.943057, 39.826361),
    "D02": (-105.049, 39.748),
}
BUDGETS_FT = (1232, 2464, 3696)
EXTRACT_BBOX = (-105.08, 39.68, -104.93, 39.83)
SAMPLE_POINTS = {
    "G01": (-104.6928167, 40.4249),
    "B01": (-105.06877, 39.91758),
    "F01": (-105.81945, 39.94776),
}
WGS84_FEET = Geod(a=20_925_646.325459316, rf=298.257223563)


def read_json(path: Path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            row = json.loads(line)
            if not isinstance(row, dict):
                raise AssertionError(f"Expected JSON object at {path}:{line_number}")
            yield row


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def checked_path(project_root: Path, value) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (project_root / path).resolve()
    if not resolved.is_relative_to(project_root.resolve()):
        raise AssertionError(f"sample-index path escapes project root: {value}")
    return resolved


def expected_tile_record(segment: dict, way: dict) -> dict:
    """Map graph and extracted-way fields to the actual v0 tile record."""
    tags = way["tags"]
    return {"id": segment["candidate_id"], "from": segment["from_node_id"],
            "to": segment["to_node_id"], "len_ft": segment["length_ft"],
            "dir": segment["direction"], "coords": segment["coordinates"],
            "way_id": segment["way_id"], "hwy": tags.get("highway", ""),
            "name": tags.get("name", ""), "sidewalk": tags.get("sidewalk", ""),
            "footway": tags.get("footway", "")}


def configured_bbox(recorded_bbox) -> tuple[float, ...]:
    """Apply the preparation contract's 15-significant-digit TOML format."""
    return tuple(float(format(value, ".15g")) for value in recorded_bbox)


def merge(intervals):
    merged = []
    for low, high in sorted(intervals):
        if high <= low:
            continue
        if merged and low <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], high))
        else:
            merged.append((low, high))
    return merged


def ecef(lon_deg, lat_deg):
    """WGS84 ellipsoid surface point in international-foot ECEF coordinates."""
    a = 20_925_646.325459316
    flattening = 1 / 298.257223563
    e2 = flattening * (2 - flattening)
    lon, lat = math.radians(lon_deg), math.radians(lat_deg)
    prime_vertical = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    return (prime_vertical * math.cos(lat) * math.cos(lon),
            prime_vertical * math.cos(lat) * math.sin(lon),
            prime_vertical * (1 - e2) * math.sin(lat))


def ecef_bbox_edge_lower_bound(origin_lonlat, bbox):
    """Conservative ECEF chord/plane lower bound to any point on bbox edges."""
    west, south, east, north = bbox
    origin_lon, origin_lat = origin_lonlat
    if not west <= origin_lon <= east or not south <= origin_lat <= north:
        raise AssertionError("sample origin is not inside its prepared bbox")
    origin = ecef(origin_lon, origin_lat)
    latitude_chords = [math.dist(origin, ecef(origin_lon, edge_lat)) for edge_lat in (south, north)]
    longitude_plane_bounds = []
    for edge_lon in (west, east):
        longitude = math.radians(edge_lon)
        longitude_plane_bounds.append(abs(-math.sin(longitude) * origin[0]
                                          + math.cos(longitude) * origin[1]))
    all_bounds = latitude_chords + longitude_plane_bounds
    return {"latitude_edge_chords_ft": latitude_chords,
            "longitude_edge_plane_lower_bounds_ft": longitude_plane_bounds,
            "global_edge_lower_bound_ft": min(all_bounds)}


def independent_dijkstra(segments, projection, budget_ft):
    """Compute node distances and source intervals without routing.traverse."""
    by_id = {segment.id: segment for segment in segments}
    if len(by_id) != len(segments):
        raise AssertionError("duplicate source segment identity")
    selected = by_id[projection.candidate_id]
    distances = {}
    queue = []
    raw_intervals = defaultdict(list)

    def seed(node, distance):
        if distance <= budget_ft and distance < distances.get(node, math.inf):
            distances[node] = distance
            heapq.heappush(queue, (distance, node))

    def include(identity, low, high):
        if high > low:
            raw_intervals[identity].append((low, high))

    length, offset = selected.length_ft, projection.offset_ft
    if projection.endpoint_node is not None:
        seed(projection.endpoint_node, 0.0)
    else:
        if selected.direction in {"both", "forward"}:
            include(selected.id, offset, offset + min(length - offset, budget_ft))
            seed(selected.end, length - offset)
        if selected.direction in {"both", "reverse"}:
            include(selected.id, offset - min(offset, budget_ft), offset)
            seed(selected.start, offset)

    outgoing = defaultdict(list)
    for segment in segments:
        if segment.direction in {"both", "forward"}:
            outgoing[segment.start].append((segment.end, segment))
        if segment.direction in {"both", "reverse"}:
            outgoing[segment.end].append((segment.start, segment))
    while queue:
        current_distance, node = heapq.heappop(queue)
        if current_distance != distances[node]:
            continue
        for neighbor, segment in outgoing.get(node, ()):
            candidate = current_distance + segment.length_ft
            if candidate <= budget_ft and candidate < distances.get(neighbor, math.inf):
                distances[neighbor] = candidate
                heapq.heappush(queue, (candidate, neighbor))

    for segment in segments:
        remaining = budget_ft - distances.get(segment.start, math.inf)
        if segment.direction in {"both", "forward"} and remaining > 0:
            include(segment.id, 0.0, min(segment.length_ft, remaining))
        remaining = budget_ft - distances.get(segment.end, math.inf)
        if segment.direction in {"both", "reverse"} and remaining > 0:
            include(segment.id, segment.length_ft - min(segment.length_ft, remaining), segment.length_ft)
    intervals = {identity: merge(spans) for identity, spans in sorted(raw_intervals.items())}
    return intervals, dict(sorted(distances.items()))


def boundary_frontier(boundary_nodes, node_distances, budget_ft):
    """Report reached boundary nodes with remaining feet, including zero."""
    return {node: budget_ft - node_distances[node] for node in sorted(boundary_nodes)
            if node in node_distances and node_distances[node] <= budget_ft}


def load_inputs(project_root: Path):
    package = project_root / "data/generated/prototype/network-packages/denver-policy03-task52-20261104-e"
    tile_dir = project_root / "data/generated/prototype/walk-tiles/denver-policy03-walk-tiles-20261111-imperial"
    package_segments = read_json(package / "segments.json")["segments"]
    source_nodes = read_json(package / "nodes.json")["nodes"]
    source_arcs = read_json(package / "arcs.json")["arcs"]
    source = [Segment(row["candidate_id"], row["from_node_id"], row["to_node_id"], row["length_ft"], row["direction"])
              for row in package_segments]
    tile_manifest = read_json(tile_dir / "manifest.json")
    unique_records = {}
    tile_coordinates = {}
    for entry in tile_manifest["tiles"]:
        payload = read_json(tile_dir / entry["path"])
        for row in payload["segments"]:
            if row["id"] in unique_records and unique_records[row["id"]] != row:
                raise AssertionError(f"tile copies disagree: {row['id']}")
            unique_records[row["id"]] = row
            for node_id, coordinate in ((row["from"], row["coords"][0]), (row["to"], row["coords"][-1])):
                coordinate = tuple(coordinate)
                if node_id in tile_coordinates and tile_coordinates[node_id] != coordinate:
                    raise AssertionError(f"tile node coordinates disagree: {node_id}")
                tile_coordinates[node_id] = coordinate
    tiled = [Segment(row["id"], row["from"], row["to"], row["len_ft"], row["dir"])
             for row in unique_records.values()]
    source_coordinates = {row["node_id"]: tuple(row["coordinate"]) for row in source_nodes}
    if set(source_coordinates) != set(tile_coordinates):
        raise AssertionError("source/tile endpoint node ID sets differ")
    if source_coordinates != tile_coordinates:
        raise AssertionError("source/tile endpoint coordinates differ")
    if {segment.id for segment in source} != set(unique_records):
        raise AssertionError("source/tile segment ID sets differ")
    source_arc_set = set()
    for segment in source:
        if segment.direction in {"both", "forward"}:
            source_arc_set.add((segment.id, "forward", segment.start, segment.end))
        if segment.direction in {"both", "reverse"}:
            source_arc_set.add((segment.id, "reverse", segment.end, segment.start))
    given_arc_set = {(row["candidate_id"], row["direction"], row["from_node_id"], row["to_node_id"])
                     for row in source_arcs}
    if source_arc_set != given_arc_set:
        raise AssertionError("source segment directions differ from arcs.json")
    return tile_dir, tile_manifest, source, tiled, source_coordinates


def load_sample_network(project_root: Path, item: dict):
    """Load and independently reconcile one graph, extraction, and tile sample."""
    graph_dir = checked_path(project_root, item["graph_directory"])
    extraction_dir = checked_path(project_root, item["extraction_directory"])
    tile_dir = checked_path(project_root, item["tile_directory"])
    graph_report = read_json(graph_dir / "run-report.json")
    if graph_report.get("report_version") != "experimental-routing-graph-1":
        raise AssertionError("unexpected sample routing-graph report version")
    graph_outputs = graph_report.get("output_files", {})
    for name, metadata in graph_outputs.items():
        path = graph_dir / name
        if Path(name).name != name:
            raise AssertionError(f"unsafe sample graph output name: {name}")
        if not isinstance(metadata, dict) or path.stat().st_size != metadata.get("bytes") or sha256(path) != metadata.get("sha256"):
            raise AssertionError(f"sample graph output hash/size mismatch: {name}")
    if not {"nodes.jsonl", "segments.jsonl", "arcs.jsonl", "routing.gpkg"} <= graph_outputs.keys():
        raise AssertionError("sample graph output manifest is incomplete")
    if not graph_report.get("checks") or not all(value is True for value in graph_report["checks"].values()):
        raise AssertionError("sample graph has incomplete or failed checks")
    extraction = read_json(extraction_dir / "extraction.json")
    extraction_files = extraction.get("files", {})
    for name in ("nodes.jsonl", "ways.jsonl", "relations.jsonl"):
        metadata = extraction_files.get(name)
        path = extraction_dir / name
        if not isinstance(metadata, dict) or path.stat().st_size != metadata.get("bytes") or sha256(path) != metadata.get("sha256"):
            raise AssertionError(f"sample extraction output hash/size mismatch: {name}")
    way_rows = list(read_jsonl(extraction_dir / "ways.jsonl"))
    ways = {row["osm_id"]: row for row in way_rows}
    if len(ways) != len(way_rows):
        raise AssertionError("sample extraction has duplicate way identities")
    graph_segments = [row for row in read_jsonl(graph_dir / "segments.jsonl") if row["eligibility"] == "include"]
    graph_nodes = list(read_jsonl(graph_dir / "nodes.jsonl"))
    graph_arcs = list(read_jsonl(graph_dir / "arcs.jsonl"))
    source = [Segment(row["candidate_id"], row["from_node_id"], row["to_node_id"],
                      row["length_ft"], row["direction"]) for row in graph_segments]
    if len({segment.id for segment in source}) != len(source):
        raise AssertionError("sample graph has duplicate included segment identities")
    source_coordinates = {row["node_id"]: (row["lon"], row["lat"]) for row in graph_nodes}
    if len(source_coordinates) != len(graph_nodes):
        raise AssertionError("sample graph has duplicate node IDs")

    source_arc_set = set()
    for segment in source:
        if segment.direction in {"both", "forward"}:
            source_arc_set.add((segment.id, "forward", segment.start, segment.end))
        if segment.direction in {"both", "reverse"}:
            source_arc_set.add((segment.id, "reverse", segment.end, segment.start))
    graph_arc_set = {(row["candidate_id"], row["direction"], row["from_node_id"], row["to_node_id"])
                     for row in graph_arcs}
    if source_arc_set != graph_arc_set or len(graph_arc_set) != len(graph_arcs):
        raise AssertionError("sample graph segment directions differ from source arcs")

    tile_manifest = read_json(tile_dir / "manifest.json")
    tile_files = {entry["path"] for entry in tile_manifest["tiles"]}
    if len(tile_files) != len(tile_manifest["tiles"]):
        raise AssertionError("duplicate sample tile path")
    network_dir = tile_dir / "network"
    disk_files = {path.relative_to(tile_dir).as_posix() for path in network_dir.rglob("*") if path.is_file()}
    if disk_files != tile_files:
        raise AssertionError("sample tile disk files differ from manifest membership")
    unique_records, tile_coordinates = {}, {}
    for entry in tile_manifest["tiles"]:
        path = tile_dir / entry["path"]
        if path.stat().st_size != entry["bytes"]:
            raise AssertionError(f"sample tile byte count mismatch: {entry['path']}")
        payload = read_json(path)
        if len(payload.get("segments", [])) != entry.get("segments"):
            raise AssertionError(f"sample tile segment count mismatch: {entry['path']}")
        for record in payload["segments"]:
            identity = record["id"]
            if identity in unique_records and unique_records[identity] != record:
                raise AssertionError(f"sample tile copies differ: {identity}")
            unique_records[identity] = record
            for node_id, point in ((record["from"], record["coords"][0]),
                                   (record["to"], record["coords"][-1])):
                point = tuple(point)
                if node_id in tile_coordinates and tile_coordinates[node_id] != point:
                    raise AssertionError(f"sample tile endpoint coordinates differ: {node_id}")
                tile_coordinates[node_id] = point

    source_by_id = {row["candidate_id"]: row for row in graph_segments}
    if set(source_by_id) != set(unique_records):
        raise AssertionError("sample source/tile segment ID sets differ")
    if set(source_coordinates) != set(tile_coordinates) or source_coordinates != tile_coordinates:
        raise AssertionError("sample source/tile node identities or coordinates differ")
    for identity, segment in source_by_id.items():
        way = ways.get(segment["way_id"])
        if way is None:
            raise AssertionError(f"sample tile segment has no extracted way: {identity}")
        sequence = segment["sequence"]
        if type(sequence) is not int or sequence < 0 or way.get("node_refs", [])[sequence:sequence + 2] != [segment["from_node_id"], segment["to_node_id"]]:
            raise AssertionError(f"sample graph segment does not map to consecutive complete-way node refs: {identity}")
        expected = expected_tile_record(segment, way)
        if unique_records[identity] != expected:
            raise AssertionError(f"sample tile record differs from source mapping: {identity}")
    bbox = tuple(graph_report["coverage"]["extract_bbox"])
    if "extract_bbox" in item and configured_bbox(item["extract_bbox"]) != bbox:
        raise AssertionError("rounded sample-index bbox differs from source graph bbox")
    tiled = [Segment(row["id"], row["from"], row["to"], row["len_ft"], row["dir"])
             for row in unique_records.values()]
    return {"graph_directory": graph_dir, "extraction_directory": extraction_dir, "tile_directory": tile_dir,
            "source": source, "tiled": tiled, "coordinates": source_coordinates, "records": unique_records,
            "ways": ways, "graph_segments": graph_segments, "graph_nodes": graph_nodes,
            "graph_arcs": graph_arcs, "manifest": tile_manifest, "extract_bbox": bbox}


def compare_reference_case(network_id, network, point, reference_case):
    """Recompute a sample case independently and compare its saved JSON answers."""
    from flm_pipeline.routing import Readiness
    from flm_pipeline.walk_reference import snap_origin, traverse_reference

    tile_snap = snap_origin(network["tiled"], network["coordinates"], point)
    source_snap = snap_origin(network["source"], network["coordinates"], point)
    if tile_snap.as_dict() != source_snap.as_dict():
        raise AssertionError(f"{network_id}: source/tile snap differs")
    if reference_case["network_key"] != network_id or reference_case["origin_lonlat"] != list(point):
        raise AssertionError(f"{network_id}: reference case identity/origin differs")
    if reference_case["snap"] != tile_snap.as_dict():
        raise AssertionError(f"{network_id}: saved snap differs from independent source/tile search")
    bbox = network["extract_bbox"]
    boundary_nodes = tuple(sorted(node_id for node_id, (lon, lat) in network["coordinates"].items()
                                  if lon <= bbox[0] or lon >= bbox[2] or lat <= bbox[1] or lat >= bbox[3]))
    readiness = Readiness(("source_policy_and_coverage_limitations",), "not_established", boundary_nodes)
    answers = reference_case["answers"]
    if tile_snap.selected is None:
        if tile_snap.status != "off_network" or reference_case.get("rejection_reason") is None:
            raise AssertionError(f"{network_id}: failed snap lacks a recorded rejection")
        if len(answers) != 3 or any(answer.get("reached_segment_count") is not None
                                    or answer.get("total_reached_length_ft") is not None
                                    or answer.get("intervals_ft") is not None for answer in answers):
            raise AssertionError(f"{network_id}: rejected origin has non-null metrics")
        return {"snap_status": tile_snap.status, "selected_segment": None, "budgets": [
            {"budget_ft": b, "reached_segment_count": None, "reached_length_ft": None,
             "reached_frontier_nodes": None, "independent_match": True} for b in BUDGETS_FT]}

    if tile_snap.status != "resolved" or len(answers) != 3:
        raise AssertionError(f"{network_id}: expected resolved snap and three budget answers")
    actual_answers = {answer["budget_ft"]: answer for answer in answers}
    if set(actual_answers) != set(BUDGETS_FT):
        raise AssertionError(f"{network_id}: reference budgets differ")
    report_budgets = []
    for budget in BUDGETS_FT:
        tile_intervals, tile_distances = independent_dijkstra(network["tiled"], tile_snap.selected, budget)
        source_intervals, source_distances = independent_dijkstra(network["source"], source_snap.selected, budget)
        if (tile_intervals, tile_distances) != (source_intervals, source_distances):
            raise AssertionError(f"{network_id}/{budget}: source/tile independent Dijkstra differs")
        answer = actual_answers[budget]
        saved_intervals = {identity: [tuple(span) for span in spans]
                           for identity, spans in answer["intervals_ft"].items()}
        if saved_intervals != tile_intervals:
            raise AssertionError(f"{network_id}/{budget}: saved intervals differ from independent Dijkstra")
        total = math.fsum(high - low for identity in sorted(tile_intervals)
                          for low, high in tile_intervals[identity])
        if answer["reached_segment_count"] != len(tile_intervals) or answer["total_reached_length_ft"] != total:
            raise AssertionError(f"{network_id}/{budget}: saved count or length total differs")
        expected_frontier = boundary_frontier(boundary_nodes, tile_distances, budget)
        if answer.get("reached_frontier_remaining_ft") != expected_frontier:
            raise AssertionError(f"{network_id}/{budget}: saved frontier differs from independent Dijkstra")
        integrated = traverse_reference(network["tiled"], tile_snap.selected, budget, readiness)
        if integrated.intervals_ft != tile_intervals or integrated.frontier != expected_frontier:
            raise AssertionError(f"{network_id}/{budget}: integrated traversal differs from independent Dijkstra")
        if answer["status"] != integrated.computation_status:
            raise AssertionError(f"{network_id}/{budget}: saved status differs")
        report_budgets.append({"budget_ft": budget, "reached_segment_count": len(tile_intervals),
            "reached_length_ft": total, "reached_frontier_nodes": len(expected_frontier),
            "status": integrated.computation_status, "independent_match": True})
    return {"snap_status": tile_snap.status, "selected_segment": tile_snap.selected.candidate_id,
            "snap_distance_ft": tile_snap.selected.distance_ft, "budgets": report_budgets}


def validate_sample_margins(project_root: Path, samples_index_path: Path, sample_index: dict):
    results = {}
    for case_id, origin in SAMPLE_POINTS.items():
        item = sample_index["cases"][case_id]
        source_config = samples_index_path.parent / case_id / "source.toml"
        with source_config.open("rb") as stream:
            config = tomllib.load(stream)
        bbox = tuple(config["extract_bbox"])
        if tuple(config["station_lonlat"]) != origin:
            raise AssertionError(f"{case_id}: source config origin differs from approved point")
        # The index records the computed full-precision bbox; source.toml is
        # serialized to 15 significant digits by the preparation contract.
        recorded = configured_bbox(item["extract_bbox"])
        if recorded != bbox:
            raise AssertionError(f"{case_id}: rounded sample-index bbox differs from source config")
        bounds = ecef_bbox_edge_lower_bound(origin, bbox)
        if bounds["global_edge_lower_bound_ft"] < 5000:
            raise AssertionError(f"{case_id}: independent ECEF lower bound is below 5,000 ft")
        results[case_id] = {"extract_bbox": list(bbox), **bounds,
                            "margin_excess_ft": bounds["global_edge_lower_bound_ft"] - 5000}
    return results


def verify_samples(project_root: Path, samples_index_path: Path, references_path: Path | None = None):
    sample_index = read_json(samples_index_path)
    if sample_index.get("format") != "walk-sample-index" or sample_index.get("version") != 1:
        raise AssertionError("unsupported sample-index format/version")
    if sample_index.get("pedestrian_speed_mph") != 2.8 or sample_index.get("pedestrian_scenario_id") != "plan-a-walk-reference-2.8-v1":
        raise AssertionError("sample index does not use the approved 2.8 mph scenario")
    if set(sample_index.get("cases", {})) != set(SAMPLE_POINTS):
        raise AssertionError("sample index case set differs from G01/B01/F01")
    networks = {case_id: load_sample_network(project_root, sample_index["cases"][case_id])
                for case_id in SAMPLE_POINTS}
    margins = validate_sample_margins(project_root, samples_index_path, sample_index)
    result = {"sample_index": str(samples_index_path), "sample_margins": margins,
              "cases": {}, "reference_json": None, "gpkg": None}
    if references_path is None:
        for case_id, network in networks.items():
            point = SAMPLE_POINTS[case_id]
            snap = snap_origin(network["tiled"], network["coordinates"], point)
            source_snap = snap_origin(network["source"], network["coordinates"], point)
            if snap.as_dict() != source_snap.as_dict():
                raise AssertionError(f"{case_id}: source/tile snap mismatch")
            summary = {"snap_status": snap.status, "selected_segment": snap.selected.candidate_id if snap.selected else None,
                       "snap_distance_ft": snap.selected.distance_ft if snap.selected else None, "budgets": []}
            if snap.selected:
                bbox = network["extract_bbox"]
                edge_nodes = tuple(sorted(n for n, (x, y) in network["coordinates"].items()
                                          if x <= bbox[0] or x >= bbox[2] or y <= bbox[1] or y >= bbox[3]))
                from flm_pipeline.routing import Readiness
                readiness = Readiness(("source_policy_and_coverage_limitations",), "not_established", edge_nodes)
                for budget in BUDGETS_FT:
                    ti, td = independent_dijkstra(network["tiled"], snap.selected, budget)
                    si, sd = independent_dijkstra(network["source"], source_snap.selected, budget)
                    if (ti, td) != (si, sd):
                        raise AssertionError(f"{case_id}/{budget}: source/tile Dijkstra mismatch")
                    frontier = boundary_frontier(edge_nodes, td, budget)
                    integrated = traverse_reference(network["tiled"], snap.selected, budget, readiness)
                    if integrated.intervals_ft != ti or integrated.frontier != frontier:
                        raise AssertionError(f"{case_id}/{budget}: independent/integrated Dijkstra mismatch")
                    summary["budgets"].append({"budget_ft": budget, "reached_segment_count": len(ti),
                        "reached_length_ft": math.fsum(hi-lo for sid in sorted(ti) for lo,hi in ti[sid]),
                        "reached_frontier_nodes": len(frontier), "status": integrated.computation_status,
                        "independent_match": True})
            result["cases"][case_id] = summary
        return result

    reference_json = references_path
    if reference_json.is_dir():
        reference_json = reference_json / "reference" / "cases.json"
    elif reference_json.name != "cases.json":
        reference_json = reference_json / "reference" / "cases.json"
    reference = read_json(reference_json)
    if reference.get("format") != "walk-reference" or reference.get("speed_mph") != 2.8:
        raise AssertionError("reference JSON metadata is inconsistent with approved method")
    if reference.get("connector_charged_seconds") != 0 or reference.get("snap_limit_ft") != 500:
        raise AssertionError("reference JSON connector/threshold metadata is incorrect")
    reference_cases = {case["id"]: case for case in reference["cases"]}
    if set(reference_cases) != {"D01", "G01", "B01", "C01", "F01", "D02"}:
        raise AssertionError("reference case set differs from approved Step 3 cases")
    # The final release also includes the established Denver positive and
    # rejection controls. Rebuild its graph directly from the source package
    # and tiles for independent display-geometry validation.
    denver_tile_dir, denver_manifest, denver_source, denver_tiled, denver_coords = load_inputs(project_root)
    denver_records = {}
    for entry in denver_manifest["tiles"]:
        for record in read_json(denver_tile_dir / entry["path"])["segments"]:
            denver_records[record["id"]] = record
    networks["denver"] = {"records": denver_records, "tiled": denver_tiled,
                          "source": denver_source, "coordinates": denver_coords,
                          "extract_bbox": EXTRACT_BBOX}
    all_points = {**SAMPLE_POINTS, "D01": CASE_POINTS["D01"], "C01": CASE_POINTS["C01"], "D02": CASE_POINTS["D02"]}
    for case_id, point in all_points.items():
        if case_id not in reference_cases:
            raise AssertionError(f"reference JSON is missing {case_id}")
        network_key = "denver" if case_id in {"D01", "C01", "D02"} else case_id
        result["cases"][case_id] = compare_reference_case(network_key, networks[network_key], point, reference_cases[case_id])
    result["reference_json"] = str(reference_json)
    gpkg_path = reference_json.parent / "walk-reference.gpkg"
    result["gpkg"] = validate_reference_gpkg(gpkg_path, reference, networks)
    return result


def validate_reference_gpkg(path: Path, reference: dict, networks: dict):
    """Reopen reference layers and independently check attributes and geometry."""
    import geopandas as gpd
    import pyogrio
    from shapely.geometry import LineString, Point

    geod = WGS84_FEET
    cases = {case["id"]: case for case in reference["cases"]}
    expected_origins = {case_id: tuple(case["origin_lonlat"]) for case_id, case in cases.items()}
    expected_snap_ids = {case_id for case_id, case in cases.items() if case["snap"]["selected"] is not None}
    expected_connectors = {case_id for case_id in expected_snap_ids
                           if cases[case_id]["snap"]["selected"]["distance_ft"] > 0}
    layers = {row[0] for row in pyogrio.list_layers(path)}
    if layers != {"origins", "snaps", "connectors", "reached_streets"}:
        raise AssertionError(f"GPKG layer names differ: {layers}")
    loaded = {}
    for layer in sorted(layers):
        frame = gpd.read_file(path, layer=layer, engine="pyogrio")
        if frame.crs is None or frame.crs.to_epsg() != 4326:
            raise AssertionError(f"GPKG {layer} CRS is not EPSG:4326")
        loaded[layer] = frame
    origins = loaded["origins"]
    if len(origins) != len(cases) or set(origins.case_id) != set(cases):
        raise AssertionError("GPKG origin IDs/count differ from cases")
    for row in origins.itertuples():
        case = cases[row.case_id]
        if (row.snap_status != case["snap"]["status"] or row.name != case["name"]
                or row.geometry.geom_type != "Point" or tuple(row.geometry.coords[0]) != expected_origins[row.case_id]):
            raise AssertionError(f"GPKG origin geometry differs: {row.case_id}")
    snaps = loaded["snaps"]
    if len(snaps) != len(expected_snap_ids) or set(snaps.case_id) != expected_snap_ids:
        raise AssertionError("GPKG snap IDs/count differ from successful snaps")
    for row in snaps.itertuples():
        selected = cases[row.case_id]["snap"]["selected"]
        if row.candidate_id != selected["candidate_id"] or abs(row.distance_ft-selected["distance_ft"]) > 1e-9 or abs(row.offset_ft-selected["offset_ft"]) > 1e-9:
            raise AssertionError(f"GPKG snap attributes differ: {row.case_id}")
        if row.geometry.geom_type != "Point" or math.dist(tuple(row.geometry.coords[0]), tuple(selected["point"])) > 1e-12:
            raise AssertionError(f"GPKG snap geometry differs: {row.case_id}")
    connectors = loaded["connectors"]
    if len(connectors) != len(expected_connectors) or set(connectors.case_id) != expected_connectors:
        raise AssertionError("GPKG connectors differ from positive-distance snaps")
    for row in connectors.itertuples():
        case = cases[row.case_id]
        selected = case["snap"]["selected"]
        points = list(row.geometry.coords)
        if row.charged_seconds != 0 or abs(row.distance_ft-selected["distance_ft"]) > 1e-9 or points[0] != tuple(case["origin_lonlat"]) or math.dist(points[-1], tuple(selected["point"])) > 1e-12:
            raise AssertionError(f"GPKG connector attributes/endpoints differ: {row.case_id}")
    expected_reached = {}
    for case in cases.values():
        key = case["network_key"]
        network = networks[key]
        for answer in case["answers"]:
            if answer["intervals_ft"] is None:
                continue
            for identity, spans in answer["intervals_ft"].items():
                record = network["records"][identity]
                for low, high in spans:
                    expected_reached[(case["id"], answer["minutes"], identity, low, high)] = record
    reached = loaded["reached_streets"]
    actual_keys = set()
    for row in reached.itertuples():
        key = (row.case_id, row.minutes, row.candidate_id, row.from_ft, row.to_ft)
        if key in actual_keys or key not in expected_reached:
            raise AssertionError(f"Unexpected/duplicate GPKG reached interval: {key}")
        actual_keys.add(key)
        record = expected_reached[key]
        if (row.from_node_id, row.to_node_id, row.direction) != (record["from"], record["to"], record["dir"]):
            raise AssertionError(f"GPKG reached segment attributes differ: {key}")
        if abs(row.length_ft-(row.to_ft-row.from_ft)) > 1e-9:
            raise AssertionError(f"GPKG reached length differs: {key}")
        steps = max(1, math.ceil((row.to_ft-row.from_ft)/50))
        expected_coords = [interpolate_fraction_independent(record["coords"], (row.from_ft+(row.to_ft-row.from_ft)*i/steps)/record["len_ft"])
                           for i in range(steps+1)]
        got_coords = list(row.geometry.coords)
        if row.geometry.geom_type != "LineString" or len(got_coords) != len(expected_coords):
            raise AssertionError(f"GPKG reached display geometry vertex count differs: {key}")
        if any(math.dist(actual, expected) > 2e-12 for actual, expected in zip(got_coords, expected_coords)):
            raise AssertionError(f"GPKG reached display geometry coordinates differ: {key}")
        for a, b in zip(got_coords, got_coords[1:]):
            if geod.inv(*a, *b)[2] > 50.001:
                raise AssertionError(f"GPKG display chord exceeds 50 ft: {key}")
    if actual_keys != set(expected_reached):
        raise AssertionError(f"GPKG reached intervals omitted: {len(set(expected_reached)-actual_keys)}")
    counts = {name: len(frame) for name, frame in loaded.items()}
    return counts


def interpolate_fraction_independent(coords, fraction):
    """Interpolate by source-vertex geodesic lengths without pipeline helpers."""
    lengths = [WGS84_FEET.inv(*a, *b)[2] for a, b in zip(coords, coords[1:])]
    total = math.fsum(lengths)
    target = fraction * total
    elapsed = 0.0
    for index, length in enumerate(lengths):
        if target <= elapsed + length or index == len(lengths)-1:
            azimuth, _, _ = WGS84_FEET.inv(*coords[index], *coords[index+1])
            return WGS84_FEET.fwd(*coords[index], azimuth, max(0.0, min(length, target-elapsed)))[:2]
        elapsed += length
    raise AssertionError("cannot interpolate empty geometry")


def verify(project_root: Path):
    tile_dir, manifest, source, tiled, coordinates = load_inputs(project_root)
    boundary_nodes = tuple(sorted(node_id for node_id, (lon, lat) in coordinates.items()
                                  if lon <= EXTRACT_BBOX[0] or lon >= EXTRACT_BBOX[2]
                                  or lat <= EXTRACT_BBOX[1] or lat >= EXTRACT_BBOX[3]))
    readiness = Readiness(coverage="not_established", frontier_nodes=boundary_nodes)
    report = {"source_segments": len(source), "tiled_unique_segments": len(tiled),
              "tile_files": len(manifest["tiles"]), "cases": []}
    for case_id, point in CASE_POINTS.items():
        tile_snap = snap_origin(tiled, coordinates, point)
        source_snap = snap_origin(source, coordinates, point)
        if tile_snap.as_dict() != source_snap.as_dict():
            raise AssertionError(f"{case_id}: source/tile snap mismatch")
        row = {"case": case_id, "snap_status": tile_snap.status,
               "selected_segment": tile_snap.selected.candidate_id if tile_snap.selected else None,
               "snap_distance_ft": tile_snap.selected.distance_ft if tile_snap.selected else None,
               "budgets": []}
        if tile_snap.selected is None:
            if case_id != "D02" or tile_snap.status != "off_network":
                raise AssertionError(f"{case_id}: unexpected snap rejection")
            row["budgets"] = [{"budget_ft": budget, "status": "off_network",
                               "reached_segment_count": None, "reached_length_ft": None}
                              for budget in BUDGETS_FT]
        else:
            for budget in BUDGETS_FT:
                tile_intervals, tile_distances = independent_dijkstra(tiled, tile_snap.selected, budget)
                source_intervals, source_distances = independent_dijkstra(source, source_snap.selected, budget)
                if (tile_intervals, tile_distances) != (source_intervals, source_distances):
                    raise AssertionError(f"{case_id}/{budget}: independent source/tile Dijkstra mismatch")
                expected = traverse_reference(tiled, tile_snap.selected, budget, readiness)
                if expected.intervals_ft != tile_intervals:
                    raise AssertionError(f"{case_id}/{budget}: independent Dijkstra intervals differ")
                expected_frontier = boundary_frontier(boundary_nodes, tile_distances, budget)
                if expected.frontier != dict(sorted(expected_frontier.items())):
                    raise AssertionError(f"{case_id}/{budget}: extract-boundary frontier differs")
                total = math.fsum(high - low for identity in sorted(tile_intervals)
                                  for low, high in tile_intervals[identity])
                row["budgets"].append({"budget_ft": budget, "status": expected.computation_status,
                    "reached_segment_count": len(tile_intervals), "reached_length_ft": total,
                    "reached_frontier_nodes": len(expected_frontier), "independent_match": True})
        report["cases"].append(row)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--samples-index", type=Path)
    parser.add_argument("--references", type=Path)
    args = parser.parse_args()
    root = args.project_root.resolve()
    if args.samples_index:
        index = checked_path(root, args.samples_index)
        references = checked_path(root, args.references) if args.references else None
        report = verify_samples(root, index, references)
    else:
        report = verify(root)
    print(json.dumps(report, indent=2, allow_nan=False))

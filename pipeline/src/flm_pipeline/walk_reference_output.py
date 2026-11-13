"""Local Step 3 references and reopened GeoPackage inspection output."""
from __future__ import annotations

from dataclasses import asdict
import argparse
import json
import math
from pathlib import Path
import tempfile
import time

from .routing import Readiness, Segment
from .walk_tiles import _json, _check_schema, _schema, _sha, verify_records

ROOT = Path(__file__).resolve().parents[3]
CASES = (
    ("D01", "Denver Union Station", (-105.0004685, 39.7529095), "denver"),
    ("G01", "Greeley Lincoln Park", (-104.6928167, 40.4249), "G01"),
    ("B01", "Broomfield Library", (-105.06877, 39.91758), "B01"),
    ("C01", "Commerce City/72nd station", (-104.943057, 39.826361), "denver"),
    ("F01", "Fraser Town Hall", (-105.81945, 39.94776), "F01"),
    ("D02", "Sloan's Lake rejection control", (-105.049, 39.748), "denver"),
)
BUDGETS = ((5, 1232), (10, 2464), (15, 3696))


def _rows(path):
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def _path(value):
    result = Path(value)
    return result if result.is_absolute() else ROOT / result


def load_network(tile_directory, *, package_directory=None, graph_directory=None, extraction_directory):
    """Validate tiles against the source graph, then reconstruct from disk tiles."""
    tile_directory = Path(tile_directory)
    manifest = _json(tile_directory / "manifest.json")
    _check_schema(manifest, _schema("manifest.schema.json"), "manifest")
    if package_directory:
        directory = Path(package_directory)
        source_manifest = _json(directory / "manifest.json")
        for kind in ("segments", "nodes", "arcs"):
            item = source_manifest["files"][kind]
            path = directory / item["path"]
            if path.stat().st_size != item["bytes"] or _sha(path) != item["sha256"]:
                raise ValueError(f"source package file changed: {kind}")
        segments = _json(directory / "segments.json")["segments"]
        nodes = _json(directory / "nodes.json")["nodes"]
        arcs = _json(directory / "arcs.json")["arcs"]
        extract = _json(Path(extraction_directory) / "extraction.json")
        bbox = extract["coverage"]["extract_bbox"]
    else:
        directory = Path(graph_directory)
        report = _json(directory / "run-report.json")
        if report.get("report_version") != "experimental-routing-graph-1" or not {
            "nodes.jsonl", "segments.jsonl", "arcs.jsonl", "routing.gpkg"
        } <= report.get("output_files", {}).keys():
            raise ValueError("missing completed source graph file manifest")
        if not report.get("checks") or not all(value is True for value in report["checks"].values()):
            raise ValueError("source graph has failed completion checks")
        for name, item in report.get("output_files", {}).items():
            if Path(name).name != name:
                raise ValueError("unsafe graph source path")
            path = directory / name
            if path.stat().st_size != item["bytes"] or _sha(path) != item["sha256"]:
                raise ValueError(f"source graph file changed: {name}")
        segments = [r for r in _rows(directory / "segments.jsonl") if r["eligibility"] == "include"]
        nodes = [{"node_id": r["node_id"], "coordinate": [r["lon"], r["lat"]]} for r in _rows(directory / "nodes.jsonl")]
        arcs = list(_rows(directory / "arcs.jsonl"))
        bbox = _json(directory / "run-report.json")["coverage"]["extract_bbox"]
    extraction_directory = Path(extraction_directory)
    extraction = _json(extraction_directory / "extraction.json")
    for name in ("nodes.jsonl", "ways.jsonl", "relations.jsonl"):
        item = extraction["files"][name]
        path = extraction_directory / name
        if path.stat().st_size != item["bytes"] or _sha(path) != item["sha256"]:
            raise ValueError(f"extraction source file changed: {name}")
    ways = {r["osm_id"]: r for r in _rows(extraction_directory / "ways.jsonl")}
    verification = verify_records(segments, nodes, arcs, ways, tile_directory, manifest)
    records = {}
    for entry in manifest["tiles"]:
        for record in _json(tile_directory / entry["path"])["segments"]:
            records[record["id"]] = record
    coordinates = {}
    rebuilt = []
    for identity, record in sorted(records.items()):
        rebuilt.append(Segment(identity, record["from"], record["to"], record["len_ft"], record["dir"]))
        for node, point in zip((record["from"], record["to"]), record["coords"]):
            if node in coordinates and coordinates[node] != tuple(point):
                raise ValueError("source node has inconsistent tile coordinates")
            coordinates[node] = tuple(point)
    source_segments = [Segment(s["candidate_id"], s["from_node_id"], s["to_node_id"], s["length_ft"], s["direction"]) for s in segments]
    frontier = tuple(sorted(n for n, (x, y) in coordinates.items() if x <= bbox[0] or x >= bbox[2] or y <= bbox[1] or y >= bbox[3]))
    readiness = Readiness(("source_policy_and_coverage_limitations",), "not_established", frontier)
    return {"segments": rebuilt, "coordinates": coordinates, "source_segments": source_segments,
            "readiness": readiness, "verification": verification, "manifest": manifest, "extract_bbox": bbox,
            "tile_directory": str(tile_directory.resolve()), "records": records}


def _write_gpkg(path, cases, networks):
    import geopandas as gpd
    import pyogrio
    from shapely.geometry import Point, LineString
    from .walk_reference import interpolate_fraction
    origins, snaps, connectors, reached = [], [], [], []
    for case in cases:
        common = {"case_id": case["id"], "name": case["name"], "snap_status": case["snap"]["status"]}
        origins.append({**common, "geometry": Point(case["origin_lonlat"])})
        selected = case["snap"]["selected"]
        if selected is None:
            continue
        snaps.append({**common, "candidate_id": selected["candidate_id"], "distance_ft": selected["distance_ft"],
                      "offset_ft": selected["offset_ft"], "geometry": Point(selected["point"])})
        if selected["distance_ft"] > 0:
            connectors.append({**common, "distance_ft": selected["distance_ft"], "charged_seconds": 0,
                               "geometry": LineString([case["origin_lonlat"], selected["point"]])})
        network = networks[case["network_key"]]
        for answer in case["answers"]:
            for identity, intervals in answer["intervals_ft"].items():
                record = network["records"][identity]
                for low, high in intervals:
                    # Densification is a display approximation; analytical offsets remain exact.
                    steps = max(1, math.ceil((high - low) / 50))
                    fractions = []
                    for i in range(steps + 1):
                        if i == 0:
                            offset = low
                        elif i == steps:
                            offset = high
                        else:
                            offset = low + (high - low) * (i / steps)
                        fractions.append(offset / record["len_ft"])
                    points = [interpolate_fraction(*record["coords"], fraction) for fraction in fractions]
                    reached.append({"case_id": case["id"], "minutes": answer["minutes"], "candidate_id": identity,
                                    "from_node_id": record["from"], "to_node_id": record["to"], "direction": record["dir"],
                                    "from_ft": low, "to_ft": high, "length_ft": high-low, "geometry": LineString(points)})
    expected = {}
    for name, records in (("origins", origins), ("snaps", snaps), ("connectors", connectors), ("reached_streets", reached)):
        if not records:
            continue
        frame = gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")
        frame.to_file(path, layer=name, driver="GPKG", engine="pyogrio")
        expected[name] = frame
    if {r[0] for r in pyogrio.list_layers(path)} != set(expected):
        raise ValueError("GeoPackage layer membership mismatch")
    for name, frame in expected.items():
        actual = gpd.read_file(path, layer=name, engine="pyogrio")
        if actual.crs.to_epsg() != 4326 or len(actual) != len(frame):
            raise ValueError(f"GeoPackage CRS/count mismatch: {name}")
        for column in frame.columns:
            if column == "geometry":
                if not all(a.equals_exact(b, 0) for a, b in zip(actual.geometry, frame.geometry)):
                    raise ValueError(f"GeoPackage geometry mismatch: {name}")
            elif actual[column].tolist() != frame[column].tolist():
                raise ValueError(f"GeoPackage attribute mismatch: {name}/{column}")
    return {name: len(frame) for name, frame in expected.items()}


def run_reference(samples_index, output_directory):
    from .walk_reference import snap_origin, traverse_reference
    started = time.perf_counter()
    output = Path(output_directory)
    if output.exists():
        raise ValueError("reference output already exists; choose a new directory")
    index = _json(Path(samples_index))
    networks = {"denver": load_network(
        ROOT / "data/generated/prototype/walk-tiles/denver-policy03-walk-tiles-20261111-imperial",
        package_directory=ROOT / "data/generated/prototype/network-packages/denver-policy03-task52-20261104-e",
        extraction_directory=ROOT / "data/generated/prototype/20261103T192505Z-fcf6a557")}
    for key in ("G01", "B01", "F01"):
        item = index["cases"][key]
        networks[key] = load_network(_path(item["tile_directory"]), graph_directory=_path(item["graph_directory"]),
                                     extraction_directory=_path(item["extraction_directory"]))
    cases = []
    for identity, name, point, key in CASES:
        network = networks[key]
        print(f"Snapping {identity}: {len(network['segments']):,} unique segments", flush=True)
        snap = snap_origin(network["segments"], network["coordinates"], point)
        # Source order intentionally differs; this also checks deterministic selection.
        source_snap = snap_origin(list(reversed(network["source_segments"])), network["coordinates"], point)
        if snap.as_dict() != source_snap.as_dict():
            raise ValueError(f"tile/source snapping mismatch: {identity}")
        case = {"id": identity, "name": name, "origin_lonlat": list(point), "network_key": key,
                "snap": snap.as_dict(), "answers": [], "coverage_readiness": "not_established"}
        if snap.selected is not None:
            for minutes, budget in BUDGETS:
                result = traverse_reference(network["segments"], snap.selected, budget, network["readiness"])
                source = traverse_reference(network["source_segments"], source_snap.selected, budget, network["readiness"])
                if asdict(result) != asdict(source) or result.intervals_ft is None:
                    raise ValueError(f"tile/source traversal mismatch or failure: {identity}/{minutes}")
                case["answers"].append({"minutes": minutes, "budget_ft": budget,
                    "status": result.computation_status, "reached_segment_count": len(result.intervals_ft),
                    "total_reached_length_ft": math.fsum(high-low for sid in sorted(result.intervals_ft) for low, high in result.intervals_ft[sid]),
                    "intervals_ft": dict(sorted(result.intervals_ft.items())),
                    "reached_frontier_remaining_ft": dict(sorted(result.frontier.items()))})
        else:
            case["rejection_reason"] = "No included network location within 500 feet; no traversal was executed."
            case["answers"] = [{"minutes": minutes, "budget_ft": budget, "status": snap.status,
                "reached_segment_count": None, "total_reached_length_ft": None, "intervals_ft": None} for minutes, budget in BUDGETS]
        cases.append(case)
        print(f"{identity}: {snap.status}", flush=True)
    if any(c["snap"]["status"] != ("off_network" if c["id"] == "D02" else "resolved") for c in cases):
        raise ValueError("case did not produce its approved positive/rejection role")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".walk-reference-", dir=output.parent))
    try:
        reference = staging / "reference"
        reference.mkdir()
        payload = {"format": "walk-reference", "version": 1, "method": "plan-a-step3-geodesic-foot-1",
            "crs": "EPSG:4326", "coordinate_order": "longitude_latitude", "length_unit": "international_foot",
            "speed_mph": 2.8, "snap_limit_ft": 500, "connector_charged_seconds": 0,
            "coverage_readiness": "not_established", "human_visual_review": "not_run", "cases": cases,
            "networks": {k: {"tile_directory": n["tile_directory"], "release_id": n["manifest"]["release_id"],
                "extract_bbox": n["extract_bbox"], "reconstruction": n["verification"],
                "limitations": n["manifest"]["limitations"]} for k, n in networks.items()}}
        path = reference / "cases.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
        if _json(path) != json.loads(json.dumps(payload)):
            raise ValueError("reopened cases differ")
        layers = _write_gpkg(reference / "walk-reference.gpkg", cases, networks)
        (reference / "validation.json").write_text(json.dumps({"checks": {
            "source_tile_reconstruction": "pass", "source_tile_snap_and_traversal": "pass", "gpkg_all_records_reopened": "pass"},
            "layers": layers, "elapsed_seconds": time.perf_counter()-started,
            "manual_viewer_import": "not_run", "coverage_completeness": "not_established"}, indent=2)+"\n", encoding="utf-8")
        staging.rename(output)
    except Exception:
        # Keep diagnostic staging files; never replace a previous release.
        raise
    return output / "reference/cases.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples-index", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    print(run_reference(args.samples_index, args.output), flush=True)
    return 0

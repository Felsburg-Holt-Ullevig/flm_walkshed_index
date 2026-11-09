"""Experimental directed multigraph assembly; JSONL is independent of graph libraries."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import json
import math
import os
from pathlib import Path
import sqlite3
import time
import uuid

from pyproj import Geod

from .classification import (
    _candidate_record, _hash_file, _json_bytes, _jsonl, _load_object,
    _validate_inputs, _write_json,
)
from .code_identity import code_identity
from .pedestrian_config import load_pedestrian_settings
from .pedestrian_policy import evaluate_node, evaluate_way


GRAPH_VERSION = "experimental-routing-graph-1"
ROOT = Path(__file__).resolve().parents[3]
GEOD = Geod(ellps="WGS84")


class GraphError(RuntimeError):
    """A provenance, topology, geometry, or structural invariant failed."""


def _require(condition, message):
    if not condition:
        raise GraphError(message)


def base_seconds(length_ft, speed_mph):
    for value in (length_ft, speed_mph):
        _require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value), "Length and speed must be finite numbers")
    _require(length_ft >= 0 and speed_mph > 0, "Length must be nonnegative and speed positive")
    result = length_ft * 3600 / (speed_mph * 5280)
    _require(math.isfinite(result), "Computed cost must be finite")
    return result


def _length(coordinates):
    _require(isinstance(coordinates, list) and len(coordinates) == 2, "A segment requires two WGS84 coordinates")
    for xy in coordinates:
        _require(isinstance(xy, list) and len(xy) == 2, "Invalid coordinate pair")
        _require(all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in xy), "Nonfinite coordinate")
        _require(-180 <= xy[0] <= 180 and -90 <= xy[1] <= 90, "Coordinate outside WGS84 bounds")
    _, _, meters = GEOD.inv(*coordinates[0], *coordinates[1])
    feet = meters / 0.3048
    _require(math.isfinite(feet) and feet >= 0, "Invalid geodesic length")
    return feet


def _close(actual, expected):
    return isinstance(actual, (int, float)) and not isinstance(actual, bool) and math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-9)


def relation_audit(row):
    """Flag unsupported walking restrictions without implementing turn semantics."""
    tags = row["tags"]
    foot_exempt = "foot" in tags.get("except", "").split(";")
    unsupported = (
        "restriction:foot" in tags or "restriction:foot:conditional" in tags
        or (tags.get("type") == "restriction" and not foot_exempt)
    )
    return {"relation_id": row["osm_id"], "unsupported": unsupported,
            "reason_codes": ["R_UNSUPPORTED"] if unsupported else [],
            "unresolved_members": sum(not member["resolved"] for member in row["members"]),
            "tags": tags, "members": row["members"]}


def _expected_arcs(segment):
    if segment["eligibility"] != "include":
        return []
    rows = []
    for direction in ("forward", "reverse"):
        if segment["direction"] not in {"both", direction}:
            continue
        reverse = direction == "reverse"
        rows.append({
            "edge_id": segment["candidate_id"] + "/" + direction,
            "candidate_id": segment["candidate_id"], "way_id": segment["way_id"],
            "sequence": segment["sequence"], "direction": direction,
            "from_node_id": segment["to_node_id"] if reverse else segment["from_node_id"],
            "to_node_id": segment["from_node_id"] if reverse else segment["to_node_id"],
            "coordinates": list(reversed(segment["coordinates"])) if reverse else segment["coordinates"],
            "length_ft": segment["length_ft"], "base_seconds": segment["base_seconds"],
        })
    return rows


def _inspect_gpkg(directory, write):
    """Bounded batches, then independently reopen every GIS record and geometry."""
    import geopandas as gpd
    import pandas as pd
    import pyogrio
    from shapely.geometry import LineString, Point

    path = directory / "routing.gpkg"
    layers = {
        "routing_nodes": ("nodes.jsonl", ["node_id"], ["lon", "lat"]),
        "routing_arcs": ("arcs.jsonl", ["edge_id", "candidate_id", "way_id", "from_node_id", "to_node_id", "direction"], ["sequence", "length_ft", "base_seconds"]),
        "candidate_audit": ("segments.jsonl", ["candidate_id", "way_id", "from_node_id", "to_node_id", "direction", "eligibility", "reason_codes", "warnings"], ["sequence", "length_ft"]),
    }
    for layer, (filename, text_fields, numeric_fields) in layers.items():
        def batches():
            batch = []
            for _, row in _jsonl(directory / filename, filename):
                batch.append(row)
                if len(batch) == 10000:
                    yield batch
                    batch = []
            if batch:
                yield batch

        def fields(row):
            return {key: json.dumps(row[key], ensure_ascii=False, separators=(",", ":")) if isinstance(row[key], list) else row[key] for key in text_fields + numeric_fields}

        def geometry(row):
            if layer == "routing_nodes":
                return Point(row["lon"], row["lat"])
            return LineString(row["coordinates"])

        if write:
            first = True
            for batch in batches():
                frame = gpd.GeoDataFrame([fields(row) for row in batch], geometry=[geometry(row) for row in batch], crs="EPSG:4326")
                pyogrio.write_dataframe(frame, path, layer=layer, driver="GPKG", append=not first)
                first = False
            if first:
                frame = gpd.GeoDataFrame({**{key: pd.Series(dtype="str") for key in text_fields}, **{key: pd.Series(dtype="float64") for key in numeric_fields}}, geometry=gpd.GeoSeries([], crs="EPSG:4326"))
                pyogrio.write_dataframe(frame, path, layer=layer, driver="GPKG", geometry_type="Point" if layer == "routing_nodes" else "LineString")
        info = pyogrio.read_info(path, layer=layer)
        _require(info["crs"] == "EPSG:4326", f"GIS CRS mismatch: {layer}")
        offset = 0
        for batch in batches():
            frame = pyogrio.read_dataframe(path, layer=layer, skip_features=offset, max_features=len(batch))
            _require(len(frame) == len(batch), f"GIS row count mismatch: {layer}")
            for actual, expected in zip(frame.to_dict("records"), batch, strict=True):
                for key, value in fields(expected).items():
                    _require(actual[key] == value, f"GIS field mismatch: {layer}/{key}")
                _require(list(actual["geometry"].coords) == list(geometry(expected).coords), f"GIS geometry mismatch: {layer}")
            offset += len(batch)
        _require(info["features"] == offset, f"GIS total count mismatch: {layer}")


def validate_graph(directory, speed_mph):
    """Reopen graph; validate IDs, multiedge membership, cost, direction and geometry."""
    directory = Path(directory)
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE nodes(id TEXT PRIMARY KEY, lon REAL, lat REAL, used INTEGER DEFAULT 0)")
    node_count = arc_count = 0
    try:
        for _, row in _jsonl(directory / "nodes.jsonl", "graph node"):
            _require(set(row) == {"node_id", "lon", "lat"}, "Unexpected graph node fields")
            node_id = row["node_id"]
            _require(isinstance(node_id, str) and node_id.isascii() and node_id.isdecimal() and not node_id.startswith("0"), "Invalid graph node ID")
            _length([[row["lon"], row["lat"]], [row["lon"], row["lat"]]])
            connection.execute("INSERT INTO nodes(id,lon,lat) VALUES (?,?,?)", (node_id, row["lon"], row["lat"]))
            node_count += 1
        arcs = (row for _, row in _jsonl(directory / "arcs.jsonl", "graph arc"))
        status = Counter()
        last_key = None
        for _, segment in _jsonl(directory / "segments.jsonl", "candidate audit"):
            way_id, sequence = segment["way_id"], segment["sequence"]
            _require(isinstance(way_id, str) and way_id.isascii() and way_id.isdecimal() and not way_id.startswith("0"), "Invalid segment way ID")
            _require(type(sequence) is int and sequence >= 0, "Invalid segment sequence")
            key = (len(way_id), way_id, sequence)
            _require(last_key is None or key > last_key, "Duplicate or unordered candidate")
            last_key = key
            _require(segment["candidate_id"] == f"way/{way_id}/segment/{sequence}", "Candidate ID disagrees with source sequence")
            length_ft = _length(segment["coordinates"])
            _require(_close(segment["length_ft"], length_ft), "Segment length mismatch")
            _require(segment["eligibility"] in {"include", "exclude", "unknown"}, "Invalid candidate disposition")
            _require(segment["geometry_check"] == "pass" and segment["routing_ready"] is (segment["eligibility"] == "include"), "Candidate geometry/readiness mismatch")
            status[segment["eligibility"]] += 1
            if segment["eligibility"] == "include":
                _require(length_ft > 0 and segment["from_node_id"] != segment["to_node_id"], "Zero-length edge included")
                _require(segment["direction"] in {"both", "forward", "reverse"}, "Invalid included direction")
                _require(_close(segment["base_seconds"], base_seconds(length_ft, speed_mph)), "Segment cost mismatch")
                for index, endpoint in enumerate((segment["from_node_id"], segment["to_node_id"])):
                    node = connection.execute("SELECT lon,lat FROM nodes WHERE id=?", (endpoint,)).fetchone()
                    _require(node is not None and list(node) == segment["coordinates"][index], "Graph endpoint reference/geometry mismatch")
                    connection.execute("UPDATE nodes SET used=1 WHERE id=?", (endpoint,))
            else:
                expected_direction = "none" if segment["eligibility"] == "exclude" else "unknown"
                _require(segment["base_seconds"] is None and segment["direction"] == expected_direction, "Excluded/unknown candidate has cost or direction")
            for expected in _expected_arcs(segment):
                actual = next(arcs, None)
                _require(actual == expected, "Arc membership, direction, geometry, or cost mismatch")
                arc_count += 1
        _require(next(arcs, None) is None, "Extra arc or excluded candidate routed")
        used = connection.execute("SELECT COUNT(*) FROM nodes WHERE used=1").fetchone()[0]
        _require(used == node_count, "Unused graph node")
        return {"nodes": node_count, "directed_arcs": arc_count, "candidates": sum(status.values()), "candidates_by_eligibility": dict(sorted(status.items()))}
    except sqlite3.IntegrityError as error:
        raise GraphError("Duplicate graph node ID") from error
    finally:
        connection.close()


def build_graph(extraction_path, classification_path, policy_config_path, stage, progress=None):
    """Build and verify a staged product. Only the supervised parent may promote it."""
    extraction = Path(extraction_path).resolve()
    classification = Path(classification_path).resolve()
    stage = Path(stage)
    stage.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    identity = code_identity()
    settings = load_pedestrian_settings(policy_config_path)
    authority = ROOT / settings.rule_authority
    authority_hash = _hash_file(authority)
    metadata, _, extraction_hashes = _validate_inputs(extraction)
    report = _load_object(classification / "run-report.json", "classification report")
    classification_hashes = {"run-report.json": _hash_file(classification / "run-report.json")}
    _require(report.get("report_version") == "pedestrian-classification-1" and report.get("status") in {"classification_complete", "classification_complete_with_unknowns"}, "Classification is not complete")
    _require(report.get("implementation_identity") == identity, "Classification identity is stale; rerun classify")
    _require(report["policy"]["config_sha256"] == settings.config_sha256 and report["policy"]["authority_sha256"] == authority_hash, "Classification policy/config mismatch")
    _require(report["inputs"]["file_sha256"] == extraction_hashes, "Classification belongs to a different extraction")
    _require(report.get("checks") and all(v is True for v in report["checks"].values()), "Classification completion checks failed")
    for name, item in report["output_files"].items():
        _require(Path(name).name == name, "Invalid classification output path")
        path = classification / name
        _require(path.stat().st_size == item["bytes"] and _hash_file(path) == item["sha256"], f"Classification output hash mismatch: {name}")
        classification_hashes[name] = item["sha256"]
    connection = sqlite3.connect(stage / "index.sqlite")
    connection.execute("CREATE TABLE nodes(id TEXT PRIMARY KEY, lon REAL, lat REAL, tags TEXT, used INTEGER DEFAULT 0)")
    connection.execute("CREATE TABLE geometry(a TEXT,b TEXT, PRIMARY KEY(a,b))")
    duplicate_count = 0
    status = Counter()
    lengths = Counter()
    arc_count = 0
    try:
        for _, row in _jsonl(extraction / "nodes.jsonl", "source node"):
            _length([[row["lon"], row["lat"]], [row["lon"], row["lat"]]])
            connection.execute("INSERT INTO nodes(id,lon,lat,tags) VALUES (?,?,?,?)", (row["osm_id"], row["lon"], row["lat"], json.dumps(row["tags"])))
        connection.commit()
        candidates = (row for _, row in _jsonl(classification / "candidates-classified.jsonl", "classification candidate"))
        with (stage / "segments.jsonl").open("wb") as segments, (stage / "arcs.jsonl").open("wb") as arcs:
            for way_number, (_, way) in enumerate(_jsonl(extraction / "ways.jsonl", "source way"), 1):
                refs = way["node_refs"]
                evaluation = evaluate_way(way["osm_id"], refs, way["tags"])
                nodes = {}
                for ref in set(refs):
                    record = connection.execute("SELECT lon,lat,tags FROM nodes WHERE id=?", (ref,)).fetchone()
                    _require(record is not None, f"Missing source node {ref}")
                    nodes[ref] = record
                node_results = {ref: evaluate_node(ref, json.loads(row[2])) for ref, row in nodes.items()}
                for sequence in range(len(refs) - 1):
                    expected = _candidate_record(way["osm_id"], sequence, refs, evaluation, node_results)
                    candidate = next(candidates, None)
                    _require(candidate == expected, "Classification candidate disagrees with source and accepted policy")
                    coords = [list(nodes[ref][:2]) for ref in refs[sequence:sequence + 2]]
                    length_ft = _length(coords)
                    if length_ft == 0 or refs[sequence] == refs[sequence + 1]:
                        candidate.update(eligibility="exclude", direction="none")
                        if "G_ZERO_LENGTH" not in candidate["reason_codes"]:
                            candidate["reason_codes"].append("G_ZERO_LENGTH")
                    # Geometry coincidence is evidence only; IDs never merge.
                    geometry_key = sorted(_json_bytes(xy).decode() for xy in coords)
                    inserted = connection.execute("INSERT OR IGNORE INTO geometry VALUES (?,?)", geometry_key).rowcount
                    if not inserted:
                        duplicate_count += 1
                        candidate["warnings"].append("W_DUPLICATE_GEOMETRY")
                    candidate.update(coordinates=coords, length_ft=length_ft, geometry_check="pass", routing_ready=candidate["eligibility"] == "include",
                                     base_seconds=base_seconds(length_ft, settings.speed_mph) if candidate["eligibility"] == "include" else None)
                    segments.write(_json_bytes(candidate) + b"\n")
                    status[candidate["eligibility"]] += 1
                    lengths[candidate["eligibility"]] += length_ft
                    for arc in _expected_arcs(candidate):
                        arcs.write(_json_bytes(arc) + b"\n")
                        arc_count += 1
                    if candidate["eligibility"] == "include":
                        connection.executemany("UPDATE nodes SET used=1 WHERE id=?", [(ref,) for ref in refs[sequence:sequence + 2]])
                if way_number % 10000 == 0:
                    connection.commit()
                    if progress:
                        progress(f"Assembled {way_number:,} ways; {arc_count:,} directed arcs")
            _require(next(candidates, None) is None, "Classification contains extra candidates")
        connection.commit()
        with (stage / "nodes.jsonl").open("wb") as stream:
            for node_id, lon, lat in connection.execute("SELECT id,lon,lat FROM nodes WHERE used=1 ORDER BY length(id),id"):
                stream.write(_json_bytes({"node_id": node_id, "lon": lon, "lat": lat}) + b"\n")
    finally:
        connection.close()
    (stage / "index.sqlite").unlink()
    relation_counts = Counter()
    with (stage / "relations-audit.jsonl").open("wb") as stream:
        for _, row in _jsonl(extraction / "relations.jsonl", "source relation"):
            audit = relation_audit(row)
            stream.write(_json_bytes(audit) + b"\n")
            relation_counts["retained"] += 1
            relation_counts["unsupported"] += audit["unsupported"]
            relation_counts["unresolved_members"] += audit["unresolved_members"]
    counts = validate_graph(stage, settings.speed_mph)
    _require(counts["candidates"] == report["counts"]["ordered_pair_candidates"] and counts["directed_arcs"] == arc_count, "Graph/source count reconciliation failed")
    if progress:
        progress("Writing and reopening routing GeoPackage")
    _inspect_gpkg(stage, write=True)
    for directory, hashes in ((extraction, extraction_hashes), (classification, classification_hashes)):
        for name, digest in hashes.items():
            _require(_hash_file(directory / name) == digest, "Input changed during graph construction")
    _require(code_identity() == identity and _hash_file(authority) == authority_hash and _hash_file(settings.config_path) == settings.config_sha256, "Implementation or policy changed during graph construction")
    incomplete = status["unknown"] > 0 or relation_counts["unsupported"] > 0
    graph_status = "incomplete_unknown_policy" if incomplete else "experimental_graph_complete"
    if not arc_count:
        graph_status = "empty"
    return {
        "report_version": GRAPH_VERSION, "status": graph_status,
        "analytical_promotion": "blocked_empty" if not arc_count else "blocked" if incomplete else "pending_gate_3_and_coverage_validation",
        "counts": {**counts, "duplicate_geometry_candidates": duplicate_count},
        "source_segment_length_ft_by_eligibility": dict(sorted(lengths.items())),
        "relations": dict(relation_counts), "coverage": metadata.get("coverage"),
        "inputs": {"source": metadata["source"], "extraction_directory": str(extraction), "extraction_hashes": extraction_hashes,
                   "classification_directory": str(classification), "classification_hashes": classification_hashes},
        "policy": {"rule_version": settings.rule_version, "scenario_id": settings.scenario_id,
                   "travel_profile": "general_pedestrian", "wheelchair_accessibility": "not_evaluated",
                   "config_sha256": settings.config_sha256, "authority_sha256": authority_hash,
                   "length_unit": "international_foot", "time_unit": "second", "speed_mph": settings.speed_mph,
                   "crossing_delay_model": "not_modeled", "steps_cost_model": settings.steps_cost_model, "slope_cost_model": "not_modeled"},
        "implementation_identity": identity,
        "checks": {"source_classification_replayed": True, "input_hashes_verified_before_after": True,
                   "structural_validation": True, "gpkg_all_records_reopened": True, "counts_reconciled": True},
        "output_files": {p.name: {"bytes": p.stat().st_size, "sha256": _hash_file(p)} for p in sorted(stage.iterdir()) if p.is_file()},
        "duration_seconds": round(time.monotonic() - started, 3),
        "limitations": ["Experimental distance-derived base times; no crossing, slope, stair or turn delays.",
                        "Unknown segments omitted; unsupported walking restrictions block analytical promotion.",
                        "Complete ways do not establish complete routes; expanded coverage comparison remains pending.",
                        "No routing, origin snapping, geometry repair, simplification or publication performed.",
                        "Source extraction is historical hash-verified evidence; raw PBF not reprocessed or rehashed."],
    }


def run_graph(extraction, classification, policy_config, output_root=None):
    """Supervise graph worker under the accepted 20-minute/4-GiB limits."""
    import sys
    from .cli import _supervise, _promote_directory

    output = Path(output_root).resolve() if output_root else ROOT / "data/generated/prototype/routing-graph"
    _require(output.is_relative_to(ROOT) and not output.is_relative_to(ROOT / "data/raw"), "Graph output must stay in repository outside data/raw")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    stage = ROOT / "data/staging/prototype" / ("routing-graph-" + run_id)
    stage.mkdir(parents=True)
    candidate = stage / "candidate"
    result = stage / "worker-result.json"
    command = [sys.executable, "-m", "flm_pipeline", "_graph-worker", "--extraction", str(Path(extraction).resolve()),
               "--classification", str(Path(classification).resolve()), "--policy-config", str(Path(policy_config).resolve()), "--stage", str(candidate), "--result", str(result)]
    supervised = _supervise(command, ROOT, stage / "worker.log", 1200, 4 * 1024**3)
    if supervised["exit_code"] != 0 or supervised.get("failure_reason") or not supervised.get("child_cleanup_complete", False) or not result.exists():
        failure = {"status": "fail", "supervision": supervised, "staging_directory": str(stage)}
        _write_json(stage / "run-report.json", failure)
        return 1, failure
    try:
        report = _load_object(result, "graph worker result")
        _require(report.get("checks") and all(value is True for value in report["checks"].values()), "Graph worker validation checks failed")
        report.update(run_id=run_id, supervision=supervised)
        report["checks"].update(worker_exit_zero=True, resource_limits_passed=True)
        destination = output / run_id
        output.mkdir(parents=True, exist_ok=True)
        _require(not destination.exists(), "Refusing to overwrite graph run")
        _promote_directory(candidate, destination)
        for name, item in report["output_files"].items():
            _require(_hash_file(destination / name) == item["sha256"], "Promoted graph hash mismatch")
        report["run_report"] = (destination / "run-report.json").relative_to(ROOT).as_posix()
        _write_json(destination / "run-report.json.tmp", report)
        os.replace(destination / "run-report.json.tmp", destination / "run-report.json")
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        failure = {"status": "fail", "supervision": supervised, "staging_directory": str(stage), "errors": [str(error)]}
        _write_json(stage / "run-report.json", failure)
        return 1, failure
    return 0, {"status": report["status"], "run_id": run_id, "run_report": report["run_report"], "counts": report["counts"], "analytical_promotion": report["analytical_promotion"]}

"""Build and verify experimental fixed-grid pedestrian network tiles."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import time

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[3]
PACKAGE_REL = Path("data/generated/prototype/network-packages/denver-policy03-task52-20261104-e")
EXTRACT_REL = Path("data/generated/prototype/20261103T192505Z-fcf6a557")
TILE_SCHEMA_DIR = ROOT / "contracts/walk-tiles/v0"
SCALE = 10_000_000
CELL = 100_000
MAX_COL, MAX_ROW = 35_999, 17_999
SAFE_ID = re.compile(r"[A-Za-z0-9_-]+\Z")
EXPECTED = {"nodes": 248272, "segments": 312004, "arcs": 624008, "excluded": 24170, "unknown": 11645}


class WalkTilesError(RuntimeError):
    """Invalid source data, tile payload, or verification result."""


def _need(value: bool, message: str) -> None:
    if not value:
        raise WalkTilesError(message)


def _pairs(items):
    result = {}
    for key, value in items:
        _need(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value):
    raise WalkTilesError(f"nonfinite JSON value: {value}")


def _float(value):
    parsed = float(value)
    _need(math.isfinite(parsed), f"nonfinite JSON number: {value}")
    return parsed


def _integer(value):
    parsed = int(value)
    _need(abs(parsed) <= 9_007_199_254_740_991, f"unsafe JSON integer: {value}")
    return parsed


def _json(path: Path):
    _need(path.is_file() and not path.is_symlink(), f"missing or symlinked input: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_float, parse_int=_integer)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise WalkTilesError(f"invalid UTF-8 JSON at {path}: {exc}") from exc


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write(path: Path, value) -> bytes:
    data = (json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    path.write_bytes(data)
    return data


def _scaled(value) -> int:
    _need(type(value) in (int, float) and math.isfinite(value), "coordinate must be a finite JSON number")
    try:
        scaled = Decimal(str(value)) * SCALE
    except InvalidOperation as exc:
        raise WalkTilesError("invalid coordinate decimal") from exc
    _need(scaled == scaled.to_integral_value(), f"coordinate exceeds seven decimal places: {value}")
    result = int(scaled)
    _need(-180 * SCALE <= result <= 180 * SCALE, "longitude outside EPSG:4326 bounds")
    return result


def _orientation(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a, b, p):
    return _orientation(a, b, p) == 0 and min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])


def _segments_intersect(a, b, c, d):
    o1, o2, o3, o4 = _orientation(a, b, c), _orientation(a, b, d), _orientation(c, d, a), _orientation(c, d, b)
    if o1 == 0 and _on_segment(a, b, c): return True
    if o2 == 0 and _on_segment(a, b, d): return True
    if o3 == 0 and _on_segment(c, d, a): return True
    if o4 == 0 and _on_segment(c, d, b): return True
    return (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0)


def _line_touches_rect(a, b, x0, y0, x1, y1):
    if x0 <= a[0] <= x1 and y0 <= a[1] <= y1 or x0 <= b[0] <= x1 and y0 <= b[1] <= y1:
        return True
    edges = (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0)))
    return any(_segments_intersect(a, b, c, d) for c, d in edges)


def _point_candidates(point: tuple[int, int]):
    x, y = point
    col, row = (x + 180 * SCALE) // CELL, (y + 90 * SCALE) // CELL
    cols = {col - 1, col} if (x + 180 * SCALE) % CELL == 0 else {col}
    rows = {row - 1, row} if (y + 90 * SCALE) % CELL == 0 else {row}
    return {(c, r) for c in cols for r in rows if 0 <= c <= MAX_COL and 0 <= r <= MAX_ROW}


def _segment_membership(a, b):
    min_x, max_x = sorted((a[0], b[0])); min_y, max_y = sorted((a[1], b[1]))
    c0, c1 = (min_x + 180 * SCALE) // CELL, (max_x + 180 * SCALE) // CELL
    r0, r1 = (min_y + 90 * SCALE) // CELL, (max_y + 90 * SCALE) // CELL
    if (min_x + 180 * SCALE) % CELL == 0: c0 -= 1
    if (min_y + 90 * SCALE) % CELL == 0: r0 -= 1
    cells = set()
    for col in range(max(0, c0), min(MAX_COL, c1) + 1):
        for row in range(max(0, r0), min(MAX_ROW, r1) + 1):
            x0, y0 = col * CELL - 180 * SCALE, row * CELL - 90 * SCALE
            if _line_touches_rect(a, b, x0, y0, x0 + CELL, y0 + CELL):
                cells.add((col, row))
    _need(bool(cells), "segment geometry does not intersect a global grid cell")
    return cells


def tiles_for_coordinates(coords):
    """Return exact closed-cell membership for a longitude/latitude polyline."""
    _need(isinstance(coords, list) and len(coords) >= 2, "coordinates must contain at least two positions")
    points = []
    for pair in coords:
        _need(isinstance(pair, list) and len(pair) == 2, "invalid coordinate pair")
        x, y = _scaled(pair[0]), _scaled(pair[1])
        _need(-90 * SCALE <= y <= 90 * SCALE, "latitude outside EPSG:4326 bounds")
        points.append((x, y))
    if len(points) == 1:
        return sorted(_point_candidates(points[0]))
    cells = set()
    for a, b in zip(points, points[1:]):
        cells.update(_segment_membership(a, b))
    return sorted(cells)


def _schema(name):
    schemas = {p.name: _json(p) for p in TILE_SCHEMA_DIR.glob("*.schema.json")}
    schemas["segment.schema.json"] = _json(TILE_SCHEMA_DIR / "segment.schema.json")
    registry = Registry()
    for schema_name, schema in schemas.items():
        Draft202012Validator.check_schema(schema)
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return Draft202012Validator(schemas[name], registry=registry)


def _check_schema(value, schema, label):
    errors = sorted(schema.iter_errors(value), key=lambda e: (list(map(str, e.absolute_path)), e.message))
    _need(not errors, f"{label} schema invalid at {list(errors[0].absolute_path)}: {errors[0].message}" if errors else "")


def _segment_record(row, way):
    _need(isinstance(row.get("candidate_id"), str) and row["candidate_id"], "candidate_id must be nonempty text")
    _need(isinstance(row.get("way_id"), str) and row["way_id"], f"{row.get('candidate_id')}: way_id must be text")
    _need(type(row.get("sequence")) is int and row["sequence"] >= 0, f"{row['candidate_id']}: invalid sequence")
    refs = way.get("node_refs")
    start = row["sequence"]
    _need(isinstance(refs, list) and refs[start:start + 2] == [row.get("from_node_id"), row.get("to_node_id")], f"{row['candidate_id']}: source way node join failed")
    tags = way.get("tags")
    _need(isinstance(tags, dict) and isinstance(tags.get("highway"), str) and tags["highway"], f"{row['candidate_id']}: missing or invalid highway tag")
    fields = [tags.get(key, "") for key in ("highway", "name", "sidewalk", "footway")]
    _need(all(isinstance(x, str) for x in fields), f"{row['candidate_id']}: source tags must be text")
    _need(row.get("direction") in {"both", "forward", "reverse"}, f"{row['candidate_id']}: invalid direction")
    length = row.get("length_ft")
    _need(type(length) in (int, float) and math.isfinite(length) and length > 0, f"{row['candidate_id']}: invalid length")
    coords = row.get("coordinates")
    _need(isinstance(coords, list) and len(coords) >= 2, f"{row['candidate_id']}: invalid geometry")
    for point in coords:
        _need(isinstance(point, list) and len(point) == 2, f"{row['candidate_id']}: invalid coordinate pair")
        _scaled(point[0]); y = _scaled(point[1])
        _need(-90 * SCALE <= y <= 90 * SCALE, f"{row['candidate_id']}: invalid latitude precision/range")
    return {"id": row["candidate_id"], "from": row["from_node_id"], "to": row["to_node_id"], "len_ft": length, "dir": row["direction"], "coords": coords, "way_id": row["way_id"], "hwy": fields[0], "name": fields[1], "sidewalk": fields[2], "footway": fields[3]}


def build_from_records(segments, nodes, arcs, ways_by_id, *, source_release_id, excluded_count, unknown_count, output_dir, release_id, source_metadata=None):
    """Build a fixture or release using package-shaped records; output_dir must be empty."""
    out = Path(output_dir)
    _need(SAFE_ID.fullmatch(release_id) is not None, "release ID must contain only letters, digits, hyphens and underscores")
    _need(not out.exists() or (out.is_dir() and not any(out.iterdir())), f"output directory must be absent or empty: {out}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "network").mkdir()
    nodes_by_id = {n["node_id"]: n for n in nodes}
    _need(len(nodes_by_id) == len(nodes), "duplicate node ID")
    seg_ids = [s.get("candidate_id") for s in segments]
    _need(len(set(seg_ids)) == len(seg_ids), "duplicate segment ID")
    tile_segments = defaultdict(list); expected_members = {}
    by_id = {}
    for source in segments:
        way_id = source.get("way_id")
        _need(way_id in ways_by_id, f"{source.get('candidate_id')}: missing source way {way_id}")
        record = _segment_record(source, ways_by_id[way_id])
        by_id[record["id"]] = record
        cell_list = tiles_for_coordinates(record["coords"])
        expected_members[record["id"]] = set(cell_list)
        for col, row in cell_list: tile_segments[(col, row)].append(record)
    total_length = math.fsum(by_id[key]["len_ft"] for key in sorted(by_id))
    tile_entries = []
    for (col, row), records in sorted(tile_segments.items()):
        path = out / "network" / f"{col}_{row}.json"
        payload = {"col": col, "row": row, "segments": sorted(records, key=lambda r: r["id"])}
        data = _write(path, payload)
        tile_entries.append({"col": col, "row": row, "path": f"network/{col}_{row}.json", "segments": len(records), "bytes": len(data)})
    coords = [p for segment in by_id.values() for p in segment["coords"]]
    bbox = [min(p[0] for p in coords), min(p[1] for p in coords), max(p[0] for p in coords), max(p[1] for p in coords)]
    metadata = source_metadata or {}
    manifest = {"format": "walk-tiles", "version": 0, "release_id": release_id, "source_release_id": source_release_id,
        "grid": {"cell_size_degrees": 0.01, "origin": [-180, -90], "coordinate_scale": SCALE, "cell_size_scaled": CELL, "coordinate_rounding": "none; exact decimal input, maximum seven places", "segment_membership": "closed cells; whole segment in every touched cell", "point_index": "floor((lon+180)/0.01), floor((lat+90)/0.01) using exact decimal arithmetic"},
        "crs": "EPSG:4326", "coordinate_order": "longitude_latitude", "length_unit": "international_foot", "default_speed_mph": 2.8,
        "coverage": {"bbox": bbox, "readiness": "not_established", "meaning": "extent of included source geometry, not a guarantee of complete walkable streets"}, "tiles": tile_entries,
        "source": {"osm_data_timestamp": metadata.get("osm_data_timestamp", "2026-11-01T21:21:36Z"), "download_date": metadata.get("download_date", "2026-11-02"), "walking_rule_version": metadata.get("walking_rule_version", "pedestrian-policy-0.3"), "selection": metadata.get("selection", "existing included segments; no re-extraction or reclassification")},
        "counts": {"included": len(segments), "excluded": excluded_count, "unknown_left_out": unknown_count, "nodes": len(nodes), "directed_arcs": len(arcs), "tiles": len(tile_entries), "segment_copies": sum(t["segments"] for t in tile_entries), "total_length_ft": total_length},
        "attribution": "© OpenStreetMap contributors", "license": "ODbL-1.0", "license_url": "https://opendatacommons.org/licenses/odbl/1-0/", "attribution_url": "https://www.openstreetmap.org/copyright", "distribution_status": "local_experimental_not_cleared_for_redistribution",
        "limitations": metadata.get("limitations", [f"Unknown ({unknown_count:,}) and excluded ({excluded_count:,}) candidates are omitted.", "Coverage is incomplete and not established; included geometry extent does not prove complete streets.", "Walking restrictions in 1,050 source relations are unsupported.", "47,490 relation members are unresolved.", "No barrier-aware origin connection or wheelchair assessment is performed.", "Crossing, slope, stair and turn delays are not modeled.", "Public redistribution is not approved.", "Decision 0011 snapping is not implemented by tile construction."])}
    schema = _schema("manifest.schema.json")
    _check_schema(manifest, schema, "manifest")
    _write(out / "manifest.json", manifest)
    return manifest


def _expected_fraction_membership(coords):
    """Independent exact rational clipping used only by disk verification."""
    pts = [(Fraction(_scaled(p[0])), Fraction(_scaled(p[1]))) for p in coords]
    result = set()
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        lo_x, hi_x = sorted((x0, x1)); lo_y, hi_y = sorted((y0, y1))
        c0, c1 = int((lo_x + 180 * SCALE) // CELL), int((hi_x + 180 * SCALE) // CELL)
        r0, r1 = int((lo_y + 90 * SCALE) // CELL), int((hi_y + 90 * SCALE) // CELL)
        if (lo_x + 180 * SCALE) % CELL == 0: c0 -= 1
        if (lo_y + 90 * SCALE) % CELL == 0: r0 -= 1
        for col in range(max(0, c0), min(MAX_COL, c1) + 1):
            for row in range(max(0, r0), min(MAX_ROW, r1) + 1):
                left, bottom = Fraction(col * CELL - 180 * SCALE), Fraction(row * CELL - 90 * SCALE)
                right, top = left + CELL, bottom + CELL
                # Liang-Barsky parameters are exact Fractions; equality keeps closed-edge contact.
                dx, dy = x1 - x0, y1 - y0
                t0, t1 = Fraction(0), Fraction(1)
                valid = True
                for p, q in ((-dx, x0-left), (dx, right-x0), (-dy, y0-bottom), (dy, top-y0)):
                    if p == 0:
                        if q < 0: valid = False; break
                    else:
                        t = q / p
                        if p < 0: t0 = max(t0, t)
                        else: t1 = min(t1, t)
                if valid and t0 <= t1: result.add((col, row))
    return result


def _map_arcs(segments):
    expected = set()
    for s in segments:
        if s["direction"] in {"both", "forward"}:
            expected.add((s["candidate_id"], "forward", s["from_node_id"], s["to_node_id"]))
        if s["direction"] in {"both", "reverse"}:
            expected.add((s["candidate_id"], "reverse", s["to_node_id"], s["from_node_id"]))
    return expected


def verify_records(segments, nodes, arcs, ways_by_id, tile_dir, manifest):
    """Verify reopened output against source-shaped records and independent grid clipping."""
    out = Path(tile_dir)
    disk_manifest = _json(out / "manifest.json")
    _need(disk_manifest == manifest, "on-disk manifest differs from supplied manifest")
    _check_schema(manifest, _schema("manifest.schema.json"), "manifest")
    expected = {}
    expected_cells = {}
    node_map = {n["node_id"]: n["coordinate"] for n in nodes}
    _need(len(node_map) == len(nodes), "duplicate source node IDs")
    for s in segments:
        rec = _segment_record(s, ways_by_id[s["way_id"]])
        expected[rec["id"]] = rec
        expected_cells[rec["id"]] = _expected_fraction_membership(rec["coords"])
        _need(s["from_node_id"] in node_map and s["to_node_id"] in node_map, f"{rec['id']}: endpoint node missing")
        _need(s["coordinates"][0] == node_map[s["from_node_id"]] and s["coordinates"][-1] == node_map[s["to_node_id"]], f"{rec['id']}: endpoint coordinate mismatch")
    all_network_files = {p.relative_to(out).as_posix() for p in (out / "network").rglob("*") if p.is_file()}
    _need(all(p.is_file() for p in (out / "network").rglob("*")), "network folder contains a non-file entry")
    tile_names = all_network_files
    listed_names = {t["path"] for t in manifest["tiles"]}
    _need(tile_names == listed_names, "network directory files do not match manifest tile list")
    tile_keys = [(t["col"], t["row"]) for t in manifest["tiles"]]
    _need(tile_keys == sorted(tile_keys) and len(tile_keys) == len(set(tile_keys)), "manifest tile list is not uniquely sorted")
    _need(len(listed_names) == len(manifest["tiles"]), "duplicate manifest tile path")
    schema = _schema("tile.schema.json")
    actual = {}; actual_cells = defaultdict(set); copies = 0
    for entry in manifest["tiles"]:
        name = entry["path"]
        _need(re.fullmatch(r"network/(0|[1-9][0-9]*)_(0|[1-9][0-9]*)\.json", name) is not None, f"unsafe tile path: {name}")
        _need(name == f"network/{entry['col']}_{entry['row']}.json", f"tile path does not match listed coordinates: {name}")
        path = out / name
        _need(path.is_file() and path.stat().st_size == entry["bytes"], f"missing tile or byte mismatch: {name}")
        payload = _json(path); _check_schema(payload, schema, name)
        _need((payload["col"], payload["row"]) == (entry["col"], entry["row"]), f"tile identity mismatch: {name}")
        _need(len(payload["segments"]) == entry["segments"] > 0, f"tile count mismatch: {name}")
        ids = [r["id"] for r in payload["segments"]]
        _need(ids == sorted(ids) and len(ids) == len(set(ids)), f"tile segment ordering/duplicates invalid: {name}")
        for record in payload["segments"]:
            sid = record["id"]; copies += 1
            _need(sid in expected, f"extra tile segment: {sid}")
            _need(record == expected[sid], f"tile record differs from source mapping: {sid}")
            if sid in actual: _need(actual[sid] == record, f"duplicate copies disagree: {sid}")
            else: actual[sid] = record
            actual_cells[sid].add((payload["col"], payload["row"]))
    _need(set(actual) == set(expected), f"segment ID mismatch; missing={len(set(expected)-set(actual))}, extra={len(set(actual)-set(expected))}")
    endpoint_ids = {s[k] for s in segments for k in ("from_node_id", "to_node_id")}
    _need(endpoint_ids == set(node_map), "referenced endpoint-ID set differs from included source nodes")
    all_coords = [point for rec in expected.values() for point in rec["coords"]]
    expected_bbox = [min(p[0] for p in all_coords), min(p[1] for p in all_coords), max(p[0] for p in all_coords), max(p[1] for p in all_coords)]
    _need(manifest["coverage"]["bbox"] == expected_bbox, "manifest coverage extent differs from source geometry")
    counts = manifest["counts"]
    _need(counts["included"] == len(segments) and counts["nodes"] == len(nodes) and counts["directed_arcs"] == len(arcs), "manifest source counts disagree")
    _need(counts["tiles"] == len(manifest["tiles"]) and counts["segment_copies"] == copies, "manifest tile/copy counts disagree")
    missed = sum(actual_cells[s] != expected_cells[s] for s in expected)
    _need(missed == 0, f"tile membership differs for {missed} segments")
    expected_arcs = _map_arcs(segments)
    actual_arcs = {(a["candidate_id"], a["direction"], a["from_node_id"], a["to_node_id"]) for a in arcs}
    arc_ids = [a.get("edge_id") for a in arcs]
    _need(len(arc_ids) == len(set(arc_ids)) and len(arcs) == len(expected_arcs), "duplicate or unexpected directed arc records")
    _need(expected_arcs == actual_arcs, "directed segment connectivity differs from arcs.json")
    rebuilt_arcs = set()
    for sid, record in actual.items():
        if record["dir"] in {"both", "forward"}: rebuilt_arcs.add((sid, "forward", record["from"], record["to"]))
        if record["dir"] in {"both", "reverse"}: rebuilt_arcs.add((sid, "reverse", record["to"], record["from"]))
    _need(rebuilt_arcs == actual_arcs, "disk-rebuilt directed connections differ from source arcs.json")
    source_length = math.fsum(expected[k]["len_ft"] for k in sorted(expected))
    _need(source_length == manifest["counts"]["total_length_ft"], "source/rebuilt length mismatch")
    return {"unique_segments": len(actual), "segment_copies": copies, "source_total_length_ft": source_length, "rebuilt_total_length_ft": math.fsum(actual[k]["len_ft"] for k in sorted(actual)), "length_difference_ft": 0.0, "directed_connections": len(actual_arcs), "tile_count": len(manifest["tiles"])}


def _read_sources(root):
    root = Path(root); package = root / PACKAGE_REL
    manifest = _json(package / "manifest.json"); qa = _json(package / "qa.json")
    _need(manifest.get("release_id") == "denver-policy03-task52-20261104-e" and qa.get("release_id") == manifest["release_id"], "package/QA release IDs disagree")
    _need(manifest.get("graph_id") == qa.get("graph_id"), "package/QA graph IDs disagree")
    for name in ("nodes", "segments", "arcs", "qa", "inventory", "notices"):
        entry = manifest["files"][name]; path = package / entry["path"]
        _need(path.is_file() and path.stat().st_size == entry["bytes"] and _sha(path) == entry["sha256"], f"package input hash/size mismatch: {path}")
    net_schema_dir = root / "contracts/network-package/v1"
    net_schemas = {p.name: _json(p) for p in net_schema_dir.glob("*.schema.json")}
    registry = Registry()
    for schema in net_schemas.values():
        Draft202012Validator.check_schema(schema)
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    manifest_errors = sorted(Draft202012Validator(net_schemas["manifest.schema.json"], registry=registry).iter_errors(manifest), key=lambda e: e.message)
    _need(qa.get("report_version") == "flm-package-qa-1", "unexpected package QA report version")
    _need(not manifest_errors, f"package manifest schema invalid: {manifest_errors[0].message}" if manifest_errors else "")
    _need(all(qa["counts"].get(k) == manifest["counts"][k] for k in ("nodes", "segments", "arcs")), "QA counts disagree with package manifest")
    for name, envelope_key in (("nodes", "nodes"), ("segments", "segments"), ("arcs", "arcs")):
        payload = _json(package / manifest["files"][name]["path"])
        _need(payload.get("release_id") == manifest["release_id"] and payload.get("graph_id") == manifest["graph_id"], f"{name} header disagrees with manifest")
        _need(isinstance(payload.get(envelope_key), list), f"invalid {name} envelope")
        schema = net_schemas[f"{name}.schema.json"]
        errors = sorted(Draft202012Validator(schema, registry=registry).iter_errors(payload), key=lambda e: (list(map(str,e.absolute_path)),e.message))
        _need(not errors, f"{name} package schema invalid: {errors[0].message}" if errors else "")
        if name == "nodes": nodes = payload[envelope_key]
        elif name == "segments": segments = payload[envelope_key]
        else: arcs = payload[envelope_key]
    counts = manifest["counts"]
    _need(counts == {"nodes": EXPECTED["nodes"], "segments": EXPECTED["segments"], "arcs": EXPECTED["arcs"]}, "package manifest counts differ from pinned counts")
    _need(qa["counts"].get("excluded_candidates") == EXPECTED["excluded"] and qa["counts"].get("unknown_candidates") == EXPECTED["unknown"], "QA candidate counts differ from pinned counts")
    _need(manifest.get("diagnostics", {}).get("unsupported_restrictions") == 1050 and manifest.get("diagnostics", {}).get("unresolved_relation_members") == 47490, "package relation limitation counts differ from pinned values")
    _need(manifest.get("files", {}).get("inventory", {}).get("sha256") == manifest.get("identity", {}).get("source_inventory_sha256"), "package inventory file and identity hash disagree")
    _need(len(nodes) == EXPECTED["nodes"] and len(segments) == EXPECTED["segments"] and len(arcs) == EXPECTED["arcs"], "package payload counts mismatch")
    extraction = _json(root / EXTRACT_REL / "extraction.json")
    report = _json(root / EXTRACT_REL / "run-report.json")
    _need(report["output_hashes"].get("ways.jsonl") == _sha(root / EXTRACT_REL / "ways.jsonl"), "ways.jsonl extraction hash mismatch")
    ways = {}
    with (root / EXTRACT_REL / "ways.jsonl").open(encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            try: row = json.loads(line, object_pairs_hook=_pairs, parse_constant=_constant)
            except (json.JSONDecodeError, UnicodeError) as exc: raise WalkTilesError(f"invalid ways.jsonl line {line_no}: {exc}") from exc
            wid = row.get("osm_id"); _need(isinstance(wid, str) and wid not in ways, f"duplicate/invalid way ID at line {line_no}"); ways[wid] = row
    _need(extraction.get("contract_version") == "source-network-1", "unexpected extraction contract")
    inventory = _json(package / manifest["files"]["inventory"]["path"])
    source = inventory.get("sources")
    if isinstance(source, list):
        osm = next((x for x in source if x.get("kind") == "osm"), {})
        timestamp = osm.get("observed_vintage")
        download = str(osm.get("downloaded_at", ""))[:10]
    else:
        osm = source.get("osm", {}) if isinstance(source, dict) else {}
        timestamp = osm.get("observed_header_vintage")
        download = str(osm.get("downloaded_at", ""))[:10]
    _need(timestamp == "2026-11-01T21:21:36Z" and download == "2026-11-02", "source OSM timestamp/download date mismatch")
    return package, manifest, qa, nodes, segments, arcs, ways, {"osm_data_timestamp": timestamp, "download_date": download, "walking_rule_version": manifest["identity"]["rule_version"]}


def _size_report(out, manifest, verification, elapsed):
    sizes = [(entry["path"], (out / entry["path"]).stat().st_size) for entry in manifest["tiles"]]
    gzip_sizes = [(path, len(gzip.compress((out / path).read_bytes(), compresslevel=9, mtime=0))) for path, _ in sizes]
    def summary(items):
        vals = sorted(v for _, v in items); n = len(vals)
        return {"total": sum(vals), "minimum": vals[0], "median": statistics.median(vals), "p95": vals[math.ceil(.95*n)-1], "maximum": vals[-1]}
    plain, zipped = summary(sizes), summary(gzip_sizes)
    man_bytes = (out / "manifest.json").read_bytes(); man_gzip = len(gzip.compress(man_bytes, compresslevel=9, mtime=0))
    largest = sorted(sizes, key=lambda item: (-item[1], item[0]))[:10]
    payload_bytes = plain["total"] + len(man_bytes)
    compressed_payload = zipped["total"] + man_gzip
    def lines(stats): return "\n".join(f"- {k}: {v} bytes ({v/1000:.3f} KB; {v/1_000_000:.3f} MB)" for k,v in stats.items())
    report = f"""# Walk tiles size and verification report

Status: PASS. Output is local experimental data and is not cleared for redistribution.

Default walking speed: exactly {manifest['default_speed_mph']} mph. Distances and lengths are international feet; time budgets are minutes or seconds. Coordinates and grid dimensions are angular degrees.

## Verification

- Unique source IDs and reopened tile IDs: {verification['unique_segments']} each; missing and extra IDs: 0.
- Segment copies across cells: {verification['segment_copies']}.
- Directed connections: {verification['directed_connections']}.
- Source length: {verification['source_total_length_ft']!r} ft; rebuilt length: {verification['rebuilt_total_length_ft']!r} ft; difference: {verification['length_difference_ft']!r} ft.
- Complete source-derived tile membership: pass; disk payload was checked with rational clipping independent of the writer's integer edge tests.
- Tile count: {verification['tile_count']}.
- Preflight elapsed seconds: {verification.get('preflight_seconds', 0):.3f}; build and verification elapsed seconds: {verification.get('build_verification_seconds', elapsed):.3f}; total elapsed seconds: {elapsed:.3f}.

## Uncompressed network tile sizes

{lines(plain)}

## Individually gzip-compressed tile sizes

Each serialized tile was compressed separately using gzip level 9 and mtime 0. This is a measurement only; no compressed files or archive are included.

{lines(zipped)}
- Manifest gzip bytes: {man_gzip}.
- Data payload (manifest plus network tiles; excludes this report): {payload_bytes} bytes ({payload_bytes/1000:.3f} KB; {payload_bytes/1_000_000:.3f} MB).
- Individually compressed data payload estimate: {compressed_payload} bytes ({compressed_payload/1000:.3f} KB; {compressed_payload/1_000_000:.3f} MB).
- Typical tile means median. Target median is below 500,000 bytes; median is {plain['median']:.0f} bytes, so target: {'PASS' if plain['median'] < 500000 else 'OVER TARGET'}.
- Largest network tiles: {', '.join(f"`{p}` ({n} bytes)" for p,n in largest)}.

## Commands and scope

- Build reproduction: `.venv/Scripts/python.exe pipeline/tools/build_walk_tiles.py --release-id {manifest['release_id']}`
- Focused verification command: `.venv/Scripts/python.exe -m pytest pipeline/tests/test_walk_tiles.py`
- Full Python verification command: `.venv/Scripts/python.exe -m pytest pipeline/tests`
- Schema lint command: `pnpm lint`. These commands must be run and their outcomes reported separately; the builder does not claim they ran.
- Not run: a real tile-reader compatibility check; no reader exists. Snapping, reachability, Census analysis and map display are outside this build.

The source is the accepted OSM-derived experimental package. Unknown and excluded candidates are omitted, coverage is not established, and public redistribution is not approved. No source length or geometry was recalculated or simplified.
"""
    (out / "size-report.md").write_text(report, encoding="utf-8", newline="\n")
    return {"plain": plain, "gzip": zipped, "manifest_gzip_bytes": man_gzip, "data_payload_bytes": payload_bytes, "compressed_data_payload_bytes": compressed_payload}


def build_tiles(source_dir: Path, output_dir: Path, release_id: str, *, source_root: Path | None = None):
    """Strict production entry point; caller provides a fresh temporary directory."""
    root = Path(source_root) if source_root else Path(source_dir)
    _need(SAFE_ID.fullmatch(release_id) is not None, "release ID must contain only letters, digits, hyphens and underscores")
    started = time.perf_counter()
    package, pkg_manifest, qa, nodes, segments, arcs, ways, metadata = _read_sources(root)
    preflight_seconds = time.perf_counter() - started
    build_started = time.perf_counter()
    manifest = build_from_records(segments, nodes, arcs, ways, source_release_id=pkg_manifest["release_id"], excluded_count=EXPECTED["excluded"], unknown_count=EXPECTED["unknown"], output_dir=output_dir, release_id=release_id, source_metadata=metadata)
    verification = verify_records(segments, nodes, arcs, ways, output_dir, manifest)
    verification["preflight_seconds"] = preflight_seconds
    verification["build_verification_seconds"] = time.perf_counter() - build_started
    verification["total_elapsed_seconds"] = time.perf_counter() - started
    _size_report(Path(output_dir), manifest, verification, verification["total_elapsed_seconds"])
    return {"manifest": manifest, "verification": verification}

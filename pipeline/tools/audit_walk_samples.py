"""Audit completed walk-sample tiles, source preservation, and serialized sizes."""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import tomllib

from pyproj import Geod

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

from flm_pipeline.graph import _close, base_seconds  # noqa: E402
from flm_pipeline.walk_tiles import verify_records  # noqa: E402

GEOD_FT = Geod(a=20_925_646.325459316, rf=298.257223563)
AUDIT_ROOT = Path("data/generated/prototype/walk-sample-audits")


class SampleAuditError(RuntimeError):
    """A completed sample index or its source/tile data failed audit."""


def _need(condition, message):
    if not condition:
        raise SampleAuditError(message)


def _json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SampleAuditError(f"Could not read JSON {path}: {error}") from error
    _need(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def _jsonl(path):
    rows = []
    try:
        with Path(path).open(encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                row = json.loads(line)
                _need(isinstance(row, dict), f"Expected object at {path}:{number}")
                rows.append(row)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SampleAuditError(f"Could not read JSONL {path}: {error}") from error
    return rows


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _root_path(root, value, label):
    _need(isinstance(value, str) and value, f"{label} must be a nonempty root-relative path")
    candidate = Path(value)
    _need(not candidate.is_absolute() and ".." not in candidate.parts, f"{label} must remain inside the repository")
    unresolved = root / candidate
    current = root
    for part in candidate.parts:
        current = current / part
        _need(not current.is_symlink(), f"{label} cannot traverse a symlink")
    resolved = unresolved.resolve()
    _need(resolved.is_relative_to(root.resolve()), f"{label} escapes the repository")
    _need(not resolved.is_symlink(), f"{label} cannot be a symlink")
    return resolved


def _verify_output_manifest(directory, manifest, label):
    _need(isinstance(manifest, dict) and manifest, f"{label} output manifest is missing")
    checked = 0
    for name, record in manifest.items():
        _need(Path(name).name == name, f"{label} output path is not a filename: {name}")
        path = directory / name
        _need(path.is_file() and not path.is_symlink(), f"{label} output is missing: {path}")
        if isinstance(record, str):
            expected_hash, expected_bytes = record, None
        else:
            _need(isinstance(record, dict), f"{label} output entry is invalid: {name}")
            expected_hash, expected_bytes = record.get("sha256"), record.get("bytes")
        _need(isinstance(expected_hash, str) and len(expected_hash) == 64, f"{label} output hash is invalid: {name}")
        _need(_sha256(path) == expected_hash, f"{label} output hash mismatch: {name}")
        if expected_bytes is not None:
            _need(type(expected_bytes) is int and path.stat().st_size == expected_bytes, f"{label} output byte count mismatch: {name}")
        checked += 1
    return checked


def _coord(node):
    lon, lat = node.get("lon"), node.get("lat")
    _need(type(lon) in (int, float) and math.isfinite(lon), "source longitude is not finite")
    _need(type(lat) in (int, float) and math.isfinite(lat), "source latitude is not finite")
    _need(-180 <= lon <= 180 and -90 <= lat <= 90, "source coordinate is outside EPSG:4326")
    return [lon, lat]


def _inside(point, bbox):
    west, south, east, north = bbox
    return west <= point[0] <= east and south <= point[1] <= north


def _round15(values):
    return [float(format(value, ".15g")) for value in values]


def _all_checks_pass(report, label):
    checks = report.get("checks")
    _need(isinstance(checks, dict) and checks, f"{label} has no recorded checks")
    failed = [key for key, value in checks.items() if value is not True]
    _need(not failed, f"{label} checks failed: {', '.join(failed)}")
    return len(checks)


def _validate_case_ids(cases):
    _need(isinstance(cases, dict) and set(cases) == {"G01", "B01", "F01"}, "sample index must contain exactly G01, B01, and F01")


def _touches_bbox(a, b, bbox):
    """Exact rational Liang-Barsky test for a source segment and closed bbox."""
    west, south, east, north = (Fraction(str(value)) for value in bbox)
    x0, y0 = (Fraction(str(value)) for value in a)
    x1, y1 = (Fraction(str(value)) for value in b)
    dx, dy = x1 - x0, y1 - y0
    low, high = Fraction(0), Fraction(1)
    for p, q in ((-dx, x0 - west), (dx, east - x0), (-dy, y0 - south), (dy, north - y0)):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            low = max(low, t)
        else:
            high = min(high, t)
        if low > high:
            return False
    return True


def audit_source_graph(extraction_directory, graph_directory, bbox):
    """Reconcile every graph candidate to a canonical whole-way source pair."""
    _need(isinstance(bbox, list) and len(bbox) == 4, "extract_bbox must contain west,south,east,north")
    _need(all(type(value) in (int, float) and math.isfinite(value) for value in bbox), "extract_bbox must be finite")
    west, south, east, north = bbox
    _need(west < east and south < north, "extract_bbox must have positive area")
    extraction_directory, graph_directory = Path(extraction_directory), Path(graph_directory)
    nodes = {}
    for node in _jsonl(extraction_directory / "nodes.jsonl"):
        node_id = node.get("osm_id")
        _need(isinstance(node_id, str) and node_id not in nodes, "duplicate or invalid source node ID")
        nodes[node_id] = node
        _coord(node)
    ways = {}
    expected = {}
    ways_with_inside_node = 0
    for way in _jsonl(extraction_directory / "ways.jsonl"):
        way_id, refs = way.get("osm_id"), way.get("node_refs")
        _need(isinstance(way_id, str) and way_id not in ways, "duplicate or invalid source way ID")
        _need(isinstance(refs, list) and len(refs) >= 2, f"source way {way_id} has invalid node_refs")
        ways[way_id] = way
        has_inside_node = any(_inside(_coord(nodes[node_id]), bbox) for node_id in refs if node_id in nodes)
        _need(has_inside_node, f"source way {way_id} has no node inside its written extraction bbox")
        ways_with_inside_node += 1
        for sequence, (from_id, to_id) in enumerate(zip(refs, refs[1:])):
            _need(from_id in nodes and to_id in nodes, f"source way {way_id} references a missing node")
            coords = [_coord(nodes[from_id]), _coord(nodes[to_id])]
            candidate_id = f"way/{way_id}/segment/{sequence}"
            expected[candidate_id] = {
                "candidate_id": candidate_id, "way_id": way_id, "sequence": sequence,
                "from_node_id": from_id, "to_node_id": to_id, "coordinates": coords,
            }
    graph_segments = {}
    for segment in _jsonl(graph_directory / "segments.jsonl"):
        candidate_id = segment.get("candidate_id")
        _need(isinstance(candidate_id, str) and candidate_id not in graph_segments, "duplicate or invalid graph candidate ID")
        graph_segments[candidate_id] = segment
    _need(set(graph_segments) == set(expected),
          f"graph candidate set differs from canonical whole-way pairs; missing={len(set(expected)-set(graph_segments))}, extra={len(set(graph_segments)-set(expected))}")

    graph_nodes = {}
    for node in _jsonl(graph_directory / "nodes.jsonl"):
        node_id = node.get("node_id")
        _need(isinstance(node_id, str) and node_id not in graph_nodes, "duplicate or invalid graph node ID")
        graph_nodes[node_id] = [node.get("lon"), node.get("lat")]

    counts = Counter()
    lengths = {"include": [], "exclude": [], "unknown": []}
    recomputed_lengths = {"include": [], "exclude": [], "unknown": []}
    maximum_length_difference_ft = 0.0
    included = []
    included_node_ids = set()
    for candidate_id, source in expected.items():
        segment = graph_segments[candidate_id]
        _need(type(segment.get("sequence")) is int, f"{candidate_id}: sequence must be an integer")
        for key in ("way_id", "sequence", "from_node_id", "to_node_id", "coordinates"):
            _need(segment.get(key) == source[key], f"{candidate_id}: graph {key} differs from canonical node_refs/coordinates")
        length = segment.get("length_ft")
        _need(type(length) in (int, float) and math.isfinite(length) and length >= 0, f"{candidate_id}: invalid length_ft")
        source_length = GEOD_FT.inv(*source["coordinates"][0], *source["coordinates"][1])[2]
        length_difference = abs(length - source_length)
        maximum_length_difference_ft = max(maximum_length_difference_ft, length_difference)
        _need(_close(length, source_length), f"{candidate_id}: graph length_ft differs from source-node geodesic length beyond the graph tolerance")
        eligibility = segment.get("eligibility")
        _need(eligibility in lengths, f"{candidate_id}: invalid eligibility")
        lengths[eligibility].append(length)
        recomputed_lengths[eligibility].append(source_length)
        counts[f"candidates_{eligibility}"] += 1
        direction = segment.get("direction")
        if eligibility == "include":
            _need(direction in {"both", "forward", "reverse"}, f"{candidate_id}: invalid included direction")
            expected_seconds = base_seconds(length, 2.8)
            _need(_close(segment.get("base_seconds"), expected_seconds), f"{candidate_id}: base_seconds differs from the 2.8 mph graph cost")
            included.append({key: segment[key] for key in (
                "candidate_id", "way_id", "sequence", "from_node_id", "to_node_id", "direction", "length_ft", "coordinates")})
            included_node_ids.update((source["from_node_id"], source["to_node_id"]))
            endpoint_inside = all(_inside(point, bbox) for point in source["coordinates"])
            touches = _touches_bbox(*source["coordinates"], bbox)
            if endpoint_inside:
                counts["included_segments_inside_bbox"] += 1
            elif touches:
                counts["included_segments_crossing_bbox"] += 1
            else:
                counts["included_segments_outside_bbox"] += 1
        elif eligibility == "exclude":
            _need(direction == "none", f"{candidate_id}: excluded direction must be none")
            _need(segment.get("base_seconds") is None, f"{candidate_id}: excluded candidate must not have base_seconds")
        else:
            _need(direction == "unknown", f"{candidate_id}: unknown direction must be unknown")
            _need(segment.get("base_seconds") is None, f"{candidate_id}: unknown candidate must not have base_seconds")
    _need(set(graph_nodes) == included_node_ids, "graph node IDs differ from included-segment endpoint set")
    for node_id, coordinate in graph_nodes.items():
        _need(coordinate == _coord(nodes[node_id]), f"graph node {node_id} coordinate differs from source")

    expected_arcs = {}
    for segment in included:
        for direction in ("forward", "reverse"):
            if segment["direction"] not in {"both", direction}:
                continue
            reverse = direction == "reverse"
            edge_id = segment["candidate_id"] + "/" + direction
            expected_arcs[edge_id] = (
                segment["candidate_id"], direction,
                segment["to_node_id"] if reverse else segment["from_node_id"],
                segment["from_node_id"] if reverse else segment["to_node_id"],
                segment["way_id"], segment["sequence"], segment["length_ft"],
                list(reversed(segment["coordinates"])) if reverse else segment["coordinates"],
                base_seconds(segment["length_ft"], 2.8),
            )
    actual_arcs = {}
    for arc in _jsonl(graph_directory / "arcs.jsonl"):
        edge_id = arc.get("edge_id")
        _need(isinstance(edge_id, str) and edge_id not in actual_arcs, "duplicate or invalid graph edge ID")
        _need(type(arc.get("sequence")) is int, f"{edge_id}: sequence must be an integer")
        actual_arcs[edge_id] = (
            arc.get("candidate_id"), arc.get("direction"), arc.get("from_node_id"), arc.get("to_node_id"),
            arc.get("way_id"), arc.get("sequence"), arc.get("length_ft"), arc.get("coordinates"),
            arc.get("base_seconds"),
        )
    _need(actual_arcs == expected_arcs, "graph arc IDs, directions, or source-node endpoints differ")

    for eligibility in ("include", "exclude", "unknown"):
        counts.setdefault(f"candidates_{eligibility}", 0)
    for category in ("included_segments_inside_bbox", "included_segments_crossing_bbox", "included_segments_outside_bbox"):
        counts.setdefault(category, 0)
    counts["source_ways"] = len(ways)
    counts["source_ways_with_node_inside_bbox"] = ways_with_inside_node
    counts["source_candidates"] = len(expected)
    counts["included_segments"] = len(included)
    counts["included_nodes"] = len(included_node_ids)
    counts["directed_arcs"] = len(actual_arcs)
    length_summary = {
        "graph_recorded": {key: math.fsum(value) for key, value in lengths.items()},
        "foot_geodesic_recomputed": {key: math.fsum(value) for key, value in recomputed_lengths.items()},
        "maximum_absolute_segment_difference_ft": maximum_length_difference_ft,
    }
    source_ways = {source["way_id"]: ways[source["way_id"]] for source in expected.values() if source["candidate_id"] in graph_segments}
    tile_nodes = [{"node_id": node_id, "coordinate": graph_nodes[node_id]} for node_id in sorted(included_node_ids, key=lambda item: (len(item), item))]
    tile_arcs = [arc for arc in _jsonl(graph_directory / "arcs.jsonl")]
    return included, tile_nodes, tile_arcs, source_ways, dict(counts), length_summary


def _summary(values):
    ordered = sorted(values)
    if not ordered:
        return {"total_bytes": 0, "minimum_bytes": 0, "median_bytes": 0, "p95_nearest_rank_bytes": 0, "maximum_bytes": 0}
    return {
        "total_bytes": sum(ordered), "minimum_bytes": ordered[0],
        "median_bytes": statistics.median(ordered),
        "p95_nearest_rank_bytes": ordered[math.ceil(0.95 * len(ordered)) - 1],
        "maximum_bytes": ordered[-1],
    }


def measure_tile_sizes(tile_directory):
    """Measure serialized files and deterministic per-file gzip sizes."""
    tile_directory = Path(tile_directory)
    manifest_path = tile_directory / "manifest.json"
    manifest = _json(manifest_path)
    tiles = manifest.get("tiles")
    _need(isinstance(tiles, list) and tiles, "tile manifest must list at least one network tile")
    listed = {}
    for entry in tiles:
        path = entry.get("path")
        _need(isinstance(path, str) and path.startswith("network/") and ".." not in Path(path).parts,
              "manifest tile path must stay in network/")
        _need(path not in listed, f"duplicate manifest tile path: {path}")
        listed[path] = entry
    network = tile_directory / "network"
    actual_paths = {path.relative_to(tile_directory).as_posix() for path in network.rglob("*") if path.is_file()}
    _need(not any(path.is_symlink() for path in network.rglob("*")), "network folder contains a symlink")
    _need(actual_paths == set(listed), "network files differ from manifest tile paths")
    plain, zipped = [], []
    sizes = []
    for relative, entry in sorted(listed.items()):
        path = tile_directory / relative
        data = path.read_bytes()
        _need(len(data) == entry.get("bytes"), f"tile byte count differs from manifest: {relative}")
        compressed = gzip.compress(data, compresslevel=9, mtime=0)
        plain.append(len(data)); zipped.append(len(compressed))
        sizes.append({"path": relative, "bytes": len(data), "gzip_bytes": len(compressed)})
    manifest_data = manifest_path.read_bytes()
    manifest_gzip = len(gzip.compress(manifest_data, compresslevel=9, mtime=0))
    sizes.sort(key=lambda row: (-row["bytes"], row["path"]))
    return {
        "tile_count": len(tiles), "network_files": _summary(plain),
        "per_file_gzip": _summary(zipped), "manifest_bytes": len(manifest_data),
        "manifest_gzip_bytes": manifest_gzip,
        "payload_bytes_manifest_plus_tiles": len(manifest_data) + sum(plain),
        "individually_gzipped_payload_bytes_estimate": manifest_gzip + sum(zipped),
        "largest_tiles": sizes[:10],
    }


def audit_case(root, case_id, case, source_sha256):
    _need(case.get("source_sha256") == source_sha256, f"{case_id}: sample-index source hash mismatch")
    _need(case.get("pedestrian_speed_mph") == 2.8, f"{case_id}: sample-index speed differs from exact 2.8 mph")
    extraction = _root_path(root, case.get("extraction_directory"), f"{case_id}.extraction_directory")
    graph = _root_path(root, case.get("graph_directory"), f"{case_id}.graph_directory")
    tiles = _root_path(root, case.get("tile_directory"), f"{case_id}.tile_directory")
    nominal_bbox = case.get("extract_bbox")
    _need(isinstance(nominal_bbox, list) and len(nominal_bbox) == 4, f"{case_id}: sample-index extract_bbox is invalid")
    _need(all(type(value) in (int, float) and math.isfinite(value) for value in nominal_bbox), f"{case_id}: sample-index extract_bbox must be finite")
    case_config = tiles.parent / "source.toml"
    _need(case_config.is_file() and not case_config.is_symlink(), f"{case_id}: written source config is missing")
    try:
        config = tomllib.loads(case_config.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise SampleAuditError(f"{case_id}: could not read written source config: {error}") from error
    bbox = config.get("extract_bbox")
    extraction_report = _json(extraction / "run-report.json")
    extraction_metadata = _json(extraction / "extraction.json")
    graph_report = _json(graph / "run-report.json")
    _need(extraction_report.get("status") in {"pass", "pass_with_warnings"}, f"{case_id}: extraction report did not pass")
    _need(graph_report.get("status") in {"incomplete_unknown_policy", "experimental_graph_complete"}, f"{case_id}: graph report has invalid status")
    extraction_check_count = _all_checks_pass(extraction_report, f"{case_id} extraction")
    graph_check_count = _all_checks_pass(graph_report, f"{case_id} graph")
    graph_coverage = graph_report.get("coverage")
    extraction_coverage = extraction_metadata.get("coverage")
    _need(isinstance(graph_coverage, dict) and isinstance(extraction_coverage, dict), f"{case_id}: extraction/graph coverage is missing")
    graph_bbox = graph_coverage.get("extract_bbox")
    metadata_bbox = extraction_coverage.get("extract_bbox")
    _need(isinstance(bbox, list) and len(bbox) == 4, f"{case_id}: written config extract_bbox is invalid")
    _need(bbox == graph_bbox == metadata_bbox, f"{case_id}: written config, extraction, and graph bounding boxes differ")
    _need(_round15(nominal_bbox) == bbox, f"{case_id}: sample-index nominal bbox does not round to written config bbox")
    _need(graph_report.get("inputs", {}).get("source", {}).get("sha256") == source_sha256, f"{case_id}: graph source hash mismatch")
    _need(graph_report.get("policy", {}).get("speed_mph") == 2.8, f"{case_id}: graph speed differs from exact 2.8 mph scenario")
    extraction_hashes = extraction_report.get("output_hashes")
    graph_hashes = graph_report.get("output_files")
    extraction_checked = _verify_output_manifest(extraction, extraction_hashes, f"{case_id} extraction")
    graph_checked = _verify_output_manifest(graph, graph_hashes, f"{case_id} graph")
    included, nodes, arcs, ways, counts, lengths = audit_source_graph(extraction, graph, bbox)
    manifest = _json(tiles / "manifest.json")
    tile_verification = verify_records(included, nodes, arcs, ways, tiles, manifest)
    return {
        "origin_lonlat": case.get("origin_lonlat"), "extract_bbox": bbox,
        "source_sha256": source_sha256, "counts": counts,
        "source_length_ft_by_eligibility": lengths,
        "source_reports_checked": {
            "extraction_files": extraction_checked, "graph_files": graph_checked,
            "extraction_checks_passed": extraction_check_count, "graph_checks_passed": graph_check_count,
            "written_config_bbox_matches_reports": True, "nominal_bbox_rounds_to_written_bbox": True,
        },
        "tile_verification": tile_verification, "sizes": measure_tile_sizes(tiles),
        "directories": {"extraction": extraction.relative_to(root).as_posix(), "graph": graph.relative_to(root).as_posix(), "tiles": tiles.relative_to(root).as_posix()},
    }


def audit_sample_index(index_path, output_directory, root=ROOT):
    root = Path(root).resolve()
    index_path = _root_path(root, Path(index_path).relative_to(root).as_posix() if Path(index_path).is_absolute() else str(index_path), "samples index")
    index = _json(index_path)
    _need(index.get("format") == "walk-sample-index" and index.get("version") == 1, "unsupported sample-index format/version")
    source_sha = index.get("source_sha256")
    _need(isinstance(source_sha, str) and len(source_sha) == 64, "sample index source_sha256 is invalid")
    _need(index.get("pedestrian_speed_mph") == 2.8, "sample index speed differs from exact 2.8 mph")
    _need(index.get("pedestrian_scenario_id") == "plan-a-walk-reference-2.8-v1", "sample index uses an unexpected pedestrian cost scenario")
    cases = index.get("cases")
    _validate_case_ids(cases)
    case_audits = {case_id: audit_case(root, case_id, case, source_sha) for case_id, case in sorted(cases.items())}
    destination_arg = Path(output_directory)
    destination = destination_arg.resolve() if destination_arg.is_absolute() else (root / destination_arg).resolve()
    allowed = (root / AUDIT_ROOT).resolve()
    _need(destination != allowed and destination.is_relative_to(allowed), "audit output must be a new directory under data/generated/prototype/walk-sample-audits")
    _need(not destination.exists(), f"refusing to overwrite audit output: {destination}")
    summary = {
        "format": "walk-sample-audit", "version": 1,
        "sample_release_id": index.get("release_id"), "source_sha256": source_sha,
        "pedestrian_rule_version": index.get("pedestrian_rule_version"),
        "pedestrian_scenario_id": index.get("pedestrian_scenario_id"),
        "pedestrian_speed_mph": index.get("pedestrian_speed_mph"),
        "stage_timeout_seconds": index.get("stage_timeout_seconds"),
        "cases": case_audits,
    }
    destination.mkdir(parents=True, exist_ok=False)
    json_path = destination / "sample-audit.json"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    markdown = [
        "# Walk sample source and size audit", "",
        f"Sample release: `{summary['sample_release_id']}`", f"Source SHA-256: `{source_sha}`",
        f"Pedestrian rule: `{summary['pedestrian_rule_version']}`; cost scenario: `{summary['pedestrian_scenario_id']}` at {summary['pedestrian_speed_mph']} mph.",
        "The gzip values compress each serialized file independently with level 9 and mtime 0; they are not archive sizes.",
    ]
    for case_id, result in case_audits.items():
        sizes = result["sizes"]
        counts = result["counts"]
        markdown.extend([
            "", f"## {case_id}", "",
            f"- Whole source ways: {counts['source_ways']}; candidate segments: {counts['source_candidates']}; included: {counts['included_segments']}.",
            f"- Included complete segments inside bbox: {counts['included_segments_inside_bbox']}; crossing/touching boundary: {counts['included_segments_crossing_bbox']}; outside bbox: {counts['included_segments_outside_bbox']}.",
            f"- Graph-recorded source lengths by eligibility (international feet): `{result['source_length_ft_by_eligibility']['graph_recorded']}`.",
            f"- Foot-scaled WGS84 recomputation by eligibility: `{result['source_length_ft_by_eligibility']['foot_geodesic_recomputed']}`; maximum absolute segment difference from legacy graph lengths: {result['source_length_ft_by_eligibility']['maximum_absolute_segment_difference_ft']:.12g} ft.",
            f"- Tile copies verified: {result['tile_verification']['segment_copies']}; directed connections: {result['tile_verification']['directed_connections']}; membership mismatches: 0.",
            f"- Network tiles: {sizes['tile_count']}; serialized payload including manifest: {sizes['payload_bytes_manifest_plus_tiles']} bytes; individual-gzip payload estimate: {sizes['individually_gzipped_payload_bytes_estimate']} bytes.",
            f"- Tile bytes min/median/p95/max: {sizes['network_files']['minimum_bytes']} / {sizes['network_files']['median_bytes']} / {sizes['network_files']['p95_nearest_rank_bytes']} / {sizes['network_files']['maximum_bytes']}; total {sizes['network_files']['total_bytes']}.",
        ])
        markdown.append("- Largest tile files: " + ", ".join(f"`{row['path']}` ({row['bytes']} B; gzip {row['gzip_bytes']} B)" for row in sizes["largest_tiles"]) + ".")
    (destination / "sample-audit.md").write_text("\n".join(markdown) + "\n", encoding="utf-8", newline="\n")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples-index", required=True)
    parser.add_argument("--output", required=True, help="new directory below data/generated/prototype/walk-sample-audits")
    args = parser.parse_args(argv)
    try:
        result = audit_sample_index(args.samples_index, args.output)
    except (OSError, ValueError, SampleAuditError, KeyError, TypeError) as error:
        parser.exit(1, f"ERROR: {error}\n")
    print(f"Audited {len(result['cases'])} sample networks; report: {Path(args.output) / 'sample-audit.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

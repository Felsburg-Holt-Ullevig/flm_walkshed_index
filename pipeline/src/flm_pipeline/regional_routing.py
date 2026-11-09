"""Supervised, local regional routing diagnostics for Task 4.4.

The module reads immutable source and graph artifacts, runs experimental
source-node traversals, compares original/expanded observations in a common
core, and writes a reopened GeoPackage inspection product. It does not establish
network completeness or an authoritative walkshed method.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import tomllib
import uuid

from pyproj import Geod, Transformer

from .code_identity import code_identity
from .routing import Origin, Readiness, combined_intervals, traverse, union_intervals
from .routing_adapter import compare_core, load_graph
from .routing_geometry import interpolate

ROOT = Path(__file__).resolve().parents[3]
GEOD = Geod(ellps="WGS84")
SECONDS_PER_FOOT = 0.24384
CORE_COST_TOLERANCE_SECONDS = 1e-9
CORE_INTERVAL_TOLERANCE_FT = 1e-8
CLIP_SAMPLE_STEP_FT = 100.0
CLIP_ROOT_TOLERANCE_FT = 1e-7
CLIP_MAX_SAMPLES_PER_SEGMENT = 100_000
MAX_ORIGINS = 50


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _repo_path(value: str | Path) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    if not resolved.is_relative_to(ROOT):
        raise ValueError("Regional routing paths must remain inside the repository")
    return resolved


def _read_jsonl(path: Path):
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {error}") from error
            if not isinstance(value, dict):
                raise ValueError(f"Expected an object at {path}:{line_number}")
            yield value


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def _checks_pass(checks) -> bool:
    return isinstance(checks, dict) and bool(checks) and all(type(value) is bool and value for value in checks.values())


def verify_handoff(handoff_path: str | Path, graph_directory: str | Path | None = None) -> dict:
    """Fail closed on accepted settings, source, policy, graph report and payload hashes."""
    handoff_file = _repo_path(handoff_path)
    handoff = _json(handoff_file)
    required = {
        "source_sha256", "config", "config_sha256", "graph_directory", "graph_report",
        "graph_report_sha256", "graph_implementation_sha256", "routing_reference_acceptance_manifest",
        "routing_reference_acceptance_sha256", "pedestrian_rule_version", "pedestrian_scenario_id",
    }
    missing = required - set(handoff)
    if missing:
        raise ValueError("Regional handoff is missing: " + ", ".join(sorted(missing)))

    accepted_manifest_path = ROOT / "pipeline" / "fixtures" / "routing-reference-acceptance-v1.json"
    accepted_spec_path = ROOT / "pipeline" / "routing-reference-spec.md"
    accepted_data_path = ROOT / "pipeline" / "fixtures" / "routing-references-v1.json"
    accepted_settings_path = ROOT / "pipeline" / "config" / "routing-benchmarks.v1.toml"
    expected_manifest_path = _repo_path(handoff["routing_reference_acceptance_manifest"])
    if expected_manifest_path != accepted_manifest_path or _sha256(accepted_manifest_path) != handoff["routing_reference_acceptance_sha256"]:
        raise ValueError("Accepted routing reference manifest hash/path mismatch")
    manifest = _json(accepted_manifest_path)
    expected_files = {
        "pipeline/routing-reference-spec.md": accepted_spec_path,
        "pipeline/fixtures/routing-references-v1.json": accepted_data_path,
        "pipeline/config/routing-benchmarks.v1.toml": accepted_settings_path,
    }
    if manifest.get("version") != "routing-reference-acceptance-1" or manifest.get("status") != "accepted_experimental" or set(manifest.get("sha256", {})) != set(expected_files):
        raise ValueError("Routing reference manifest is not the accepted version")
    for relative, path in expected_files.items():
        if _sha256(path) != manifest["sha256"][relative]:
            raise ValueError("Accepted routing reference bytes changed: " + relative)
    metric_data = _json(accepted_data_path)
    settings = tomllib.loads(accepted_settings_path.read_text(encoding="utf-8"))
    if metric_data.get("version") != "routing-references-1" or metric_data.get("status") != "accepted_experimental":
        raise ValueError("Metric reference file is not accepted")
    origin_records = settings.get("origins")
    if (
        settings.get("benchmark_version") != "routing-benchmarks-1"
        or settings.get("status") != "accepted_experimental"
        or settings.get("time_budget_seconds") != 600
        or settings.get("speed_mph") != 4500 / 1609.344
        or settings.get("length_unit") != "international_foot"
        or settings.get("time_unit") != "second"
        or settings.get("coverage_status") != "not_established"
        or not isinstance(origin_records, list)
        or len(origin_records) != 1
    ):
        raise ValueError("Accepted regional run settings changed or are incomplete")
    accepted_origin = origin_records[0]
    if (
        accepted_origin.get("mode") != "verified_source_node"
        or accepted_origin.get("source_node_id") != "7581419196"
        or accepted_origin.get("station_entrance_status") != "not_verified"
        or accepted_origin.get("access_cost_seconds") != 0
    ):
        raise ValueError("Accepted diagnostic origin does not match the pinned source node")

    config_path = _repo_path(handoff["config"])
    if _sha256(config_path) != handoff["config_sha256"]:
        raise ValueError("Accepted source configuration hash mismatch")
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    source_path = _repo_path(config["sources"]["osm"]["path"])
    expected_source = config["sources"]["osm"]["expected_sha256"]
    if expected_source != handoff["source_sha256"]:
        raise ValueError("Pinned OSM source SHA-256 differs from the handoff")
    bounds = settings["coverage_comparison"]
    if (
        config["extract_bbox"] != bounds["original_bbox"]
        or config["expanded_bbox"] != bounds["expanded_bbox"]
        or config["core_bbox"] != bounds["common_core_bbox"]
    ):
        raise ValueError("Accepted source config bounds differ from routing comparison settings")

    original_graph = _repo_path(graph_directory or handoff["graph_directory"])
    report_path = original_graph / "run-report.json"
    if report_path != _repo_path(handoff["graph_report"]) or _sha256(report_path) != handoff["graph_report_sha256"]:
        raise ValueError("Frozen original graph report path or hash mismatch")
    segments, coordinates, readiness, graph_report = load_graph(original_graph)
    source = graph_report.get("inputs", {}).get("source", {})
    if (
        graph_report.get("implementation_identity", {}).get("sha256") != handoff["graph_implementation_sha256"]
        or source.get("sha256") != handoff["source_sha256"]
        or source.get("expected_sha256") != handoff["source_sha256"]
        or graph_report.get("policy", {}).get("rule_version") != handoff["pedestrian_rule_version"]
        or graph_report.get("policy", {}).get("scenario_id") != handoff["pedestrian_scenario_id"]
        or graph_report.get("coverage", {}).get("extract_bbox") != bounds["original_bbox"]
        or graph_report.get("coverage", {}).get("core_bbox") != bounds["common_core_bbox"]
    ):
        raise ValueError("Frozen original graph source, policy, bounds or implementation identity mismatch")
    policy_config_path = ROOT / "pipeline" / "config" / "pedestrian-policy.example.toml"
    policy_authority_path = _repo_path(graph_report["policy"].get("authority_path", "pipeline/pedestrian-policy.md"))
    if (
        _sha256(policy_config_path) != graph_report["policy"].get("config_sha256")
        or _sha256(policy_authority_path) != graph_report["policy"].get("authority_sha256")
        or graph_report["policy"].get("speed_mph") != settings["speed_mph"]
    ):
        raise ValueError("Frozen graph policy configuration or authority hash mismatch")
    raw_digest = _sha256(source_path)
    if raw_digest != handoff["source_sha256"]:
        raise ValueError("Local OSM bytes do not match the pinned accepted source hash")
    if accepted_origin["source_node_id"] not in coordinates:
        raise ValueError("Accepted source node is absent from the frozen graph")
    accepted_point = (accepted_origin["longitude"], accepted_origin["latitude"])
    if coordinates[accepted_origin["source_node_id"]] != accepted_point:
        raise ValueError("Accepted source coordinate does not match the graph node")
    west, south, east, north = bounds["original_bbox"]
    if not (west <= accepted_point[0] <= east and south <= accepted_point[1] <= north):
        raise ValueError("Accepted diagnostic origin is outside the original extract")
    return {
        "handoff": handoff,
        "handoff_path": handoff_file,
        "config": config,
        "config_path": config_path,
        "source_path": source_path,
        "source_sha256": raw_digest,
        "settings": settings,
        "accepted_origin": accepted_origin,
        "original_graph": original_graph,
        "original_report": graph_report,
        "original_segments": segments,
        "original_coordinates": coordinates,
        "original_readiness": readiness,
        "core_bbox": tuple(bounds["common_core_bbox"]),
        "original_bbox": tuple(bounds["original_bbox"]),
        "expanded_bbox": tuple(bounds["expanded_bbox"]),
        "policy_config_path": policy_config_path,
        "policy_sha256": graph_report["policy"]["config_sha256"],
        "policy_authority_sha256": graph_report["policy"]["authority_sha256"],
    }


def prepare_expanded_graph(handoff_path: str | Path) -> dict:
    """Create a distinct expanded extraction/classification/graph from the pinned bytes."""
    context = verify_handoff(handoff_path)
    config_file = context["config_path"]
    source_text = config_file.read_text(encoding="utf-8")
    expanded_bbox = context["expanded_bbox"]
    bbox_text = "[" + ", ".join(format(value, ".15g") for value in expanded_bbox) + "]"
    updated, count = re.subn(r"(?m)^extract_bbox\s*=\s*\[[^\r\n]*\]", "extract_bbox = " + bbox_text, source_text, count=1)
    if count != 1:
        raise ValueError("Could not derive an expanded config from the frozen accepted config")
    updated, count = re.subn(r'(?m)^output_root\s*=\s*"[^"]+"', 'output_root = "data/generated/prototype/expanded-routing"', updated, count=1)
    if count != 1:
        raise ValueError("Could not set the expanded output directory")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    staging = ROOT / "data" / "staging" / "prototype" / ("task-4.4-expanded-" + run_id)
    staging.mkdir(parents=True, exist_ok=False)
    expanded_config = staging / "expanded-source.toml"
    expanded_config.write_text(updated, encoding="utf-8", newline="\n")

    from .cli import extract, inventory
    from .classification import run_classification
    from .graph import run_graph

    inventory_code, inventory_result = inventory(expanded_config)
    if inventory_code != 0 or inventory_result.get("status") not in {"pass", "pass_with_warnings"}:
        raise RuntimeError("Expanded source inventory failed: " + json.dumps(inventory_result, ensure_ascii=False))
    inventory_path = _repo_path(inventory_result["source_inventory"])
    inventory_report = _repo_path(inventory_result["run_report"])
    extract_code, extraction_result = extract(expanded_config, inventory_path, inventory_report)
    if extract_code != 0 or extraction_result.get("status") not in {"pass", "pass_with_warnings"}:
        raise RuntimeError("Expanded source extraction failed: " + json.dumps(extraction_result, ensure_ascii=False))
    extraction_directory = _repo_path(extraction_result["output_directory"])
    classification_code, classification_result = run_classification(
        extraction_directory,
        context["policy_config_path"],
        ROOT / "data" / "generated" / "prototype" / "expanded-routing" / "pedestrian-classification",
    )
    if classification_code != 0 or classification_result.get("status") not in {"classification_complete", "classification_complete_with_unknowns"}:
        raise RuntimeError("Expanded pedestrian classification failed: " + json.dumps(classification_result, ensure_ascii=False))
    classification_directory = _repo_path(classification_result["output_directory"])
    graph_code, graph_result = run_graph(
        extraction_directory,
        classification_directory,
        context["policy_config_path"],
        ROOT / "data" / "generated" / "prototype" / "expanded-routing" / "routing-graph",
    )
    if graph_code != 0:
        raise RuntimeError("Expanded graph construction failed: " + json.dumps(graph_result, ensure_ascii=False))
    graph_directory = _repo_path(graph_result["run_report"]).parent
    expanded_report = _json(graph_directory / "run-report.json")
    if (
        expanded_report.get("inputs", {}).get("source", {}).get("sha256") != context["source_sha256"]
        or expanded_report.get("policy", {}).get("config_sha256") != context["policy_sha256"]
        or expanded_report.get("coverage", {}).get("extract_bbox") != list(context["expanded_bbox"])
    ):
        raise RuntimeError("Expanded graph provenance or bounds do not match the accepted run")
    return {
        "status": expanded_report["status"],
        "staging_directory": staging.relative_to(ROOT).as_posix(),
        "expanded_configuration": expanded_config.relative_to(ROOT).as_posix(),
        "expanded_configuration_sha256": _sha256(expanded_config),
        "inventory": inventory_result,
        "extraction": extraction_result,
        "classification": classification_result,
        "graph": graph_result,
        "graph_directory": graph_directory.relative_to(ROOT).as_posix(),
        "graph_report_sha256": _sha256(graph_directory / "run-report.json"),
        "graph_implementation_identity": expanded_report["implementation_identity"]["sha256"],
        "source_sha256": context["source_sha256"],
        "policy_config_sha256": context["policy_sha256"],
        "coverage": expanded_report["coverage"],
        "counts": expanded_report["counts"],
    }


def _inside(point, bbox) -> bool:
    west, south, east, north = bbox
    return west <= point[0] <= east and south <= point[1] <= north


def _geo_point(start, azimuth, offset_ft, total_ft):
    if offset_ft <= 0:
        return start
    if offset_ft >= total_ft:
        return None
    lon, lat, _ = GEOD.fwd(*start, azimuth, offset_ft * 0.3048)
    return lon, lat


def geodesic_bbox_clip(start, end, bbox, *, sample_step_ft=CLIP_SAMPLE_STEP_FT, root_tolerance_ft=CLIP_ROOT_TOLERANCE_FT):
    """Find positive source-oriented geodesic intervals in a local lon/lat box.

    Samples are spaced at most 100 international feet apart. Crossings found
    between samples are refined by geodesic bisection. This is bounded and
    deliberately limited to the local prototype extent; it is not a global
    geodesic clipping algorithm.
    """
    if len(bbox) != 4 or not all(math.isfinite(value) for value in bbox):
        raise ValueError("Invalid clipping bbox")
    azimuth, _, meters = GEOD.inv(*start, *end)
    length_ft = meters / 0.3048
    if not math.isfinite(length_ft):
        raise ValueError("Nonfinite source geodesic length")
    if length_ft <= 0:
        return [], _inside(start, bbox)
    samples = max(1, math.ceil(length_ft / sample_step_ft))
    if samples > CLIP_MAX_SAMPLES_PER_SEGMENT:
        raise ValueError("Source geodesic exceeds common-core clipping resource limit")
    offsets = [length_ft * index / samples for index in range(samples + 1)]
    points = [start if index == 0 else end if index == samples else _geo_point(start, azimuth, offset, length_ft) for index, offset in enumerate(offsets)]
    west, south, east, north = bbox
    boundaries = ((0, west), (0, east), (1, south), (1, north))
    breaks = set(offsets)
    touches = any(_inside(point, bbox) for point in points)

    def at(offset):
        if offset <= 0:
            return start
        if offset >= length_ft:
            return end
        return _geo_point(start, azimuth, offset, length_ft)

    for index in range(samples):
        low, high = offsets[index], offsets[index + 1]
        point_low, point_high = points[index], points[index + 1]
        for axis, boundary in boundaries:
            value_low, value_high = point_low[axis] - boundary, point_high[axis] - boundary
            if value_low == 0:
                breaks.add(low)
            if value_high == 0:
                breaks.add(high)
            if value_low * value_high >= 0:
                continue
            left, right = low, high
            sign = value_low < 0
            for _ in range(64):
                middle = (left + right) / 2
                value = at(middle)[axis] - boundary
                if abs(value) <= 1e-15 or right - left <= root_tolerance_ft:
                    left = right = middle
                    break
                if (value < 0) == sign:
                    left = middle
                else:
                    right = middle
            root = (left + right) / 2
            breaks.add(root)
            if _inside(at(root), bbox):
                touches = True

    ordered = sorted(breaks)
    clipped = []
    for low, high in zip(ordered, ordered[1:]):
        if high > low and _inside(at((low + high) / 2), bbox):
            clipped.append((low, high))
    return union_intervals(clipped), touches or bool(clipped)


def _sample_origins(coordinates, anchor_id, core_bbox, count=MAX_ORIGINS):
    """Deterministic farthest-point sample in the declared core, starting at anchor."""
    if anchor_id not in coordinates or not _inside(coordinates[anchor_id], core_bbox):
        raise ValueError("Anchor origin is outside the common core")
    project = Transformer.from_crs("EPSG:4326", "EPSG:26913", always_xy=True).transform
    candidates = {node_id: project(*point) for node_id, point in coordinates.items() if _inside(point, core_bbox)}
    if len(candidates) < count:
        raise ValueError(f"Only {len(candidates)} source nodes are available in the common core; need {count}")
    selected = [anchor_id]
    selected_xy = [candidates[anchor_id]]
    remaining = set(candidates) - {anchor_id}
    while len(selected) < count:
        choice = min(remaining, key=lambda node_id: (
            -min((candidates[node_id][0] - x) ** 2 + (candidates[node_id][1] - y) ** 2 for x, y in selected_xy),
            node_id,
        ))
        selected.append(choice)
        selected_xy.append(candidates[choice])
        remaining.remove(choice)
    return selected


def _load_candidates(graph_directory: Path, core_bbox):
    result = {}
    for row in _read_jsonl(graph_directory / "segments.jsonl"):
        intervals, intersects = geodesic_bbox_clip(row["coordinates"][0], row["coordinates"][1], core_bbox)
        if not intersects:
            continue
        result[row["candidate_id"]] = {
            "way_id": row["way_id"],
            "sequence": row["sequence"],
            "from_node_id": row["from_node_id"],
            "to_node_id": row["to_node_id"],
            "eligibility": row["eligibility"],
            "direction": row["direction"],
            "proposed_direction": row["proposed_direction"],
            "from_node_disposition": row["from_node_disposition"],
            "to_node_disposition": row["to_node_disposition"],
            "reason_codes": row["reason_codes"],
            "core_geometry_intervals_ft": intervals,
        }
    return result


def _observation(graph_id, candidate_map, coordinates, result, origin_id, source_sha256, policy_sha256, core_bbox):
    clipped_nodes = {node_id: seconds for node_id, seconds in (result.node_seconds or {}).items() if node_id in coordinates and _inside(coordinates[node_id], core_bbox)}
    clipped_intervals = {}
    if result.intervals_ft is not None:
        for candidate_id, intervals in result.intervals_ft.items():
            core_ranges = candidate_map.get(candidate_id, {}).get("core_geometry_intervals_ft", [])
            clipped = []
            for low, high in intervals:
                for core_low, core_high in core_ranges:
                    start, end = max(low, core_low), min(high, core_high)
                    if end > start:
                        clipped.append((start, end))
            union = union_intervals(clipped)
            if union:
                clipped_intervals[candidate_id] = union
    return {
        "source_sha256": source_sha256,
        "policy_sha256": policy_sha256,
        "origin": origin_id,
        "core_bbox": list(core_bbox),
        "candidates": candidate_map,
        "node_seconds": clipped_nodes,
        "intervals_ft": clipped_intervals,
        "graph_id": graph_id,
    }


def _manual_inspection_checklist(context, origin_ids, original_frontiers, expanded_frontiers, expanded_coordinates, primary_result):
    """Create coordinate-indexed review candidates without asserting they pass."""
    accepted = context["accepted_origin"]
    anchor = accepted["source_node_id"]
    origin_point = context["original_coordinates"][anchor]
    extraction_directory = _repo_path(context["original_report"]["inputs"]["extraction_directory"])
    barrier_candidates = []
    for row in _read_jsonl(extraction_directory / "nodes.jsonl"):
        if "barrier" not in row.get("tags", {}):
            continue
        point = (row["lon"], row["lat"])
        if not _inside(point, context["original_bbox"]):
            continue
        barrier_candidates.append({
            "node_id": row["osm_id"], "longitude": row["lon"], "latitude": row["lat"],
            "barrier_tag": row["tags"].get("barrier"), "highway_tag": row["tags"].get("highway"),
            "foot_tag": row["tags"].get("foot"), "included_graph_node": row["osm_id"] in context["original_coordinates"],
        })
    barrier_candidates.sort(key=lambda row: (
        (row["longitude"] - origin_point[0]) ** 2 + (row["latitude"] - origin_point[1]) ** 2,
        int(row["node_id"]),
    ))

    def edge_point(nodes, coordinates, side, bbox):
        west, south, east, north = bbox
        choices = []
        for node_id in nodes:
            lon, lat = coordinates[node_id]
            if side == "west" and lon <= west + 0.002:
                score = abs(lon - west) + max(0, south - lat, lat - north)
            elif side == "east" and lon >= east - 0.002:
                score = abs(lon - east) + max(0, south - lat, lat - north)
            elif side == "south" and lat <= south + 0.002:
                score = abs(lat - south) + max(0, west - lon, lon - east)
            elif side == "north" and lat >= north - 0.002:
                score = abs(lat - north) + max(0, west - lon, lon - east)
            else:
                continue
            choices.append((score, node_id, lon, lat))
        if not choices:
            return {"side": side, "status": "no_frontier_candidate_found", "not_an_absence_claim": True}
        _, node_id, lon, lat = min(choices)
        return {"side": side, "status": "candidate_for_review", "node_id": node_id,
                "longitude": lon, "latitude": lat, "not_verified_in_GIS": True}

    original_edge_candidates = [edge_point(original_frontiers, context["original_coordinates"], side, context["original_bbox"])
                                for side in ("west", "east", "south", "north")]
    expanded_edge_candidates = [edge_point(expanded_frontiers, expanded_coordinates, side, context["expanded_bbox"])
                                for side in ("west", "east", "south", "north")]
    return {
        "status": "review_locations_prepared_manual_GIS_review_not_run",
        "cases": [
            {"case": "urban accepted diagnostic origin", "status": "candidate_for_review",
             "origin_id": accepted["id"], "source_node_id": anchor,
             "longitude": origin_point[0], "latitude": origin_point[1],
             "station_entrance_verified": False},
            {"case": "kerb node with a raw barrier tag", "status": "candidate_for_review" if barrier_candidates else "not_found_in_current_extract",
             "candidates": barrier_candidates[:5], "not_an_absence_claim": True,
             "scope_note": "Policy 0.3 is a general pedestrian profile; this is not a wheelchair accessibility finding."},
            {"case": "suburban context", "status": "reviewer_location_selection_required",
             "candidate_source_node_id": origin_ids[-1],
             "longitude": context["original_coordinates"][origin_ids[-1]][0],
             "latitude": context["original_coordinates"][origin_ids[-1]][1],
             "location_character_not_verified": True},
            {"case": "rural context", "status": "not_run_no_additional_region_configuration",
             "reason": "Only the accepted Denver Union extract is configured; additional regions require a reviewed configuration."},
            {"case": "original extract boundary", "status": "candidate_for_review",
             "bbox_lonlat": list(context["original_bbox"]), "frontier_candidates": original_edge_candidates,
             "reached_frontier_count_from_primary_origin": len(primary_result.frontier)},
            {"case": "expanded extract boundary", "status": "candidate_for_review",
             "bbox_lonlat": list(context["expanded_bbox"]), "frontier_candidates": expanded_edge_candidates},
        ],
    }


def _route_workload(graph_segments, coordinates, readiness, origins, seconds_per_foot, budget, frontier_nodes):
    measured = {}
    start = time.perf_counter()
    for origin_id in origins:
        origin_start = time.perf_counter()
        result = traverse(
            graph_segments,
            Origin(node=origin_id),
            budget,
            seconds_per_foot,
            Readiness(readiness.policy_blockers, "not_established", frontier_nodes, True),
        )
        if result.node_seconds is None or result.intervals_ft is None or result.computation_status not in {"incomplete", "incomplete_coverage"}:
            raise ValueError(f"Origin {origin_id} did not produce an explicit incomplete diagnostic: {result.error or result.computation_status}")
        measured[origin_id] = {"result": result, "seconds": time.perf_counter() - origin_start}
    return measured, time.perf_counter() - start


def _costs_by_interval(segments, nodes_seconds, intervals, seconds_per_foot):
    by_id = {segment.id: segment for segment in segments}
    rows = []
    for candidate_id, ranges in intervals.items():
        segment = by_id[candidate_id]
        for low, high in ranges:
            low_costs = []
            high_costs = []
            if segment.direction in {"both", "forward"} and segment.start in nodes_seconds:
                low_costs.append(nodes_seconds[segment.start] + low * seconds_per_foot)
                high_costs.append(nodes_seconds[segment.start] + high * seconds_per_foot)
            if segment.direction in {"both", "reverse"} and segment.end in nodes_seconds:
                low_costs.append(nodes_seconds[segment.end] + (segment.length_ft - low) * seconds_per_foot)
                high_costs.append(nodes_seconds[segment.end] + (segment.length_ft - high) * seconds_per_foot)
            if not low_costs or not high_costs:
                raise ValueError("Reachable interval has no reached directionally allowed endpoint")
            rows.append({"candidate_id": candidate_id, "from_offset_ft": low, "to_offset_ft": high,
                         "length_ft": high - low, "seconds_at_from_offset": min(low_costs),
                         "seconds_at_to_offset": min(high_costs)})
    return rows


def _densified_geodesic(start, end, low, high, total_length_ft):
    first = interpolate(start, end, low, geographic=True)
    last = interpolate(start, end, high, geographic=True)
    pieces = max(1, math.ceil((high - low) / 100))
    points = [first]
    azimuth, _, _ = GEOD.inv(*start, *end)
    for index in range(1, pieces):
        offset = low + (high - low) * index / pieces
        lon, lat, _ = GEOD.fwd(*start, azimuth, offset * 0.3048)
        points.append((lon, lat))
    points.append(last)
    return points


def _write_inspection_gpkg(path: Path, accepted_origin, coordinates, primary, segments, core_bbox, seconds_per_foot, output_summary):
    import geopandas as gpd
    import pandas as pd
    import pyogrio
    from shapely.geometry import LineString, Point

    origin_id = accepted_origin["id"]
    origin_node = accepted_origin["source_node_id"]
    origin_point = coordinates[origin_node]
    result = primary["result"]
    if result.node_seconds is None or result.intervals_ft is None:
        raise ValueError("Primary accepted origin has no executed costs")
    by_id = {segment.id: segment for segment in segments}
    point_frame = gpd.GeoDataFrame([{
        "origin_id": origin_id, "source_node_id": origin_node,
        "entrance_verified": False, "access_distance_ft": 0.0,
        "result_status": result.computation_status,
    }], geometry=[Point(origin_point)], crs="EPSG:4326")
    node_rows = [{"node_id": node_id, "seconds": seconds, "geometry": Point(coordinates[node_id])}
                 for node_id, seconds in result.node_seconds.items()]
    node_frame = gpd.GeoDataFrame(node_rows, columns=["node_id", "seconds", "geometry"], geometry="geometry", crs="EPSG:4326")
    cost_rows = _costs_by_interval(segments, result.node_seconds, result.intervals_ft, seconds_per_foot)
    interval_rows = []
    for cost in cost_rows:
        segment = by_id[cost["candidate_id"]]
        a, b = coordinates[segment.start], coordinates[segment.end]
        interval_rows.append({**cost, "way_id": segment.id.split("/")[1],
                              "from_node_id": segment.start, "to_node_id": segment.end,
                              "direction": segment.direction,
                              "geometry": LineString(_densified_geodesic(a, b, cost["from_offset_ft"], cost["to_offset_ft"], segment.length_ft))})
    interval_frame = gpd.GeoDataFrame(
        interval_rows,
        columns=["candidate_id", "from_offset_ft", "to_offset_ft", "length_ft", "seconds_at_from_offset",
                 "seconds_at_to_offset", "way_id", "from_node_id", "to_node_id", "direction", "geometry"],
        geometry="geometry", crs="EPSG:4326",
    )
    frontier_rows = [{"node_id": node_id, "remaining_seconds": seconds,
                      "coverage_status": "incomplete_coverage" if seconds > 0 else "frontier_at_budget",
                      "geometry": Point(coordinates[node_id])}
                     for node_id, seconds in result.frontier.items()]
    frontier_frame = gpd.GeoDataFrame(
        frontier_rows, columns=["node_id", "remaining_seconds", "coverage_status", "geometry"],
        geometry="geometry", crs="EPSG:4326",
    )
    connector_frame = pd.DataFrame([{
        "origin_id": origin_id, "connector_status": "not_applicable_source_node_origin",
        "connector_length_ft": 0.0, "connector_seconds": 0.0,
    }])

    layers = [
        ("origin_points", point_frame, "Point"),
        ("reached_nodes", node_frame, "Point"),
        ("reachable_edge_portions", interval_frame, "LineString"),
        ("frontier_nodes", frontier_frame, "Point"),
        ("origin_access", connector_frame, "None"),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite inspection GeoPackage: {path}")
    for index, (layer, frame, geometry_type) in enumerate(layers):
        pyogrio.write_dataframe(frame, path, layer=layer, driver="GPKG", geometry_type=geometry_type,
                                append=index > 0)

    layer_names = {name for name, _ in pyogrio.list_layers(path)}
    if layer_names != {layer for layer, _, _ in layers}:
        raise ValueError("Inspection GeoPackage layer list does not reconcile")
    listed = {name: int(pyogrio.read_info(path, layer=name)["features"]) for name in layer_names}
    for layer in ("origin_points", "reached_nodes", "reachable_edge_portions", "frontier_nodes"):
        if pyogrio.read_info(path, layer=layer)["crs"] != "EPSG:4326":
            raise ValueError("Inspection GeoPackage layer CRS is not EPSG:4326: " + layer)
    expected_counts = {"origin_points": 1, "reached_nodes": len(node_rows),
                       "reachable_edge_portions": len(interval_rows), "frontier_nodes": len(frontier_rows),
                       "origin_access": 1}
    if listed != expected_counts:
        raise ValueError("Inspection GeoPackage feature counts do not reconcile")

    reopened_origins = pyogrio.read_dataframe(path, layer="origin_points")
    if reopened_origins.iloc[0]["source_node_id"] != origin_node or not reopened_origins.geometry.iloc[0].equals(Point(origin_point)):
        raise ValueError("Reopened origin point does not match the accepted source node")
    reopened_nodes = pyogrio.read_dataframe(path, layer="reached_nodes")
    reopened_node_map = {str(row.node_id): float(row.seconds) for row in reopened_nodes.itertuples()}
    if set(reopened_node_map) != set(result.node_seconds) or any(not math.isclose(reopened_node_map[key], value, rel_tol=0, abs_tol=1e-12) for key, value in result.node_seconds.items()):
        raise ValueError("Reopened reached-node IDs or costs do not reconcile")
    reopened_intervals = pyogrio.read_dataframe(path, layer="reachable_edge_portions")
    if len(reopened_intervals) != len(interval_rows):
        raise ValueError("Reopened interval feature count does not reconcile")
    for expected, row in zip(interval_rows, reopened_intervals.itertuples()):
        if (row.candidate_id != expected["candidate_id"]
                or not math.isclose(float(row.from_offset_ft), expected["from_offset_ft"], rel_tol=0, abs_tol=1e-10)
                or not math.isclose(float(row.to_offset_ft), expected["to_offset_ft"], rel_tol=0, abs_tol=1e-10)
                or not math.isclose(float(row.length_ft), expected["length_ft"], rel_tol=0, abs_tol=1e-10)
                or not math.isclose(float(row.seconds_at_from_offset), expected["seconds_at_from_offset"], rel_tol=0, abs_tol=1e-10)
                or not math.isclose(float(row.seconds_at_to_offset), expected["seconds_at_to_offset"], rel_tol=0, abs_tol=1e-10)):
            raise ValueError("Reopened interval IDs, distances or costs do not reconcile")
        expected_start, expected_end = expected["geometry"].coords[0], expected["geometry"].coords[-1]
        actual_start, actual_end = row.geometry.coords[0], row.geometry.coords[-1]
        if any(abs(a - b) > 1e-9 for a, b in zip(expected_start, actual_start)) or any(abs(a - b) > 1e-9 for a, b in zip(expected_end, actual_end)):
            raise ValueError("Reopened reachable geometry endpoints do not reconcile")
    reopened_frontier = pyogrio.read_dataframe(path, layer="frontier_nodes")
    frontier_map = {str(row.node_id): float(row.remaining_seconds) for row in reopened_frontier.itertuples()}
    if frontier_map != result.frontier:
        raise ValueError("Reopened frontier IDs or remaining times do not reconcile")
    reopened_access = pyogrio.read_dataframe(path, layer="origin_access")
    if len(reopened_access) != 1 or reopened_access.iloc[0]["connector_status"] != "not_applicable_source_node_origin":
        raise ValueError("Reopened source-node access record does not reconcile")
    output_summary["gpkg_layers"] = listed
    output_summary["gpkg_reopen_checks"] = {
        "layer_list_and_counts": True, "origin_identity_and_geometry": True,
        "reached_node_ids_and_costs": True, "reachable_interval_ids_geometry_lengths_and_costs": True,
        "frontier_ids_and_remaining_costs": True, "source_node_has_no_connector": True,
        "crs": "EPSG:4326",
    }


def _run_worker(original_graph: Path, expanded_graph: Path, handoff_path: Path, stage: Path) -> dict:
    context = verify_handoff(handoff_path, original_graph)
    expanded_segments, expanded_coordinates, expanded_readiness, expanded_report = load_graph(expanded_graph)
    expanded_source = expanded_report.get("inputs", {}).get("source", {})
    if (
        expanded_source.get("sha256") != context["source_sha256"]
        or expanded_report.get("policy", {}).get("config_sha256") != context["policy_sha256"]
        or expanded_report.get("policy", {}).get("rule_version") != context["handoff"]["pedestrian_rule_version"]
        or expanded_report.get("policy", {}).get("scenario_id") != context["handoff"]["pedestrian_scenario_id"]
        or expanded_report.get("coverage", {}).get("extract_bbox") != list(context["expanded_bbox"])
        or expanded_report.get("coverage", {}).get("core_bbox") != list(context["core_bbox"])
    ):
        raise ValueError("Expanded graph does not match the accepted source, policy, or bounds")

    clipping_start = time.perf_counter()
    original_candidates = _load_candidates(context["original_graph"], context["core_bbox"])
    expanded_candidates = _load_candidates(expanded_graph, context["core_bbox"])
    clipping_seconds = time.perf_counter() - clipping_start
    accepted = context["accepted_origin"]
    anchor = accepted["source_node_id"]
    origin_ids = _sample_origins(context["original_coordinates"], anchor, context["core_bbox"])
    if any(node_id not in expanded_coordinates for node_id in origin_ids):
        missing = [node_id for node_id in origin_ids if node_id not in expanded_coordinates]
        raise ValueError("Expanded graph is missing deterministic common-core performance origins: " + ", ".join(missing[:10]))

    budget = context["settings"]["time_budget_seconds"]
    seconds_per_foot = SECONDS_PER_FOOT
    original_frontiers = context["original_readiness"].frontier_nodes
    expanded_frontiers = expanded_readiness.frontier_nodes
    original_start = time.perf_counter()
    original_routes, original_route_seconds = _route_workload(
        context["original_segments"], context["original_coordinates"], context["original_readiness"], origin_ids,
        seconds_per_foot, budget, original_frontiers,
    )
    original_total = time.perf_counter() - original_start
    expanded_start = time.perf_counter()
    expanded_routes, expanded_route_seconds = _route_workload(
        expanded_segments, expanded_coordinates, expanded_readiness, origin_ids,
        seconds_per_foot, budget, expanded_frontiers,
    )
    expanded_total = time.perf_counter() - expanded_start

    workload_summaries = []
    differences = []
    for count in (1, 10, 50):
        selected_ids = origin_ids[:count]
        sides = []
        for graph_id, routes, candidates, coords in (
            ("original", original_routes, original_candidates, context["original_coordinates"]),
            ("expanded", expanded_routes, expanded_candidates, expanded_coordinates),
        ):
            selected_results = [routes[node_id]["result"] for node_id in selected_ids]
            union = combined_intervals(selected_results)
            node_union = set().union(*(result.node_seconds for result in selected_results))
            sides.append({
                "graph": graph_id,
                "origins": selected_ids,
                "origin_count": count,
                "total_traversal_seconds": sum(routes[node_id]["seconds"] for node_id in selected_ids),
                "reached_node_count_sum": sum(len(result.node_seconds) for result in selected_results),
                "unique_reached_node_count": len(node_union),
                "unique_reachable_source_length_ft": math.fsum(high - low for ranges in union.values() for low, high in ranges),
                "result_status_counts": dict(sorted(Counter(result.computation_status for result in selected_results).items())),
                "policy_blockers": list((context["original_readiness"] if graph_id == "original" else expanded_readiness).policy_blockers),
                "coverage_readiness": "not_established",
                "origin_role": "accepted_diagnostic_source_node" if graph_id == "original" and count == 1 else "deterministic_core_source_node_performance_sample",
            })
        workload_summaries.append({"origin_count": count, "results": sides})
        per_origin_differences = []
        for origin_id in selected_ids:
            original_observation = _observation(
                "original", original_candidates, context["original_coordinates"], original_routes[origin_id]["result"],
                origin_id, context["source_sha256"], context["policy_sha256"], context["core_bbox"],
            )
            expanded_observation = _observation(
                "expanded", expanded_candidates, expanded_coordinates, expanded_routes[origin_id]["result"],
                origin_id, context["source_sha256"], context["policy_sha256"], context["core_bbox"],
            )
            comparison = compare_core(original_observation, expanded_observation,
                                      cost_tolerance_seconds=CORE_COST_TOLERANCE_SECONDS,
                                      interval_tolerance_ft=CORE_INTERVAL_TOLERANCE_FT)
            for item in comparison["differences"]:
                item["origin_id"] = origin_id
            differences.extend(comparison["differences"])
            per_origin_differences.append({"origin_id": origin_id, "status": comparison["status"], "difference_count": len(comparison["differences"])})
        workload_summaries[-1]["common_core_comparison"] = {
            "status": "differences_require_review" if any(item["difference_count"] for item in per_origin_differences) else "agreement_supporting_evidence_only",
            "origin_results": per_origin_differences,
            "difference_count": sum(item["difference_count"] for item in per_origin_differences),
            "coverage_readiness": "not_established",
        }

    primary = original_routes[anchor]
    checklist = _manual_inspection_checklist(context, origin_ids, original_frontiers, expanded_frontiers,
                                             expanded_coordinates, primary["result"])
    report = {
        "report_version": "regional-routing-diagnostic-1",
        "status": "completed_with_incomplete_regional_results",
        "analytical_promotion": "blocked_by_unknown_candidates_unsupported_restrictions_and_unestablished_coverage",
        "inputs": {
            "handoff": context["handoff_path"].relative_to(ROOT).as_posix(),
            "accepted_source_sha256": context["source_sha256"],
            "original_graph_directory": context["original_graph"].relative_to(ROOT).as_posix(),
            "original_graph_report_sha256": _sha256(context["original_graph"] / "run-report.json"),
            "original_graph_implementation_identity": context["original_report"]["implementation_identity"]["sha256"],
            "expanded_graph_directory": expanded_graph.relative_to(ROOT).as_posix(),
            "expanded_graph_report_sha256": _sha256(expanded_graph / "run-report.json"),
            "expanded_graph_implementation_identity": expanded_report["implementation_identity"]["sha256"],
            "policy_config_sha256": context["policy_sha256"],
            "policy_authority_sha256": context["policy_authority_sha256"],
            "routing_acceptance_manifest_sha256": context["handoff"]["routing_reference_acceptance_sha256"],
            "routing_settings_sha256": _sha256(ROOT / "pipeline" / "config" / "routing-benchmarks.v1.toml"),
            "routing_runner_implementation_identity": code_identity()["sha256"],
        },
        "graph_sizes": {
            "original": context["original_report"]["counts"],
            "expanded": expanded_report["counts"],
        },
        "settings": {
            "time_budget_seconds": budget, "seconds_per_foot": seconds_per_foot,
            "length_unit": "international_foot", "time_unit": "second",
            "core_bbox_lonlat": list(context["core_bbox"]),
            "original_extract_bbox_lonlat": list(context["original_bbox"]),
            "expanded_extract_bbox_lonlat": list(context["expanded_bbox"]),
            "coverage_readiness": "not_established",
            "unknown_candidates": context["original_report"]["counts"]["candidates_by_eligibility"].get("unknown", 0),
            "unsupported_restrictions": context["original_report"]["relations"].get("unsupported", 0),
            "source_node_origin_mode": "exact_source_node_no_connector_or_entrance_claim",
            "edge_snap_experiment": "not_run_disabled_in_accepted_settings",
            "common_core_cost_tolerance_seconds": CORE_COST_TOLERANCE_SECONDS,
            "common_core_interval_tolerance_ft": CORE_INTERVAL_TOLERANCE_FT,
            "common_core_clipping": {"method": "WGS84 geodesic source-oriented intervals", "sample_step_max_ft": CLIP_SAMPLE_STEP_FT,
                                     "root_tolerance_ft": CLIP_ROOT_TOLERANCE_FT,
                                     "limit_samples_per_segment": CLIP_MAX_SAMPLES_PER_SEGMENT,
                                     "intersection_completeness_proven": False},
        },
        "primary_origin": {
            "origin_id": accepted["id"], "source_node_id": anchor,
            "longitude": accepted["longitude"], "latitude": accepted["latitude"],
            "station_entrance_verified": False, "connector_distance_ft": 0,
            "computation_status": primary["result"].computation_status,
            "origin_status": primary["result"].origin_status,
            "policy_readiness": primary["result"].policy_readiness,
            "coverage_readiness": primary["result"].coverage_readiness,
            "policy_blockers": list(primary["result"].blockers),
            "reached_nodes": len(primary["result"].node_seconds or {}),
            "reachable_candidate_intervals": sum(len(rows) for rows in (primary["result"].intervals_ft or {}).values()),
            "unique_source_length_ft": primary["result"].unique_source_length_ft,
            "frontier_nodes_reached": len(primary["result"].frontier),
        },
        "performance": {
            "origin_selection": "accepted anchor plus deterministic farthest-point source nodes within common core; EPSG:26913 metric",
            "sample_origin_ids": origin_ids,
            "sample_origins_are_station_locations": False,
            "original_total_traversal_seconds_50_origins": original_route_seconds,
            "original_wall_seconds_for_all_50": original_total,
            "expanded_total_traversal_seconds_50_origins": expanded_route_seconds,
            "expanded_wall_seconds_for_all_50": expanded_total,
            "common_core_clipping_seconds_for_both_graphs": clipping_seconds,
            "workloads": workload_summaries,
            "hardware": {"platform": sys.platform, "python": sys.version.split()[0], "processor": __import__("platform").processor(),
                         "logical_cpu_count": os.cpu_count()},
            "timing_scope": "in-process Dijkstra calls; excludes graph loading, core clipping, and GeoPackage export; outer supervisor records full wall time and sampled process-tree RSS",
        },
        "comparison": {
            "status": "differences_require_review" if differences else "agreement_supporting_evidence_only",
            "difference_count": len(differences),
            "differences_file": "common-core-differences.json",
            "coverage_readiness": "not_established",
            "matching_extracts_or_fixed_margin_prove_completeness": False,
        },
        "boundary_diagnostics": {
            "frontier_definition": "included graph endpoint nodes on or outside the configured extraction bbox",
            "original_frontier_candidate_count": len(original_frontiers),
            "original_primary_origin_reached_frontier_count": len(primary["result"].frontier),
            "expanded_frontier_candidate_count": len(expanded_frontiers),
            "expanded_primary_origin_reached_frontier_count": len(expanded_routes[anchor]["result"].frontier),
            "coverage_readiness": "not_established",
            "warning": "The conservative frontier detector does not find every omitted way or prove complete coverage.",
        },
        "manual_inspection_checklist": checklist,
        "checks": {"accepted_reference_hashes": True, "original_graph_report_hash": True,
                   "original_graph_payload_hashes_and_structure": True, "expanded_graph_payload_hashes_and_structure": True,
                   "source_identity_match": True, "policy_identity_match": True,
                   "primary_origin_source_membership": True, "primary_traversal_executed": True,
                   "1_10_50_origin_diagnostics_executed": True,
                   "common_core_membership_and_clipping_completed": True,
                   "boundary_warnings_retained": True,
                   "gpkg_layers_reopened_and_reconciled": False},
        "inspection_export": {},
    }
    stage.mkdir(parents=True, exist_ok=True)
    _write_inspection_gpkg(stage / "routing-inspection.gpkg", accepted, context["original_coordinates"], primary,
                           context["original_segments"], context["core_bbox"], seconds_per_foot, report["inspection_export"])
    _write_json(stage / "common-core-differences.json", {"status": report["comparison"]["status"], "differences": differences})
    with (stage / "common-core-differences.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("origin_id", "category", "id", "kind", "original", "expanded"), extrasaction="ignore")
        writer.writeheader()
        for row in differences:
            writer.writerow({key: json.dumps(row.get(key), ensure_ascii=False, sort_keys=True) if key in {"original", "expanded"} else row.get(key, "") for key in writer.fieldnames})
    output_files = {}
    for path in sorted(stage.iterdir(), key=lambda value: value.name):
        if path.is_file():
            output_files[path.name] = {"bytes": path.stat().st_size, "sha256": _sha256(path)}
    report["output_files"] = output_files
    report["checks"]["gpkg_layers_reopened_and_reconciled"] = True
    return report


def run_regional_routing(handoff_path: str | Path, expanded_graph: str | Path, *, original_graph: str | Path | None = None) -> dict:
    """Run and promote a bounded routing/comparison worker with process-tree limits."""
    from .cli import _promote_directory, _supervise

    context = verify_handoff(handoff_path, original_graph)
    expanded_path = _repo_path(expanded_graph)
    if not expanded_path.is_dir():
        raise ValueError("Expanded graph directory does not exist")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    stage_root = ROOT / "data" / "staging" / "prototype" / ("regional-routing-" + run_id)
    stage_root.mkdir(parents=True, exist_ok=False)
    candidate = stage_root / "candidate"
    result_path = stage_root / "worker-result.json"
    command = [sys.executable, "-m", "flm_pipeline.regional_routing", "--worker",
               "--handoff", str(context["handoff_path"]), "--original-graph", str(context["original_graph"]),
               "--expanded-graph", str(expanded_path), "--stage", str(candidate), "--result", str(result_path)]
    supervision = _supervise(command, ROOT, stage_root / "worker.log", 1200, 4 * 1024**3)
    if (supervision.get("exit_code") != 0 or supervision.get("failure_reason") is not None
            or not supervision.get("child_cleanup_complete") or not result_path.is_file()):
        failure = {"status": "fail", "supervision": supervision, "staging_directory": stage_root.relative_to(ROOT).as_posix()}
        _write_json(stage_root / "run-report.json", failure)
        raise RuntimeError("Regional routing worker failed: " + json.dumps(failure, ensure_ascii=False))
    worker_report = _json(result_path)
    if not _checks_pass(worker_report.get("checks")):
        raise RuntimeError("Regional routing worker validation checks failed")
    generated_root = ROOT / "data" / "generated" / "prototype" / "regional-routing"
    generated_root.mkdir(parents=True, exist_ok=True)
    final = generated_root / run_id
    if final.exists():
        raise FileExistsError("Refusing to overwrite regional routing run")
    _promote_directory(candidate, final)
    for name, item in worker_report["output_files"].items():
        target = final / name
        if not target.is_file() or target.stat().st_size != item["bytes"] or _sha256(target) != item["sha256"]:
            raise ValueError("Promoted regional routing payload mismatch: " + name)
    worker_report.update({"run_id": run_id, "supervision": supervision,
                          "status": "completed_with_incomplete_regional_results",
                          "run_report": (final / "run-report.json").relative_to(ROOT).as_posix(),
                          "output_directory": final.relative_to(ROOT).as_posix()})
    worker_report["checks"].update({"worker_exit_zero": True, "resource_limits_passed": True,
                                    "promoted_output_hashes_verified": True})
    _write_json(final / "run-report.json", worker_report)
    _write_json(stage_root / "run-report.json", {"status": "promoted", "final_directory": final.relative_to(ROOT).as_posix(),
                                                  "run_report": worker_report["run_report"], "supervision": supervision})
    return worker_report


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run local Task 4.4 regional routing diagnostics")
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--expanded-graph", type=Path)
    parser.add_argument("--prepare-expanded", action="store_true")
    parser.add_argument("--original-graph", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--stage", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--result", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.prepare_expanded:
            report = prepare_expanded_graph(args.handoff)
        elif args.worker:
            if args.stage is None or args.result is None or args.expanded_graph is None or args.original_graph is None:
                raise ValueError("Worker arguments are incomplete")
            report = _run_worker(_repo_path(args.original_graph), _repo_path(args.expanded_graph), args.handoff, _repo_path(args.stage))
            _write_json(_repo_path(args.result), report)
        else:
            if args.expanded_graph is None:
                raise ValueError("Provide --expanded-graph or use --prepare-expanded")
            report = run_regional_routing(args.handoff, args.expanded_graph, original_graph=args.original_graph)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "fail", "error": str(error)}, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

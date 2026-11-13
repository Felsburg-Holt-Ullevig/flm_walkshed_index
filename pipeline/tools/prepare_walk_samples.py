"""Prepare three separate local OSM extracts, pedestrian graphs, and tile samples."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

from flm_pipeline.classification import run_classification  # noqa: E402
from flm_pipeline.cli import extract, inventory  # noqa: E402
from flm_pipeline.graph import run_graph  # noqa: E402
from flm_pipeline.pedestrian_config import load_pedestrian_settings  # noqa: E402
from flm_pipeline.walk_samples import build_sample_records, sample_bbox  # noqa: E402
from flm_pipeline.walk_tiles import PACKAGE_REL, build_from_records, verify_records  # noqa: E402

HANDOFF = Path("docs/planning/2026-11-02/active-regional-run.json")
POLICY = Path("pipeline/config/pedestrian-policy.example.toml")
SAMPLES = {
    "G01": (-104.6928167, 40.4249),
    "B01": (-105.06877, 39.91758),
    "F01": (-105.81945, 39.94776),
}
DEFAULT_STAGE_SECONDS = 1200


def _positive_stage_seconds(value):
    try:
        seconds = int(value)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError("must be a positive integer number of seconds") from error
    if seconds <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer number of seconds")
    return seconds


def _replace_stage_seconds(config_text, stage_seconds):
    if type(stage_seconds) is not int or stage_seconds <= 0:
        raise ValueError("stage_seconds must be a positive integer")
    matches = list(re.finditer(r"(?m)^seconds\s*=\s*\d+\s*$", config_text))
    if len(matches) != 1:
        raise ValueError("Accepted configuration must contain exactly one integer limits.seconds setting")
    match = matches[0]
    return config_text[:match.start()] + f"seconds = {stage_seconds}" + config_text[match.end():]


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _config_text(source_path, bbox, origin, output_root, case, stage_seconds=DEFAULT_STAGE_SECONDS):
    source = source_path.read_text(encoding="utf-8")
    box = "[" + ", ".join(format(value, ".15g") for value in bbox) + "]"
    source, n = re.subn(r"(?m)^region_id\s*=\s*\"[^\"]+\"", f'region_id = "walk-sample-{case.lower()}-v1"', source, count=1)
    if n != 1:
        raise ValueError("Accepted configuration has no unique region_id")
    for key in ("core_bbox", "extract_bbox", "expanded_bbox"):
        source, n = re.subn(rf"(?m)^{key}\s*=\s*\[[^\r\n]*\]", f"{key} = {box}", source, count=1)
        if n != 1:
            raise ValueError(f"Accepted configuration has no unique {key}")
    source, n = re.subn(r"(?m)^station_lonlat\s*=\s*\[[^\r\n]*\]", "station_lonlat = [" + ", ".join(format(value, ".15g") for value in origin) + "]", source, count=1)
    if n != 1:
        raise ValueError("Accepted configuration has no unique station_lonlat")
    source, n = re.subn(r'(?m)^output_root\s*=\s*"[^"]+"', f'output_root = "{output_root.as_posix()}"', source, count=1)
    if n != 1:
        raise ValueError("Accepted configuration has no unique output_root")
    return _replace_stage_seconds(source, stage_seconds)


def _sample_policy_text(source_path):
    source = source_path.read_text(encoding="utf-8")
    source, count = re.subn(r'(?m)^scenario_id\s*=\s*"[^"]+"', 'scenario_id = "plan-a-walk-reference-2.8-v1"', source, count=1)
    if count != 1:
        raise ValueError("Accepted pedestrian policy has no unique scenario_id setting")
    source, count = re.subn(r"(?m)^speed_mph\s*=\s*[^\r\n]+", "speed_mph = 2.8", source, count=1)
    if count != 1:
        raise ValueError("Accepted pedestrian policy has no unique speed_mph setting")
    return source


def _relation_counts(graph_report):
    relations = graph_report.get("relations", {})
    if not isinstance(relations, dict):
        raise ValueError("graph report relations must be an object")
    counts = {}
    for key in ("retained", "unsupported", "unresolved_members"):
        value = relations.get(key, 0)
        if type(value) is not int or value < 0:
            raise ValueError(f"graph report relations.{key} must be a nonnegative integer")
        counts[key] = value
    return counts


def _prepare_case(case, origin, bbox, margin_minimum, config_path, destination, handoff, stage_seconds):
    case_root = destination / case
    if case_root.exists():
        raise FileExistsError(f"Refusing to overwrite sample folder: {case_root}")
    case_root.mkdir(parents=True)
    output_root = Path("data/generated/prototype/walk-samples") / destination.name / case / "pipeline"
    case_config = case_root / "source.toml"
    case_config.write_text(_config_text(config_path, bbox, origin, output_root, case, stage_seconds), encoding="utf-8", newline="\n")
    case_policy = case_root / "pedestrian-policy-2.8.toml"
    case_policy.write_text(_sample_policy_text(ROOT / POLICY), encoding="utf-8", newline="\n")
    settings = load_pedestrian_settings(case_policy)
    if settings.scenario_id != "plan-a-walk-reference-2.8-v1" or settings.speed_mph != 2.8:
        raise ValueError("Sample policy must use the exact 2.8 mph reference scenario")
    inventory_code, inventory_result = inventory(case_config)
    if inventory_code or inventory_result.get("status") not in {"pass", "pass_with_warnings"}:
        raise RuntimeError(f"{case}: inventory failed: {inventory_result}")
    inventory_path = ROOT / inventory_result["source_inventory"]
    inventory_report_path = ROOT / inventory_result["run_report"]
    extraction_code, extraction_result = extract(case_config, inventory_path, inventory_report_path)
    if extraction_code or extraction_result.get("status") not in {"pass", "pass_with_warnings"}:
        raise RuntimeError(f"{case}: extraction failed: {extraction_result}")
    extraction_directory = ROOT / extraction_result["output_directory"]
    classification_code, classification_result = run_classification(
        extraction_directory, case_policy,
        ROOT / output_root / "pedestrian-classification")
    if classification_code or classification_result.get("status") not in {"classification_complete", "classification_complete_with_unknowns"}:
        raise RuntimeError(f"{case}: classification failed: {classification_result}")
    classification_directory = ROOT / classification_result["output_directory"]
    graph_code, graph_result = run_graph(
        extraction_directory, classification_directory, case_policy,
        ROOT / output_root / "routing-graph")
    if graph_code:
        raise RuntimeError(f"{case}: graph failed: {graph_result}")
    graph_directory = (ROOT / graph_result["run_report"]).parent
    segments, nodes, arcs, ways, counts = build_sample_records(graph_directory, extraction_directory, bbox)
    graph_report = _json(graph_directory / "run-report.json")
    if graph_report.get("inputs", {}).get("source", {}).get("sha256") != handoff["source_sha256"]:
        raise ValueError(f"{case}: graph OSM SHA-256 does not match the accepted handoff")
    inventory_data = _json(inventory_path)
    osm = inventory_data["sources"]["osm"]
    accepted_manifest = _json(ROOT / PACKAGE_REL / "manifest.json")
    accepted_inventory_path = ROOT / PACKAGE_REL / accepted_manifest["files"]["inventory"]["path"]
    accepted_sources = _json(accepted_inventory_path)["sources"]
    accepted_osm = (next((row for row in accepted_sources if row.get("kind") == "osm"), None)
                    if isinstance(accepted_sources, list) else accepted_sources.get("osm"))
    if not isinstance(accepted_osm, dict) or accepted_osm.get("sha256") != handoff["source_sha256"]:
        raise ValueError("Accepted package inventory does not match the pinned OSM source hash")
    if accepted_manifest["identity"]["rule_version"] != graph_report["policy"]["rule_version"]:
        raise ValueError("New graph pedestrian policy differs from the accepted Denver package")
    accepted_vintage = accepted_osm.get("observed_vintage", accepted_osm.get("observed_header_vintage"))
    if osm.get("observed_header_vintage") != accepted_vintage:
        raise ValueError("Fresh inventory OSM timestamp differs from the accepted source metadata")
    relations = _relation_counts(graph_report)
    metadata = {
        "osm_data_timestamp": accepted_vintage,
        "download_date": str(accepted_osm.get("downloaded_at", ""))[:10],
        "walking_rule_version": graph_report["policy"]["rule_version"],
        "selection": "highway-node-in-bbox-complete-way-1; pedestrian-policy-0.3 included segments",
        "limitations": [
            f"Sample includes {counts['included_segments']} included segments; {counts['excluded_segments']} excluded and {counts['unknown_segments']} unknown whole-way candidates are omitted.",
            "Coverage is not established; the sample bbox is an extraction boundary, not proof of complete streets.",
            f"Source relations retained: {relations['retained']}; unsupported restrictions: {relations['unsupported']}; unresolved members: {relations['unresolved_members']}.",
            "No barrier-aware origin connection, wheelchair assessment, crossing delay, slope cost, or turn delay is modeled.",
            "Public redistribution is not approved.",
        ],
    }
    release_id = f"{case.lower()}-{destination.name}"
    tile_directory = case_root / "tiles"
    manifest = build_from_records(
        segments, nodes, arcs, ways,
        source_release_id="osm-" + handoff["source_sha256"][:12],
        excluded_count=counts["excluded_segments"], unknown_count=counts["unknown_segments"],
        output_dir=tile_directory, release_id=release_id, source_metadata=metadata)
    verification = verify_records(segments, nodes, arcs, ways, tile_directory, manifest)
    return {
        "origin_lonlat": list(origin), "extract_bbox": list(bbox),
        "minimum_origin_to_bbox_edge_ft": margin_minimum,
        "source_sha256": handoff["source_sha256"],
        "pedestrian_rule_version": graph_report["policy"]["rule_version"],
        "pedestrian_scenario_id": graph_report["policy"]["scenario_id"],
        "pedestrian_speed_mph": graph_report["policy"]["speed_mph"],
        "stage_timeout_seconds": stage_seconds,
        "inventory_directory": inventory_result["run_report"].rsplit("/", 1)[0],
        "extraction_directory": extraction_result["output_directory"],
        "classification_directory": classification_result["output_directory"],
        "graph_directory": graph_directory.relative_to(ROOT).as_posix(),
        "tile_directory": tile_directory.relative_to(ROOT).as_posix(),
        "counts": counts, "verification": verification,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-id", required=True)
    parser.add_argument(
        "--stage-seconds", type=_positive_stage_seconds, default=DEFAULT_STAGE_SECONDS,
        help="inventory and extraction worker timeout in seconds (default: 1200)",
    )
    args = parser.parse_args(argv)
    if re.fullmatch(r"[A-Za-z0-9_-]+", args.release_id) is None:
        parser.error("release ID may contain only letters, digits, hyphens and underscores")
    handoff_path = ROOT / HANDOFF
    handoff = _json(handoff_path)
    config_path = ROOT / handoff["config"]
    if not config_path.is_file():
        parser.error(f"Pinned accepted configuration is missing: {config_path}")
    raw_config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    osm_path = ROOT / raw_config["sources"]["osm"]["path"]
    if not osm_path.is_file() or raw_config["sources"]["osm"]["expected_sha256"] != handoff["source_sha256"]:
        parser.error("Pinned accepted OSM source path/hash does not match the handoff")
    destination = ROOT / "data/generated/prototype/walk-samples" / args.release_id
    if destination.exists():
        print(f"ERROR: destination already exists; refusing overwrite: {destination}", file=sys.stderr)
        return 2
    destination.mkdir(parents=True, exist_ok=False)
    try:
        cases = {}
        for case, origin in SAMPLES.items():
            bbox, minimum = sample_bbox(origin)
            print(f"{case}: starting fresh inventory and extraction; sample bounds {bbox}", flush=True)
            cases[case] = _prepare_case(case, origin, bbox, minimum, config_path, destination, handoff, args.stage_seconds)
        index = {"format": "walk-sample-index", "version": 1, "release_id": args.release_id,
                 "source_sha256": handoff["source_sha256"], "pedestrian_rule_version": handoff["pedestrian_rule_version"],
                 "pedestrian_scenario_id": "plan-a-walk-reference-2.8-v1", "pedestrian_speed_mph": 2.8,
                 "stage_timeout_seconds": args.stage_seconds,
                 "cases": cases}
        (destination / "sample-index.json").write_text(json.dumps(index, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
        print(f"Prepared {len(cases)} samples under {destination}")
        return 0
    except Exception as error:
        print(f"ERROR: {error}; partial output retained at {destination}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

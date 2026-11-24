"""Compare the baseline and Larimer inclusive-road GeoPackages read-only."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sqlite3


BASELINE_SHA256 = "011ee731145be9d67f0b8056d712ea39b8f7e8817f2650af868ea705698ebeac"
EXPECTED_NEW = "way/329495950/segment/2"
EXPECTED_CROSSING = "way/1389221449/segment/2"
EXPECTED_ABSENT = ("way/308279184/segment/2", "way/6164850/segment/1")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def rows(path: Path):
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        columns = [item[1] for item in connection.execute("PRAGMA table_info(pedestrian_edges)")]
        if not columns or "segment_id" not in columns or "geom" not in columns:
            raise ValueError(f"pedestrian_edges schema missing required columns: {path}")
        selected = [name for name in columns if name != "fid"]
        query = "SELECT " + ",".join('"' + name.replace('"', '""') + '"' for name in selected) + " FROM pedestrian_edges"
        for row in connection.execute(query):
            yield dict(zip(selected, row, strict=True))
    finally:
        connection.close()


def layer_counts(path: Path) -> dict[str, int]:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        return {
            layer: connection.execute(f'SELECT COUNT(*) FROM "{layer}"').fetchone()[0]
            for layer in ("pedestrian_edges", "pedestrian_nodes")
        }
    finally:
        connection.close()


def audit_records(path: Path) -> dict[str, dict]:
    result = {}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            result[row["candidate_id"]] = row
    return result


def check_saved_endpoints(candidate: Path, new_edges) -> None:
    connection = sqlite3.connect(candidate.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        saved = {node_id for (node_id,) in connection.execute("SELECT node_id FROM pedestrian_nodes") if node_id is not None}
    finally:
        connection.close()
    for edge in new_edges:
        for field in ("from_node_id", "to_node_id"):
            node_id = edge.get(field)
            if node_id not in saved:
                raise ValueError(f"New segment {edge['segment_id']} has missing saved endpoint {field}={node_id!r} in pedestrian_nodes")


def compare(baseline: Path, candidate: Path, baseline_audit: Path, candidate_audit: Path, output_csv: Path, output_json: Path) -> None:
    baseline_hash_before = digest(baseline)
    if baseline_hash_before != BASELINE_SHA256:
        raise ValueError(f"baseline GeoPackage hash mismatch: {baseline_hash_before}")
    baseline_rows = {row["segment_id"]: row for row in rows(baseline)}
    candidate_rows = {row["segment_id"]: row for row in rows(candidate)}
    if len(baseline_rows) != layer_counts(baseline)["pedestrian_edges"] or len(candidate_rows) != layer_counts(candidate)["pedestrian_edges"]:
        raise ValueError("duplicate segment IDs in reopened GeoPackage")

    added_ids = sorted(set(candidate_rows) - set(baseline_rows))
    removed_ids = sorted(set(baseline_rows) - set(candidate_rows))
    retained_ids = sorted(set(baseline_rows) & set(candidate_rows))
    if not retained_ids:
        raise ValueError("Baseline and inclusive GeoPackages share no segment IDs")
    check_saved_endpoints(candidate, (candidate_rows[key] for key in added_ids))
    compare_fields = [key for key in baseline_rows[retained_ids[0]] if key != "geom"]
    unchanged_attributes = all(
        all(baseline_rows[key][field] == candidate_rows[key][field] for field in compare_fields)
        and baseline_rows[key]["geom"] == candidate_rows[key]["geom"]
        for key in retained_ids
    )
    if not unchanged_attributes:
        raise ValueError("retained segment attributes or geometry changed")

    baseline_names = {
        str(row["name"]).strip().casefold()
        for row in baseline_rows.values()
        if row["name"] is not None and str(row["name"]).strip()
    }
    groups = {}
    unnamed = 0
    for segment_id in added_ids:
        row = candidate_rows[segment_id]
        raw_name = "" if row["name"] is None else str(row["name"]).strip()
        if not raw_name:
            unnamed += 1
            continue
        normalized = raw_name.casefold()
        group = groups.setdefault(normalized, {"spellings": set(), "way_ids": set(), "length_ft": 0.0, "count": 0})
        group["spellings"].add(raw_name)
        group["way_ids"].add(str(row["way_id"]))
        group["length_ft"] += float(row["length_ft"])
        group["count"] += 1
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["roadway_name", "new_segment_count", "new_way_count", "new_length_ft", "already_present_in_baseline"])
        for normalized in sorted(groups, key=str.casefold):
            group = groups[normalized]
            display = sorted(group["spellings"], key=lambda value: (value.casefold(), value))[0]
            writer.writerow([display, group["count"], len(group["way_ids"]), group["length_ft"], str(normalized in baseline_names).lower()])

    baseline_audit_rows = audit_records(baseline_audit)
    candidate_audit_rows = audit_records(candidate_audit)
    removed_reasons = {
        key: candidate_audit_rows.get(key, baseline_audit_rows.get(key, {})).get("reason_codes", [])
        for key in removed_ids
    }
    baseline_hash_after = digest(baseline)
    checkpoints = {
        "new_west_eisenhower_segment": EXPECTED_NEW in candidate_rows and EXPECTED_NEW not in baseline_rows,
        "existing_crossing_retained": EXPECTED_CROSSING in candidate_rows and EXPECTED_CROSSING in baseline_rows,
        "trail_ridge_segment_absent": EXPECTED_ABSENT[0] not in candidate_rows,
        "latigo_lane_segment_absent": EXPECTED_ABSENT[1] not in candidate_rows,
    }
    if not all(checkpoints.values()):
        raise ValueError(f"Larimer comparison checkpoint failed: {checkpoints}")
    report = {
        "status": "pass",
        "policy": {"rule_version": "pedestrian-policy-larimer-inclusive-1", "scenario_id": "larimer-inclusive-road-pilot-v1", "speed_mph": 2.8},
        "source_snapshot": "November 1, 2026 OSM snapshot; extraction 20261123T224134Z-1fb270b1",
        "files": {
            "baseline": {"path": str(baseline), "sha256_before": baseline_hash_before, "sha256_after": baseline_hash_after, "bytes": baseline.stat().st_size, "layer_counts": layer_counts(baseline)},
            "inclusive": {"path": str(candidate), "sha256": digest(candidate), "bytes": candidate.stat().st_size, "layer_counts": layer_counts(candidate)},
            "roadway_names_csv": {"path": str(output_csv), "sha256": digest(output_csv), "bytes": output_csv.stat().st_size},
        },
        "counts": {"added_segments": len(added_ids), "removed_segments": len(removed_ids), "retained_segments": len(retained_ids), "added_length_ft": sum(float(candidate_rows[key]["length_ft"]) for key in added_ids), "removed_length_ft": sum(float(baseline_rows[key]["length_ft"]) for key in removed_ids), "unnamed_added_segments": unnamed, "distinct_added_names": len(groups), "distinct_names_absent_entirely_from_baseline": sum(normalized not in baseline_names for normalized in groups)},
        "checks": {"baseline_hash_unchanged": baseline_hash_before == baseline_hash_after, "retained_attributes_and_geometry_unchanged": unchanged_attributes, "baseline_ids_unique": len(baseline_rows) == layer_counts(baseline)["pedestrian_edges"], "inclusive_ids_unique": len(candidate_rows) == layer_counts(candidate)["pedestrian_edges"], "all_new_edges_have_saved_endpoints": True, "checkpoint_segments": checkpoints},
        "removed_segment_reason_codes": removed_reasons,
        "candidate_audit_paths": {"baseline": str(baseline_audit), "inclusive": str(candidate_audit)},
    }
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--inclusive", type=Path, required=True)
    parser.add_argument("--baseline-audit", type=Path, required=True)
    parser.add_argument("--inclusive-audit", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        compare(args.baseline, args.inclusive, args.baseline_audit, args.inclusive_audit, args.csv, args.report)
    except (ValueError, sqlite3.Error) as error:
        parser.exit(1, f"Larimer comparison failed: {error}\n")
    print(json.dumps({"status": "pass", "csv": str(args.csv), "report": str(args.report)}, indent=2))


if __name__ == "__main__":
    main()

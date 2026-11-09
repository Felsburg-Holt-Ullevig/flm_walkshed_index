"""Canonical-source adapter and auditable outputs for pedestrian classification."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import uuid
from typing import Any, Callable, Iterator

from .code_identity import code_identity
from .pedestrian_config import PedestrianConfigError, PedestrianSettings, load_pedestrian_settings
from .pedestrian_policy import NodeEvaluation, PolicyInputError, WayEvaluation, evaluate_node, evaluate_way


CONTRACT_VERSION = "source-network-1"
CLASSIFICATION_VERSION = "pedestrian-classification-1"
_EXPECTED_FILES = {"nodes.jsonl", "ways.jsonl", "relations.jsonl"}
_ID_DIGITS = frozenset("0123456789")
_MAX_JSONL_RECORD_BYTES = 16 * 1024 * 1024
_REASON_STAGE = {
    "H_UNSUPPORTED": 0, "S_UNSUPPORTED_STRUCTURE": 0, "H_LIFECYCLE": 0,
    "A_FOOT_ALLOW": 1, "A_FOOT_PERMISSIVE": 1, "A_FOOT_DENY": 1, "A_FOOT_UNSUPPORTED": 1,
    "A_ACCESS_ALLOW": 1, "A_ACCESS_PERMISSIVE": 1, "A_ACCESS_DENY": 1,
    "A_ACCESS_UNSUPPORTED": 1, "A_DEFAULT": 1,
    "H_DEFAULT_INCLUDE": 2, "H_LIMITED_ACCESS": 2, "H_FOOT_UNCONFIRMED": 2,
    "A_CONDITIONAL_UNRESOLVED": 3, "A_VARIANT_UNSUPPORTED": 3,
    "D_BOTH": 4, "D_FORWARD": 4, "D_REVERSE": 4, "D_UNSUPPORTED": 4,
    "B_ACCESS_BLOCK": 5, "B_PHYSICAL_BLOCK": 5, "B_PERMISSION_PASS": 5,
    "B_PASS": 5, "B_KERB_PASS": 5, "B_UNRESOLVED": 5, "B_LOCKED": 5, "B_LOCK_UNRESOLVED": 5,
    "G_ZERO_LENGTH": 6,
}


class ClassificationError(RuntimeError):
    """Raised when source evidence or a classification output fails validation."""


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n")


def _numeric_key(value: str) -> tuple[int, str]:
    return len(value), value


def _id(value: Any, label: str, line_number: int) -> str:
    if not isinstance(value, str) or not value or value[0] == "0" or any(char not in _ID_DIGITS for char in value):
        raise ClassificationError(f"{label} at line {line_number} must be a positive decimal string")
    return value


def _tags(value: Any, label: str, line_number: int) -> dict[str, str]:
    if not isinstance(value, dict) or any(not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()):
        raise ClassificationError(f"{label} tags at line {line_number} must map strings to strings")
    return value


def _parse_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON number {value} is not allowed")


def _jsonl(path: Path, label: str) -> Iterator[tuple[int, dict[str, Any]]]:
    with path.open("rb") as stream:
        for line_number, raw in enumerate(stream, 1):
            if len(raw) > _MAX_JSONL_RECORD_BYTES:
                raise ClassificationError(f"{label} record at line {line_number} exceeds 16 MiB")
            try:
                record = json.loads(raw.decode("utf-8"), parse_constant=_parse_constant)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                raise ClassificationError(f"Malformed {label} JSON at line {line_number}: {error}") from error
            if not isinstance(record, dict):
                raise ClassificationError(f"{label} record at line {line_number} must be an object")
            if raw != _json_bytes(record) + b"\n":
                raise ClassificationError(f"{label} record at line {line_number} is not canonical JSONL")
            yield line_number, record


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_constant=_parse_constant)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ClassificationError(f"Could not read {label}: {error}") from error
    if not isinstance(value, dict):
        raise ClassificationError(f"{label} must contain a JSON object")
    return value


def _validate_inputs(extraction_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    if not extraction_dir.is_dir():
        raise ClassificationError(f"Extraction directory does not exist: {extraction_dir}")
    metadata = _load_object(extraction_dir / "extraction.json", "extraction.json")
    run_report = _load_object(extraction_dir / "run-report.json", "extraction run-report.json")
    if metadata.get("status") != "pass" or metadata.get("contract_version") != CONTRACT_VERSION:
        raise ClassificationError("Classification requires a passing source-network-1 extraction")
    if run_report.get("status") != "pass" or run_report.get("report_version") != "prototype-run-1":
        raise ClassificationError("Extraction run report is not a completed passing run")
    checks = run_report.get("checks")
    if not isinstance(checks, dict) or not checks or not all(value is True for value in checks.values()):
        raise ClassificationError("Extraction run report contains failed or missing completion checks")
    required_checks = {
        "inventory_linked", "source_hash_before_and_after", "entity_counts_reconciled",
        "required_way_references_resolve", "canonical_outputs_reopened", "worker_exit_zero",
        "child_cleanup_complete",
    }
    if not required_checks <= set(checks):
        raise ClassificationError("Extraction run report is missing required completion checks")
    files = metadata.get("files")
    if not isinstance(files, dict) or set(files) != _EXPECTED_FILES:
        raise ClassificationError("Extraction metadata must list the three canonical JSONL files")
    actual_hashes: dict[str, str] = {}
    for name in sorted(_EXPECTED_FILES):
        path = extraction_dir / name
        item = files[name]
        if not isinstance(item, dict) or item.get("path") != name or not path.is_file():
            raise ClassificationError(f"Extraction file or metadata is missing: {name}")
        actual = _hash_file(path)
        actual_hashes[name] = actual
        if actual != item.get("sha256") or actual != item.get("semantic_sha256"):
            raise ClassificationError(f"Extraction content hash does not match metadata: {name}")
        if path.stat().st_size != item.get("bytes"):
            raise ClassificationError(f"Extraction byte count does not match metadata: {name}")
        if run_report.get("output_hashes", {}).get(name) != actual:
            raise ClassificationError(f"Extraction run report does not verify {name}")
        if not isinstance(item.get("count"), int) or isinstance(item.get("count"), bool) or item["count"] < 0:
            raise ClassificationError(f"Extraction count is invalid for {name}")
    if run_report.get("output_hashes", {}).get("extraction.json") != _hash_file(extraction_dir / "extraction.json"):
        raise ClassificationError("Extraction run report does not verify extraction.json")
    actual_hashes["extraction.json"] = _hash_file(extraction_dir / "extraction.json")
    actual_hashes["run-report.json"] = _hash_file(extraction_dir / "run-report.json")
    counts = metadata.get("counts")
    if not isinstance(counts, dict):
        raise ClassificationError("Extraction metadata has no counts object")
    source = metadata.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("sha256"), str) or len(source["sha256"]) != 64:
        raise ClassificationError("Extraction metadata has no valid source SHA-256 provenance")
    if source.get("expected_sha256") is not None and source.get("expected_sha256") != source["sha256"]:
        raise ClassificationError("Extracted source hash differs from its accepted expected hash")
    for filename, field in (("nodes.jsonl", "emitted_nodes"), ("ways.jsonl", "selected_ways"), ("relations.jsonl", "emitted_relations")):
        if counts.get(field) != files[filename]["count"]:
            raise ClassificationError(f"Extraction metadata count does not reconcile for {filename}")
    if counts.get("unresolved_way_node_references") != 0:
        raise ClassificationError("Extraction reports unresolved required way-node references")
    return metadata, run_report, actual_hashes


def _add_conditional_tags(
    entity_type: str,
    osm_id: str,
    tags: dict[str, str],
    output,
    counts: Counter[tuple[str, str, str]],
) -> None:
    for key in sorted(key for key in tags if ":conditional" in key):
        value = tags[key]
        output.write(_json_bytes({"entity_type": entity_type, "osm_id": osm_id, "key": key, "value": value}) + b"\n")
        counts[(entity_type, key, value)] += 1


def _reason_order(codes: list[str]) -> list[str]:
    unique = list(dict.fromkeys(codes))
    return sorted(unique, key=lambda code: (_REASON_STAGE.get(code, 99), code))


def _candidate_record(
    way_id: str,
    sequence: int,
    refs: list[str],
    way: WayEvaluation,
    nodes: dict[str, NodeEvaluation],
) -> dict[str, Any]:
    from_id, to_id = refs[sequence], refs[sequence + 1]
    endpoint_ids = sorted({from_id, to_id}, key=_numeric_key)
    endpoint_results = [nodes[node_id] for node_id in endpoint_ids]
    same_endpoint = from_id == to_id
    known_exclusion = way.eligibility == "exclude" or any(item.disposition == "block" for item in endpoint_results) or same_endpoint
    any_unknown = way.eligibility == "unknown" or any(item.disposition == "unknown" for item in endpoint_results)
    if known_exclusion:
        eligibility, direction = "exclude", "none"
    elif any_unknown:
        eligibility, direction = "unknown", "unknown"
    else:
        eligibility, direction = "include", way.direction

    codes = list(way.reason_codes)
    for result in endpoint_results:
        codes.extend(result.reason_codes)
    if same_endpoint:
        codes.append("G_ZERO_LENGTH")
    warnings = list(way.warnings)
    for item in endpoint_results:
        warnings.extend(item.warnings)
    return {
        "candidate_id": f"way/{way_id}/segment/{sequence}",
        "rule_version": way.rule_version,
        "scenario_id": way.scenario_id,
        "way_id": way_id,
        "sequence": sequence,
        "from_node_id": from_id,
        "to_node_id": to_id,
        "way_eligibility": way.eligibility,
        "from_node_disposition": nodes[from_id].disposition,
        "to_node_disposition": nodes[to_id].disposition,
        "eligibility": eligibility,
        "direction": direction,
        "proposed_direction": way.proposed_direction,
        "reason_codes": _reason_order(codes),
        "warnings": list(dict.fromkeys(warnings)),
        "geometry_check": "not_run",
        "same_endpoint_id": same_endpoint,
        "routing_ready": False,
    }


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def _table_rows(counter: Counter, keys: tuple[str, ...], count_name: str, *, exclude_empty: bool = False) -> list[dict[str, Any]]:
    rows = []
    for key, value in sorted(counter.items(), key=lambda item: tuple(str(part) for part in (item[0] if isinstance(item[0], tuple) else (item[0],)))):
        parts = key if isinstance(key, tuple) else (key,)
        if exclude_empty and not value:
            continue
        rows.append({**dict(zip(keys, parts, strict=True)), count_name: value})
    return rows


def _write_layer(path: Path, writer, row_count: int) -> dict[str, Any]:
    writer.flush()
    os.fsync(writer.fileno())
    writer.close()
    return {"path": path.name, "count": row_count, "bytes": path.stat().st_size, "sha256": _hash_file(path)}


def run_classification(
    extraction_path: str | Path,
    policy_config_path: str | Path,
    output_root: str | Path | None = None,
    progress: Callable[[str], None] | None = None,
    staging_root: str | Path | None = None,
) -> tuple[int, dict[str, Any]]:
    """Stream a verified extraction into geometry-free classification/audit layers."""
    package_root = Path(__file__).resolve().parents[3]
    extraction_dir = Path(extraction_path).resolve()
    settings: PedestrianSettings = load_pedestrian_settings(policy_config_path)
    metadata, extraction_report, input_hashes = _validate_inputs(extraction_dir)
    raw_output_root = Path(output_root) if output_root is not None else package_root / "data" / "generated" / "prototype" / "pedestrian-classification"
    destination_root = raw_output_root.resolve()
    try:
        destination_root.relative_to(package_root)
    except ValueError as error:
        raise ClassificationError("Classification output must remain inside the repository") from error
    raw_root = (package_root / "data" / "raw").resolve()
    if destination_root == raw_root or raw_root in destination_root.parents:
        raise ClassificationError("Classification output cannot be placed inside data/raw")

    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    stage_root = Path(staging_root).resolve() if staging_root is not None else package_root / "data" / "staging" / "prototype"
    try:
        stage_root.relative_to(package_root)
    except ValueError as error:
        raise ClassificationError("Classification staging must remain inside the repository") from error
    if stage_root == raw_root or raw_root in stage_root.parents:
        raise ClassificationError("Classification staging cannot be placed inside data/raw")
    stage_root.mkdir(parents=True, exist_ok=True)
    stage_dir = stage_root / f"pedestrian-classification-{run_id}"
    final_dir = destination_root / run_id
    if stage_dir.exists() or final_dir.exists():
        raise FileExistsError(f"Refusing to reuse classification run ID {run_id}")
    stage_dir.mkdir()
    started = time.monotonic()
    counts = metadata["counts"]
    way_status: Counter[str] = Counter()
    node_status: Counter[str] = Counter()
    candidate_status: Counter[str] = Counter()
    highway_counts: Counter[tuple[str, str]] = Counter()
    reason_counts: Counter[tuple[str, str]] = Counter()
    sidewalk_counts: Counter[tuple[str, str]] = Counter()
    conditional_counts: Counter[tuple[str, str, str]] = Counter()
    candidate_total = 0
    referenced_nodes = 0
    relation_total = 0
    output_files: dict[str, dict[str, Any]] = {}
    output_handles = []
    promoted = False
    policy_document = package_root / settings.rule_authority
    if not policy_document.is_file():
        raise ClassificationError(f"Policy authority file does not exist: {settings.rule_authority}")
    authority_hash = _hash_file(policy_document)
    initial_identity = code_identity()["sha256"]
    initial_config_hash = settings.config_sha256
    connection: sqlite3.Connection | None = None
    try:
        node_index_path = stage_dir / "node-index.sqlite"
        connection = sqlite3.connect(node_index_path)
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA temp_store=FILE")
        connection.execute("CREATE TABLE source_nodes(osm_id TEXT PRIMARY KEY, tags_json TEXT NOT NULL)")
        connection.execute("CREATE TABLE evaluated_nodes(osm_id TEXT PRIMARY KEY, result_json TEXT NOT NULL)")
        node_inserted = 0
        last_node_key: tuple[int, str] | None = None
        for line_number, row in _jsonl(extraction_dir / "nodes.jsonl", "node"):
            if set(row) != {"osm_id", "lon", "lat", "tags"}:
                raise ClassificationError(f"Unexpected fields for node at line {line_number}")
            node_id = _id(row["osm_id"], "node ID", line_number)
            node_key = _numeric_key(node_id)
            if last_node_key is not None and node_key <= last_node_key:
                raise ClassificationError(f"Node records are duplicate or not numerically sorted at line {line_number}")
            last_node_key = node_key
            lon, lat = row["lon"], row["lat"]
            if isinstance(lon, bool) or isinstance(lat, bool) or not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)) or not math.isfinite(lon) or not math.isfinite(lat) or not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
                raise ClassificationError(f"Node {node_id} has invalid WGS84 coordinates")
            tags = _tags(row["tags"], f"node {node_id}", line_number)
            try:
                connection.execute("INSERT INTO source_nodes VALUES (?, ?)", (node_id, _json_bytes(tags).decode("utf-8")))
            except sqlite3.IntegrityError as error:
                raise ClassificationError(f"Duplicate node ID {node_id}") from error
            node_inserted += 1
            if node_inserted % 20_000 == 0:
                connection.commit()
                if progress:
                    progress(f"Indexed {node_inserted:,} source nodes")
        connection.commit()
        if node_inserted != counts["emitted_nodes"]:
            raise ClassificationError("Read node count does not match extraction metadata")

        way_output_path = stage_dir / "ways-classified.jsonl"
        node_output_path = stage_dir / "nodes-classified.jsonl"
        candidate_output_path = stage_dir / "candidates-classified.jsonl"
        conditional_output_path = stage_dir / "conditional-tags.jsonl"
        way_output = way_output_path.open("wb")
        node_output = node_output_path.open("wb")
        candidate_output = candidate_output_path.open("wb")
        conditional_output = conditional_output_path.open("wb")
        output_handles = [way_output, node_output, candidate_output, conditional_output]
        way_count = 0
        last_way_key: tuple[int, str] | None = None
        for line_number, row in _jsonl(extraction_dir / "ways.jsonl", "way"):
            if set(row) != {"osm_id", "node_refs", "tags"}:
                raise ClassificationError(f"Unexpected fields for way at line {line_number}")
            way_id = _id(row["osm_id"], "way ID", line_number)
            way_key = _numeric_key(way_id)
            if last_way_key is not None and way_key <= last_way_key:
                raise ClassificationError(f"Way records are duplicate or not numerically sorted at line {line_number}")
            last_way_key = way_key
            refs = row["node_refs"]
            if not isinstance(refs, list) or len(refs) < 2:
                raise ClassificationError(f"Way {way_id} must have at least two ordered node references")
            for ref in refs:
                _id(ref, f"way {way_id} node reference", line_number)
            tags = _tags(row["tags"], f"way {way_id}", line_number)
            if "highway" not in tags:
                raise ClassificationError(f"Selected source way {way_id} is missing its highway tag")
            evaluation = evaluate_way(way_id, refs, tags)
            evaluation_dict = evaluation.to_dict()
            way_output.write(_json_bytes({
                "source": {"entity_type": "way", "osm_id": way_id, "node_refs": refs, "tags_file": "ways.jsonl"},
                "evaluation": evaluation_dict,
            }) + b"\n")
            way_status[evaluation.eligibility] += 1
            highway = ("present", tags["highway"]) if tags["highway"] else ("present_empty", "")
            highway_counts[highway] += 1
            if "highway" not in tags:
                highway_counts[("missing", "")] += 1
            for code in evaluation.reason_codes:
                reason_counts[("ways", code)] += 1
            for field, value in (
                ("sidewalk_general", evaluation.sidewalk_general), ("sidewalk_left", evaluation.sidewalk_left),
                ("sidewalk_right", evaluation.sidewalk_right), ("sidewalk_both", evaluation.sidewalk_both),
                ("geometry_role", evaluation.geometry_role),
            ):
                sidewalk_counts[(field, value)] += 1
            _add_conditional_tags("way", way_id, tags, conditional_output, conditional_counts)

            endpoint_evaluations: dict[str, NodeEvaluation] = {}
            for node_id in sorted(set(refs), key=_numeric_key):
                cached = connection.execute("SELECT result_json FROM evaluated_nodes WHERE osm_id = ?", (node_id,)).fetchone()
                if cached is not None:
                    endpoint_evaluations[node_id] = _node_from_json(cached[0])
                    continue
                node_row = connection.execute("SELECT tags_json FROM source_nodes WHERE osm_id = ?", (node_id,)).fetchone()
                if node_row is None:
                    raise ClassificationError(f"Way {way_id} references missing required node {node_id}")
                node_tags = json.loads(node_row[0])
                node_eval = evaluate_node(node_id, node_tags)
                node_eval_json = _json_bytes(node_eval.to_dict()).decode("utf-8")
                connection.execute("INSERT INTO evaluated_nodes VALUES (?, ?)", (node_id, node_eval_json))
                endpoint_evaluations[node_id] = node_eval
                node_output.write(_json_bytes({
                    "source": {"entity_type": "node", "osm_id": node_id, "tags_file": "nodes.jsonl"},
                    "evaluation": node_eval.to_dict(),
                }) + b"\n")
                referenced_nodes += 1
                node_status[node_eval.disposition] += 1
                for code in node_eval.reason_codes:
                    reason_counts[("nodes", code)] += 1
                _add_conditional_tags("node", node_id, node_tags, conditional_output, conditional_counts)
            for sequence in range(len(refs) - 1):
                candidate = _candidate_record(way_id, sequence, refs, evaluation, endpoint_evaluations)
                candidate_output.write(_json_bytes(candidate) + b"\n")
                candidate_status[candidate["eligibility"]] += 1
                for code in candidate["reason_codes"]:
                    reason_counts[("candidates", code)] += 1
                candidate_total += 1
            way_count += 1
            if way_count % 5_000 == 0:
                connection.commit()
            if way_count % 10_000 == 0 and progress:
                progress(f"Classified {way_count:,} ways and {candidate_total:,} source segments")
        connection.commit()
        if way_count != counts["selected_ways"]:
            raise ClassificationError("Read way count does not match extraction metadata")
        if referenced_nodes != counts["unique_required_way_nodes"]:
            raise ClassificationError("Unique evaluated-node count does not match the extraction reference count")

        _write_layer(way_output_path, way_output, way_count)
        _write_layer(node_output_path, node_output, referenced_nodes)
        _write_layer(candidate_output_path, candidate_output, candidate_total)
        relation_output_rows = 0
        relation_last_key: tuple[int, str] | None = None
        for line_number, row in _jsonl(extraction_dir / "relations.jsonl", "relation"):
            if set(row) != {"osm_id", "members", "tags"}:
                raise ClassificationError(f"Unexpected fields for relation at line {line_number}")
            relation_id = _id(row["osm_id"], "relation ID", line_number)
            relation_key = _numeric_key(relation_id)
            if relation_last_key is not None and relation_key <= relation_last_key:
                raise ClassificationError(f"Relation records are duplicate or not numerically sorted at line {line_number}")
            relation_last_key = relation_key
            if not isinstance(row["members"], list):
                raise ClassificationError(f"Relation {relation_id} members must be an array")
            for member in row["members"]:
                if not isinstance(member, dict) or set(member) != {"type", "ref", "role", "resolved"} or member["type"] not in {"node", "way", "relation"} or not isinstance(member["role"], str) or not isinstance(member["resolved"], bool):
                    raise ClassificationError(f"Relation {relation_id} has a malformed member")
                _id(member["ref"], f"relation {relation_id} member reference", line_number)
            relation_tags = _tags(row["tags"], f"relation {relation_id}", line_number)
            _add_conditional_tags("relation", relation_id, relation_tags, conditional_output, conditional_counts)
            relation_total += 1
            relation_output_rows += 1
        if relation_total != counts["emitted_relations"]:
            raise ClassificationError("Read relation count does not match extraction metadata")
        connection.close()
        connection = None
        node_index_path.unlink(missing_ok=True)
        _write_layer(conditional_output_path, conditional_output, sum(conditional_counts.values()))
        output_handles = []

        # Keep compact machine-readable summaries and spreadsheet-friendly audit tables.
        highway_rows = [
            {"highway_presence": presence, "highway": value, "way_count": amount}
            for (presence, value), amount in sorted(highway_counts.items())
        ]
        reason_rows = [
            {"layer": layer, "reason_code": code, "record_count": amount}
            for (layer, code), amount in sorted(reason_counts.items())
        ]
        sidewalk_rows = [
            {"field": field, "evidence": value, "way_count": amount}
            for (field, value), amount in sorted(sidewalk_counts.items())
        ]
        conditional_rows = [
            {"entity_type": entity, "tag_key": key, "raw_value": value, "entity_count": amount}
            for (entity, key, value), amount in sorted(conditional_counts.items())
        ]
        tables = {
            "ways_by_eligibility": dict(sorted(way_status.items())),
            "referenced_nodes_by_disposition": dict(sorted(node_status.items())),
            "source_segments_by_policy_eligibility": dict(sorted(candidate_status.items())),
            "counts_by_highway": highway_rows,
            "counts_by_reason": reason_rows,
            "counts_by_sidewalk_evidence": sidewalk_rows,
            "conditional_tag_counts": conditional_rows,
            "count_definitions": {
                "status_counts": "Each way, unique referenced node, or ordered-pair candidate is counted once.",
                "reason_counts": "Nonexclusive; each distinct reason code is counted once per record in its layer.",
                "sidewalk_counts": "Separate field totals; they are not summed into a sidewalk-coverage percentage.",
                "conditional_tag_counts": "Counts raw conditional-tag occurrences by entity type, key, and unchanged value.",
                "candidate_counts": "Policy eligibility only; geometry validation is not_run.",
            },
        }
        _write_json(stage_dir / "audit-tables.json", tables)
        _write_csv(stage_dir / "counts-by-highway.csv", ["highway_presence", "highway", "way_count"], highway_rows)
        _write_csv(stage_dir / "counts-by-reason.csv", ["layer", "reason_code", "record_count"], reason_rows)
        _write_csv(stage_dir / "counts-by-sidewalk-evidence.csv", ["field", "evidence", "way_count"], sidewalk_rows)
        _write_csv(stage_dir / "conditional-tag-counts.csv", ["entity_type", "tag_key", "raw_value", "entity_count"], conditional_rows)

        if sum(way_status.values()) != way_count or sum(node_status.values()) != referenced_nodes or sum(candidate_status.values()) != candidate_total:
            raise ClassificationError("Classification category totals do not reconcile to processed inputs")
        if set(way_status) - {"include", "exclude", "unknown"} or set(node_status) - {"pass", "block", "unknown"} or set(candidate_status) - {"include", "exclude", "unknown"}:
            raise ClassificationError("Evaluator produced an unsupported classification")
        if candidate_total != counts["complete_way_node_reference_total"] - way_count:
            raise ClassificationError("Candidate count does not reconcile to ordered source references")

        for name in sorted(input_hashes):
            if _hash_file(extraction_dir / name) != input_hashes[name]:
                raise ClassificationError(f"Source input or provenance changed while classification was running: {name}")
        if _hash_file(settings.config_path) != initial_config_hash or _hash_file(policy_document) != authority_hash:
            raise ClassificationError("Pedestrian config or policy authority changed while classification was running")
        if code_identity()["sha256"] != initial_identity:
            raise ClassificationError("Pipeline implementation changed while classification was running")
        output_manifest = {}
        for path in sorted(stage_dir.iterdir(), key=lambda item: item.name):
            if path.is_file():
                output_manifest[path.name] = {"bytes": path.stat().st_size, "sha256": _hash_file(path)}
        unknown_candidates = candidate_status["unknown"]
        unknown_present = unknown_candidates > 0 or way_status["unknown"] > 0 or node_status["unknown"] > 0
        report = {
            "report_version": CLASSIFICATION_VERSION,
            "status": "classification_complete_with_unknowns" if unknown_present else "classification_complete",
            "run_id": run_id,
            "finished_at_utc": datetime.now(UTC).isoformat(),
            "duration_seconds": round(time.monotonic() - started, 3),
            "inputs": {
                "extraction_directory": extraction_dir.relative_to(package_root).as_posix() if extraction_dir.is_relative_to(package_root) else str(extraction_dir),
                "extraction_run_id": metadata.get("run_id"),
                "extraction_metadata_sha256": _hash_file(extraction_dir / "extraction.json"),
                "extraction_report_sha256": _hash_file(extraction_dir / "run-report.json"),
                "contract_version": metadata["contract_version"],
                "selection_id": metadata.get("selection_id"),
                "source": metadata.get("source"),
                "file_sha256": input_hashes,
                "file_counts": {name: metadata["files"][name]["count"] for name in sorted(_EXPECTED_FILES)},
            },
            "policy": {
                "rule_version": settings.rule_version,
                "scenario_id": settings.scenario_id,
                "status": settings.status,
                "travel_profile": "general_pedestrian",
                "wheelchair_accessibility": "not_evaluated",
                "config_path": settings.config_path.relative_to(package_root).as_posix() if settings.config_path.is_relative_to(package_root) else str(settings.config_path),
                "config_sha256": settings.config_sha256,
                "authority_path": settings.rule_authority,
                "authority_sha256": authority_hash,
                "comparison_scenario_id": settings.comparison_scenario_id,
                "reference_revision": settings.reference_revision,
                "length_unit": settings.length_unit,
                "speed_mph": settings.speed_mph,
                "geometry_checks": "not_run",
                "relation_semantics": "not_run",
            },
            "implementation_identity": code_identity(),
            "counts": {
                "input_ways": way_count,
                "ways_by_eligibility": dict(sorted(way_status.items())),
                "unique_referenced_nodes": referenced_nodes,
                "referenced_nodes_by_disposition": dict(sorted(node_status.items())),
                "ordered_pair_candidates": candidate_total,
                "candidate_geometry_checks": "not_run",
                "candidates_by_policy_eligibility": dict(sorted(candidate_status.items())),
                "emitted_relation_records": relation_total,
                "conditional_tag_records": sum(conditional_counts.values()),
            },
            "coverage": {
                "source_selection_id": metadata.get("selection_id"),
                "source_coverage": metadata.get("coverage"),
                "all_selected_ways_classified": way_count == counts["selected_ways"],
                "all_unique_referenced_nodes_classified_once": referenced_nodes == counts["unique_required_way_nodes"],
                "all_ordered_pair_candidates_classified": candidate_total == counts["complete_way_node_reference_total"] - way_count,
                "unknown_policy_blocks_analytical_promotion": unknown_present,
                "analytical_promotion": "blocked_by_unknown_policy" if unknown_present else "pending_geometry_and_graph_validation",
                "relation_interpretation": "not_run; relation records and conditional tags retained as source evidence",
            },
            "audit_tables": {
                "counts_by_highway": "counts-by-highway.csv",
                "counts_by_reason": "counts-by-reason.csv",
                "counts_by_sidewalk_evidence": "counts-by-sidewalk-evidence.csv",
                "conditional_tag_counts": "conditional-tag-counts.csv",
                "all_tables": "audit-tables.json",
                "count_definitions": tables["count_definitions"],
            },
            "output_files": output_manifest,
            "checks": {
                "extraction_hashes_and_completion_verified": True,
                "canonical_records_validated": True,
                "way_classification_totals_reconcile": True,
                "referenced_node_classification_totals_reconcile": True,
                "ordered_pair_candidate_totals_reconcile": True,
                "source_references_resolved": True,
                "unsupported_cases_retained": True,
                "conditional_tags_reported_without_parsing": True,
                "geometry_checks_explicitly_not_run": True,
                "no_costs_or_graph_edges_emitted": True,
            },
            "limitations": [
                "Eligibility and direction are experimental classifications under the accepted policy, not authoritative CDOT methodology.",
                "Classification layers contain source IDs and ordered references but no geometry or duplicate raw tag maps; use the recorded input hashes to join unchanged tags and spatial features from the source extraction/GeoPackage.",
                "Zero geodesic lengths, geometry validity, and length/cost conversion checks are not run until Task 3.3.",
                "Relation restrictions and turn behavior are not interpreted.",
                "Any unknown way, referenced node, or source-segment candidate blocks analytical promotion.",
                "Historical extraction source and code identities are reported as recorded; this classification run does not reprocess or rehash the raw PBF.",
            ],
        }
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        if final_dir.exists():
            raise FileExistsError(f"Refusing to replace classification output {final_dir}")
        from .cli import _promote_directory

        _promote_directory(stage_dir, final_dir)
        promoted = True
        for name, expected in output_manifest.items():
            path = final_dir / name
            if not path.is_file() or path.stat().st_size != expected["bytes"] or _hash_file(path) != expected["sha256"]:
                raise ClassificationError(f"Promoted output failed its recorded hash check: {name}")
        report_path = final_dir / "run-report.json"
        temp_report = final_dir / "run-report.json.tmp"
        report["run_report"] = report_path.relative_to(package_root).as_posix() if report_path.is_relative_to(package_root) else str(report_path)
        _write_json(temp_report, report)
        os.replace(temp_report, report_path)
        return 0, {
            "status": report["status"], "run_id": run_id, "run_report": report["run_report"],
            "output_directory": final_dir.relative_to(package_root).as_posix(),
            "counts": report["counts"], "coverage": report["coverage"], "output_files": report["output_files"],
        }
    except Exception as error:
        for handle in output_handles:
            try:
                handle.close()
            except OSError:
                pass
        if connection is not None:
            connection.close()
        if promoted and final_dir.exists() and not stage_dir.exists():
            try:
                os.replace(final_dir, stage_dir)
                promoted = False
            except OSError:
                pass
        failure_path = stage_dir / "run-report.json"
        try:
            _write_json(failure_path, {
                "report_version": CLASSIFICATION_VERSION, "status": "fail", "run_id": run_id,
                "finished_at_utc": datetime.now(UTC).isoformat(), "duration_seconds": round(time.monotonic() - started, 3),
                "error": f"{type(error).__name__}: {error}",
                "processed": {"ways": way_status.total(), "referenced_nodes": referenced_nodes, "candidates": candidate_total},
            })
        except OSError:
            pass
        if isinstance(error, (ClassificationError, PedestrianConfigError, PolicyInputError, OSError, ValueError, TypeError, KeyError, sqlite3.Error)):
            return 1, {"status": "fail", "run_id": run_id, "run_report": str(failure_path), "errors": [str(error)]}
        raise


def _node_from_json(value: str) -> NodeEvaluation:
    raw = json.loads(value)
    return NodeEvaluation(
        rule_version=raw["rule_version"], scenario_id=raw["scenario_id"], entity_type=raw["entity_type"],
        osm_id=raw["osm_id"], disposition=raw["disposition"], reason_codes=tuple(raw["reason_codes"]),
        warnings=tuple(raw["warnings"]), unsupported_tag_keys=tuple(raw["unsupported_tag_keys"]),
    )

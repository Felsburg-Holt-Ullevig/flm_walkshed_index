"""Contract-preserving regional extraction from an OSM PBF."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from typing import Any

import osmium

from .code_identity import code_identity
from .config import ConfigError, PipelineConfig
from .runtime import runtime_versions


SELECTION_ID = "highway-node-in-bbox-complete-way-1"
CONTRACT_VERSION = "source-network-1"
_ID_PATTERN = set("0123456789")
_SUCCESS_STATUSES = {"pass", "pass_with_warnings"}
_BATCH_SIZE = 10_000


class ExtractionFailure(RuntimeError):
    """A validation or processing failure with structured diagnostics."""

    def __init__(self, message: str, diagnostics: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics or []


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _id(value: Any, entity: str, phase: str) -> str:
    text = str(value)
    if not isinstance(value, str) or not text or text[0] == "0" or any(character not in _ID_PATTERN for character in text):
        raise ExtractionFailure(
            f"Invalid {entity} OSM ID during {phase}: {value!r}; ID must be a positive decimal string",
            [{"entity_type": entity, "osm_id": text, "phase": phase, "reason": "ID is not a positive decimal string"}],
        )
    return text


def _reader_id(value: Any, entity: str, phase: str) -> str:
    """Convert integer IDs at the PBF reader boundary; canonical JSON requires text."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExtractionFailure(f"Invalid reader {entity} ID during {phase}: {value!r}")
    return _id(str(value), entity, phase)


def _tags(source_tags: Any, entity: str, osm_id: str, phase: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for tag in source_tags:
        key, value = str(tag.k), str(tag.v)
        if key in result:
            raise ExtractionFailure(
                f"Duplicate tag key on {entity} {osm_id}: {key!r}",
                [{"entity_type": entity, "osm_id": osm_id, "phase": phase, "reason": "duplicate tag key", "tag_key": key}],
            )
        result[key] = value
    return result


def _coordinates(node: Any, osm_id: str, phase: str) -> tuple[float, float]:
    try:
        if not node.location.valid():
            raise ValueError("location is invalid")
        lon, lat = float(node.location.lon), float(node.location.lat)
        if not math.isfinite(lon) or not math.isfinite(lat) or not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
            raise ValueError(f"longitude/latitude outside valid ranges: {lon}, {lat}")
    except (AttributeError, OverflowError, TypeError, ValueError) as error:
        raise ExtractionFailure(
            f"Invalid coordinates for node {osm_id} during {phase}: {error}",
            [{"entity_type": "node", "osm_id": osm_id, "phase": phase, "reason": str(error)}],
        ) from error
    return lon, lat


def _numeric_sort_key(osm_id: str) -> tuple[int, str]:
    return len(osm_id), osm_id


def _repo_file(path: str | Path, repo_root: Path, label: str) -> Path:
    candidate = Path(path).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError as error:
        raise ConfigError(f"{label} must be inside the repository") from error
    if not candidate.is_file():
        raise ConfigError(f"{label} does not exist: {candidate}")
    return candidate


def load_accepted_inventory(
    config: PipelineConfig,
    inventory_path: str | Path,
    inventory_report_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], str, Path, Path]:
    """Validate the unedited, successful inventory linked to this config and code."""
    source = config.sources["osm"]
    if source.expected_sha256 is None:
        raise ConfigError("Regional extraction requires sources.osm.expected_sha256 to be pinned")
    if not source.path.is_file():
        raise ConfigError(f"OSM source is missing: {source.relative_path}")
    source_hash = sha256_file(source.path)
    if source_hash.casefold() != source.expected_sha256.casefold():
        raise ConfigError("OSM source SHA-256 does not match sources.osm.expected_sha256")

    inventory_file = _repo_file(inventory_path, config.repo_root, "source inventory")
    report_file = _repo_file(inventory_report_path, config.repo_root, "inventory run report")
    inventory_hash = sha256_file(inventory_file)
    try:
        inventory = json.loads(inventory_file.read_text(encoding="utf-8"))
        inventory_report = json.loads(report_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ConfigError(f"Could not read accepted source inventory and report: {error}") from error
    if not isinstance(inventory, dict) or inventory.get("inventory_version") != "source-inventory-1":
        raise ConfigError("Source inventory must use inventory_version source-inventory-1")
    if not isinstance(inventory_report, dict) or inventory_report.get("report_version") != "prototype-run-1":
        raise ConfigError("Inventory run report must use report_version prototype-run-1")
    if inventory.get("inventory_status") not in _SUCCESS_STATUSES or inventory_report.get("status") not in _SUCCESS_STATUSES:
        raise ConfigError("Source inventory and run report must have pass or pass_with_warnings status")
    if inventory_report.get("inventory_status") != inventory.get("inventory_status"):
        raise ConfigError("Inventory run report status does not match the source inventory")
    if inventory_report.get("source_inventory_sha256") != inventory_hash:
        raise ConfigError("Inventory run report does not match the source inventory file hash")
    if inventory.get("region_id") != config.region_id:
        raise ConfigError("Source inventory region_id does not match the extraction config")
    config_relative = config.config_path.relative_to(config.repo_root).as_posix()
    config_hash = sha256_file(config.config_path)
    inventory_configuration = inventory.get("configuration")
    report_configuration = inventory_report.get("configuration")
    if inventory_configuration != config_relative or not isinstance(report_configuration, dict):
        raise ConfigError("Source inventory was not produced from the configured TOML file")
    if report_configuration.get("path") != config_relative or report_configuration.get("sha256") != config_hash:
        raise ConfigError("Inventory run report does not match the current configuration file")

    identity = code_identity()
    if inventory.get("code_identity") != identity or inventory_report.get("code_identity") != identity:
        raise ConfigError("Source inventory code identity is stale or does not match the current pipeline files")

    sources = inventory.get("sources")
    osm_record = sources.get("osm") if isinstance(sources, dict) else None
    if not isinstance(osm_record, dict):
        raise ConfigError("Source inventory has no OSM record")
    observed_source_hash = osm_record.get("sha256")
    if osm_record.get("path") != source.relative_path or not isinstance(observed_source_hash, str) or observed_source_hash.casefold() != source_hash:
        raise ConfigError("Source inventory OSM path or SHA-256 does not match the configured source")
    if osm_record.get("expected_sha256") != source.expected_sha256 or osm_record.get("expected_sha256_matches") is not True:
        raise ConfigError("Source inventory does not show an accepted matching OSM SHA-256")
    if osm_record.get("validation_status") not in _SUCCESS_STATUSES or osm_record.get("file_stable_during_inventory") is not True:
        raise ConfigError("Source inventory OSM validation or file-stability check did not pass")
    if not isinstance(osm_record.get("scan"), dict) or osm_record["scan"].get("complete") is not True:
        raise ConfigError("Source inventory OSM entity scan was not complete")
    counts = osm_record.get("entity_counts")
    if not isinstance(counts, dict) or any(isinstance(counts.get(key), bool) or not isinstance(counts.get(key), int) for key in ("node", "way", "relation")):
        raise ConfigError("Source inventory is missing full OSM entity counts")
    return inventory, inventory_report, inventory_hash, inventory_file, report_file


def _configure_database(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA cache_size=-65536")
    connection.execute("PRAGMA temp_store=FILE")
    connection.executescript(
        """
        CREATE TABLE seen_node_ids (osm_id TEXT PRIMARY KEY) WITHOUT ROWID;
        CREATE TABLE inside_nodes (
            osm_id TEXT PRIMARY KEY, lon REAL NOT NULL, lat REAL NOT NULL, tags_json TEXT NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE seen_way_ids (osm_id TEXT PRIMARY KEY) WITHOUT ROWID;
        CREATE TABLE selected_ways (
            osm_id TEXT PRIMARY KEY, node_refs_json TEXT NOT NULL, tags_json TEXT NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE required_node_ids (osm_id TEXT PRIMARY KEY) WITHOUT ROWID;
        CREATE TABLE resolved_required_node_ids (osm_id TEXT PRIMARY KEY) WITHOUT ROWID;
        CREATE TABLE emitted_nodes (
            osm_id TEXT PRIMARY KEY, lon REAL NOT NULL, lat REAL NOT NULL, tags_json TEXT NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE seen_relation_ids (osm_id TEXT PRIMARY KEY) WITHOUT ROWID;
        CREATE TABLE selected_relations (
            osm_id TEXT PRIMARY KEY, members_json TEXT NOT NULL, tags_json TEXT NOT NULL
        ) WITHOUT ROWID;
        """
    )


def _insert_unique(connection: sqlite3.Connection, table: str, osm_id: str, entity: str, phase: str) -> None:
    try:
        connection.execute(f"INSERT INTO {table} (osm_id) VALUES (?)", (osm_id,))
    except sqlite3.IntegrityError as error:
        raise ExtractionFailure(
            f"Duplicate {entity} identity in source: {osm_id}",
            [{"entity_type": entity, "osm_id": osm_id, "phase": phase, "reason": "duplicate entity identity"}],
        ) from error


def _apply(connection: sqlite3.Connection, path: Path, handler: osmium.SimpleHandler, phase: str, timings: dict[str, float]) -> None:
    started = time.monotonic()
    connection.execute("BEGIN")
    try:
        handler.apply_file(str(path), locations=False)
        connection.commit()
    except ExtractionFailure:
        connection.rollback()
        raise
    except Exception as error:
        connection.rollback()
        raise ExtractionFailure(f"PBF {phase} pass failed: {type(error).__name__}: {error}") from error
    timings[phase] = round(time.monotonic() - started, 3)


def _write_jsonl(path: Path, query: str, connection: sqlite3.Connection, build_record: Any) -> tuple[int, str, int]:
    digest = hashlib.sha256()
    count = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        for row in connection.execute(query):
            line = _json_bytes(build_record(row)) + b"\n"
            stream.write(line)
            digest.update(line)
            count += 1
        stream.flush()
        os.fsync(stream.fileno())
    return count, digest.hexdigest(), path.stat().st_size


def _validate_tags(value: Any, entity: str, osm_id: str) -> bool:
    if not isinstance(value, dict) or any(not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()):
        raise ExtractionFailure(f"Malformed tags for {entity} {osm_id}", [{"entity_type": entity, "osm_id": osm_id, "phase": "reopen-validation", "reason": "tags must map strings to strings"}])
    return True


MAX_CANONICAL_RECORD_BYTES = 16 * 1024 * 1024


def _canonical_records(path: Path):
    """Read one bounded JSONL record at a time."""
    with path.open("rb") as stream:
        line_number = 0
        while raw := stream.readline(MAX_CANONICAL_RECORD_BYTES + 1):
            line_number += 1
            if len(raw) > MAX_CANONICAL_RECORD_BYTES:
                raise ExtractionFailure(f"Canonical record exceeds {MAX_CANONICAL_RECORD_BYTES} bytes in {path.name} at line {line_number}")
            try:
                record = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ExtractionFailure(f"Malformed UTF-8 JSON record in {path.name} at line {line_number}: {error}") from error
            yield raw, record


def validate_output_directory(directory: Path) -> dict[str, Any]:
    """Stream canonical records and resolve references through a disk-backed ID index."""
    files: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="canonical-validation-", dir=directory.parent) as scratch:
        connection = sqlite3.connect(Path(scratch) / "ids.sqlite")
        try:
            connection.execute("PRAGMA cache_size=-16384")
            connection.execute("PRAGMA temp_store=FILE")
            connection.execute("CREATE TABLE ids (kind TEXT NOT NULL, osm_id TEXT NOT NULL, PRIMARY KEY(kind, osm_id)) WITHOUT ROWID")
            for name, kind, required_keys in (
                ("nodes.jsonl", "node", {"osm_id", "lon", "lat", "tags"}),
                ("ways.jsonl", "way", {"osm_id", "node_refs", "tags"}),
                ("relations.jsonl", "relation", {"osm_id", "members", "tags"}),
            ):
                path = directory / name
                digest = hashlib.sha256()
                previous_key = None
                count = 0
                if not path.is_file():
                    raise ExtractionFailure(f"Required output file is missing: {name}")
                for raw, record in _canonical_records(path):
                    digest.update(raw)
                    if not isinstance(record, dict) or set(record) != required_keys:
                        raise ExtractionFailure(f"Unexpected record fields in {name} at line {count + 1}")
                    osm_id = _id(record.get("osm_id"), kind, "reopen-validation")
                    sort_key = _numeric_sort_key(osm_id)
                    if previous_key is not None and sort_key <= previous_key:
                        raise ExtractionFailure(f"Records in {name} are not strictly sorted by numeric OSM ID")
                    previous_key = sort_key
                    if raw != _json_bytes(record) + b"\n":
                        raise ExtractionFailure(f"Record in {name} is not canonical JSON at line {count + 1}")
                    _validate_tags(record["tags"], kind, osm_id)
                    if kind == "node":
                        lon, lat = record["lon"], record["lat"]
                        if isinstance(lon, bool) or isinstance(lat, bool) or not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
                            raise ExtractionFailure(f"Node {osm_id} has nonnumeric coordinates")
                        if not math.isfinite(lon) or not math.isfinite(lat) or not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
                            raise ExtractionFailure(f"Node {osm_id} has invalid coordinates")
                    elif kind == "way":
                        refs = record["node_refs"]
                        if not isinstance(refs, list) or len(refs) < 2:
                            raise ExtractionFailure(f"Way {osm_id} must have at least two string node references")
                        for ref in refs:
                            _id(ref, "way node reference", "reopen-validation")
                    else:
                        if not isinstance(record["members"], list):
                            raise ExtractionFailure(f"Relation {osm_id} members must be an array")
                        for member in record["members"]:
                            if not isinstance(member, dict) or set(member) != {"type", "ref", "role", "resolved"}:
                                raise ExtractionFailure(f"Relation {osm_id} has a malformed member")
                            if member["type"] not in {"node", "way", "relation"} or not isinstance(member["role"], str) or not isinstance(member["resolved"], bool):
                                raise ExtractionFailure(f"Relation {osm_id} has an invalid member value")
                            _id(member["ref"], "relation member reference", "reopen-validation")
                    connection.execute("INSERT INTO ids VALUES (?, ?)", (kind, osm_id))
                    count += 1
                    if count % _BATCH_SIZE == 0:
                        connection.commit()
                connection.commit()
                files[name] = {"path": name, "count": count, "bytes": path.stat().st_size, "sha256": digest.hexdigest(), "semantic_sha256": digest.hexdigest()}
            for _, way in _canonical_records(directory / "ways.jsonl"):
                for ref in way["node_refs"]:
                    if connection.execute("SELECT 1 FROM ids WHERE kind='node' AND osm_id=?", (ref,)).fetchone() is None:
                        raise ExtractionFailure(f"Way {way['osm_id']} has unresolved emitted node references: {ref}")
            for _, relation in _canonical_records(directory / "relations.jsonl"):
                for index, member in enumerate(relation["members"]):
                    resolved = connection.execute("SELECT 1 FROM ids WHERE kind=? AND osm_id=?", (member["type"], member["ref"])).fetchone() is not None
                    if member["resolved"] is not resolved:
                        raise ExtractionFailure(f"Relation {relation['osm_id']} member {index} has an incorrect resolved flag")
            for name, expected in files.items():
                path = directory / name
                if path.stat().st_size != expected["bytes"] or sha256_file(path) != expected["sha256"]:
                    raise ExtractionFailure(f"Canonical file changed during reopen validation: {name}")
        finally:
            connection.close()
    return files


def run_extraction(
    config: PipelineConfig,
    inventory_path: Path,
    inventory_report_path: Path,
    run_id: str,
    candidate_dir: Path,
) -> dict[str, Any]:
    """Build a source-preserving regional subset under a worker-owned staging path."""
    inventory, _, inventory_hash, _, _ = load_accepted_inventory(config, inventory_path, inventory_report_path)
    source = config.sources["osm"]
    source_hash_before = sha256_file(source.path)
    source_size_before = source.path.stat().st_size
    if source_hash_before.casefold() != (source.expected_sha256 or "").casefold():
        raise ExtractionFailure("OSM source changed after accepted-inventory validation")
    identity = code_identity()
    code_manifest_path = candidate_dir / "code-manifest.json"
    candidate_dir.mkdir(parents=True, exist_ok=False)
    code_manifest_path.write_bytes(_json_bytes({"algorithm": identity["algorithm"], "files": identity["manifest"]}) + b"\n")

    timings: dict[str, float] = {}
    scanned = {"node": 0, "way": 0, "relation": 0}
    bbox = config.extract_bbox
    with tempfile.TemporaryDirectory(prefix="extract-index-", dir=candidate_dir.parent) as temp_dir:
        database_path = Path(temp_dir) / "index.sqlite"
        connection = sqlite3.connect(database_path)
        try:
            _configure_database(connection)

            class NodeIndexHandler(osmium.SimpleHandler):
                def node(self, node: Any) -> None:
                    osm_id = _reader_id(node.id, "node", "node-index")
                    scanned["node"] += 1
                    _insert_unique(connection, "seen_node_ids", osm_id, "node", "node-index")
                    lon, lat = _coordinates(node, osm_id, "node-index")
                    if bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]:
                        tags = _tags(node.tags, "node", osm_id, "node-index")
                        connection.execute(
                            "INSERT INTO inside_nodes VALUES (?, ?, ?, ?)",
                            (osm_id, lon, lat, _json_bytes(tags).decode("utf-8")),
                        )
                    if scanned["node"] % _BATCH_SIZE == 0:
                        connection.commit()
                        connection.execute("BEGIN")

            _apply(connection, source.path, NodeIndexHandler(), "node_index", timings)
            inside_ids = {row[0] for row in connection.execute("SELECT osm_id FROM inside_nodes")}

            class WaySelectionHandler(osmium.SimpleHandler):
                def way(self, way: Any) -> None:
                    osm_id = _reader_id(way.id, "way", "way-selection")
                    scanned["way"] += 1
                    _insert_unique(connection, "seen_way_ids", osm_id, "way", "way-selection")
                    highway_present = any(tag.k == "highway" for tag in way.tags)
                    if highway_present:
                        refs = [_reader_id(node.ref, "way node reference", "way-selection") for node in way.nodes]
                        if any(ref in inside_ids for ref in refs):
                            if len(refs) < 2:
                                raise ExtractionFailure(
                                    f"Selected way {osm_id} has fewer than two node references",
                                    [{"entity_type": "way", "osm_id": osm_id, "phase": "way-selection", "reason": "selected way has fewer than two node references"}],
                                )
                            tags = _tags(way.tags, "way", osm_id, "way-selection")
                            connection.execute(
                                "INSERT INTO selected_ways VALUES (?, ?, ?)",
                                (osm_id, _json_bytes(refs).decode("utf-8"), _json_bytes(tags).decode("utf-8")),
                            )
                            connection.executemany("INSERT OR IGNORE INTO required_node_ids VALUES (?)", ((ref,) for ref in refs))
                    if scanned["way"] % _BATCH_SIZE == 0:
                        connection.commit()
                        connection.execute("BEGIN")

            _apply(connection, source.path, WaySelectionHandler(), "way_selection", timings)
            required_ids = {row[0] for row in connection.execute("SELECT osm_id FROM required_node_ids")}

            resolved_scan_count = 0

            class NodeResolutionHandler(osmium.SimpleHandler):
                def node(self, node: Any) -> None:
                    nonlocal resolved_scan_count
                    resolved_scan_count += 1
                    osm_id = str(node.id)
                    if osm_id in required_ids:
                        lon, lat = _coordinates(node, osm_id, "required-node-resolution")
                        tags = _tags(node.tags, "node", osm_id, "required-node-resolution")
                        connection.execute(
                            "INSERT INTO emitted_nodes VALUES (?, ?, ?, ?)",
                            (osm_id, lon, lat, _json_bytes(tags).decode("utf-8")),
                        )
                        connection.execute("INSERT INTO resolved_required_node_ids VALUES (?)", (osm_id,))
                    if resolved_scan_count % _BATCH_SIZE == 0:
                        connection.commit()
                        connection.execute("BEGIN")

            # Count this pass independently; no process-wide node map is retained.
            _apply(connection, source.path, NodeResolutionHandler(), "required_node_resolution", timings)
            if resolved_scan_count != scanned["node"]:
                raise ExtractionFailure("Node stream count changed between extraction passes")
            missing_query = (
                "SELECT required.osm_id FROM required_node_ids AS required "
                "LEFT JOIN resolved_required_node_ids AS resolved USING (osm_id) "
                "WHERE resolved.osm_id IS NULL ORDER BY length(required.osm_id), required.osm_id"
            )
            missing_count = connection.execute(f"SELECT COUNT(*) FROM ({missing_query})").fetchone()[0]
            if missing_count:
                missing_path = candidate_dir.parent / "missing-way-node-references.jsonl"
                missing_digest = hashlib.sha256()
                missing_examples: list[dict[str, Any]] = []
                with missing_path.open("wb") as diagnostic_stream:
                    for (missing_id,) in connection.execute(missing_query):
                        diagnostic = {
                            "entity_type": "node",
                            "osm_id": missing_id,
                            "phase": "required-node-resolution",
                            "reason": "referenced by selected way but absent from source",
                        }
                        line = _json_bytes(diagnostic) + b"\n"
                        diagnostic_stream.write(line)
                        missing_digest.update(line)
                        if len(missing_examples) < 100:
                            missing_examples.append(diagnostic)
                    diagnostic_stream.flush()
                    os.fsync(diagnostic_stream.fileno())
                raise ExtractionFailure(
                    f"{missing_count} selected-way node references are unresolved; see {missing_path.name}",
                    [
                        *missing_examples,
                        {
                            "diagnostic_file": missing_path.relative_to(config.repo_root).as_posix(),
                            "sha256": missing_digest.hexdigest(),
                            "record_count": missing_count,
                        },
                    ],
                )
            connection.execute(
                "INSERT OR IGNORE INTO emitted_nodes "
                "SELECT osm_id, lon, lat, tags_json FROM inside_nodes WHERE tags_json <> '{}'"
            )
            connection.commit()

            emitted_node_ids = {row[0] for row in connection.execute("SELECT osm_id FROM emitted_nodes")}
            selected_way_ids = {row[0] for row in connection.execute("SELECT osm_id FROM selected_ways")}

            class RelationHandler(osmium.SimpleHandler):
                def relation(self, relation: Any) -> None:
                    osm_id = _reader_id(relation.id, "relation", "relation-selection")
                    scanned["relation"] += 1
                    _insert_unique(connection, "seen_relation_ids", osm_id, "relation", "relation-selection")
                    retained_members: list[dict[str, Any]] = []
                    selected = False
                    for member in relation.members:
                        member_type = {"n": "node", "w": "way", "r": "relation"}.get(member.type)
                        member_type = member_type or str(member.type)
                        member_id = str(member.ref)
                        if member_type == "node" and member_id in emitted_node_ids:
                            selected = True
                        elif member_type == "way" and member_id in selected_way_ids:
                            selected = True
                        retained_members.append({"type": member_type, "ref": member_id, "role": str(member.role)})
                    if selected:
                        for member in retained_members:
                            if member["type"] not in {"node", "way", "relation"}:
                                raise ExtractionFailure(f"Unsupported relation member type in relation {osm_id}")
                            _id(member["ref"], "relation member reference", "relation-selection")
                        tags = _tags(relation.tags, "relation", osm_id, "relation-selection")
                        connection.execute(
                            "INSERT INTO selected_relations VALUES (?, ?, ?)",
                            (osm_id, _json_bytes(retained_members).decode("utf-8"), _json_bytes(tags).decode("utf-8")),
                        )
                    if scanned["relation"] % _BATCH_SIZE == 0:
                        connection.commit()
                        connection.execute("BEGIN")

            _apply(connection, source.path, RelationHandler(), "relation_selection", timings)

            selected_relation_ids = {row[0] for row in connection.execute("SELECT osm_id FROM selected_relations")}
            unresolved_counts: Counter[str] = Counter()
            unresolved_members: list[dict[str, Any]] = []
            finalized_relations: list[tuple[str, str]] = []
            repeated_references = 0
            way_reference_total = 0
            for osm_id, refs_json in connection.execute("SELECT osm_id, node_refs_json FROM selected_ways"):
                refs = json.loads(refs_json)
                way_reference_total += len(refs)
                repeated_references += len(refs) - len(set(refs))
            for osm_id, members_json in connection.execute("SELECT osm_id, members_json FROM selected_relations"):
                members = json.loads(members_json)
                for index, member in enumerate(members):
                    present = member["ref"] in {
                        "node": emitted_node_ids,
                        "way": selected_way_ids,
                        "relation": selected_relation_ids,
                    }[member["type"]]
                    member["resolved"] = present
                    if not present:
                        unresolved_counts[member["type"]] += 1
                        if len(unresolved_members) < 1000:
                            unresolved_members.append(
                                {"relation_id": osm_id, "member_index": index, "type": member["type"], "ref": member["ref"], "role": member["role"]}
                            )
                finalized_relations.append((osm_id, _json_bytes(members).decode("utf-8")))
            connection.executemany("UPDATE selected_relations SET members_json = ? WHERE osm_id = ?", ((members, osm_id) for osm_id, members in finalized_relations))
            connection.commit()

            expected_counts = inventory["sources"]["osm"]["entity_counts"]
            if any(scanned[entity] != expected_counts[entity] for entity in scanned):
                raise ExtractionFailure(
                    "Full OSM entity counts do not match the accepted same-source inventory",
                    [{"entity_type": entity, "phase": "count-reconciliation", "reason": "scanned count differs from accepted inventory", "scanned": scanned[entity], "inventory": expected_counts[entity]} for entity in scanned if scanned[entity] != expected_counts[entity]],
                )
            source_hash_after = sha256_file(source.path)
            if source_hash_after != source_hash_before or source.path.stat().st_size != source_size_before:
                raise ExtractionFailure("OSM source changed during extraction; candidate output is not accepted")

            def node_record(row: tuple[Any, ...]) -> dict[str, Any]:
                osm_id, lon, lat, tags_json = row
                return {"osm_id": osm_id, "lon": lon, "lat": lat, "tags": json.loads(tags_json)}

            def way_record(row: tuple[Any, ...]) -> dict[str, Any]:
                osm_id, refs_json, tags_json = row
                return {"osm_id": osm_id, "node_refs": json.loads(refs_json), "tags": json.loads(tags_json)}

            def relation_record(row: tuple[Any, ...]) -> dict[str, Any]:
                osm_id, members_json, tags_json = row
                return {"osm_id": osm_id, "members": json.loads(members_json), "tags": json.loads(tags_json)}

            files = {}
            for filename, query, builder in (
                ("nodes.jsonl", "SELECT osm_id, lon, lat, tags_json FROM emitted_nodes ORDER BY length(osm_id), osm_id", node_record),
                ("ways.jsonl", "SELECT osm_id, node_refs_json, tags_json FROM selected_ways ORDER BY length(osm_id), osm_id", way_record),
                ("relations.jsonl", "SELECT osm_id, members_json, tags_json FROM selected_relations ORDER BY length(osm_id), osm_id", relation_record),
            ):
                count, digest, byte_count = _write_jsonl(candidate_dir / filename, query, connection, builder)
                files[filename] = {"path": filename, "count": count, "bytes": byte_count, "sha256": digest, "semantic_sha256": digest}
        finally:
            connection.close()

    reopened_files = validate_output_directory(candidate_dir)
    if reopened_files != files:
        raise ExtractionFailure("Reopened canonical output hashes or counts do not match the writer results")
    source_hash_after = sha256_file(source.path)
    if source_hash_after != source_hash_before:
        raise ExtractionFailure("OSM source changed before extraction candidate validation completed")

    emitted_extent = None
    with (candidate_dir / "nodes.jsonl").open("r", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            lon, lat = record["lon"], record["lat"]
            if emitted_extent is None:
                emitted_extent = [lon, lat, lon, lat]
            else:
                emitted_extent = [min(emitted_extent[0], lon), min(emitted_extent[1], lat), max(emitted_extent[2], lon), max(emitted_extent[3], lat)]

    selected_way_count = files["ways.jsonl"]["count"]
    status = "empty" if selected_way_count == 0 else "pass"
    total_references = way_reference_total
    metadata = {
        "contract_version": CONTRACT_VERSION,
        "selection_id": SELECTION_ID,
        "status": status,
        "region_id": config.region_id,
        "run_id": run_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "code_revision": _git_revision(config.repo_root),
        "code_identity": {"algorithm": identity["algorithm"], "sha256": identity["sha256"], "manifest_path": "code-manifest.json"},
        "configuration": {"path": config.config_path.relative_to(config.repo_root).as_posix(), "sha256": sha256_file(config.config_path)},
        "accepted_source_inventory": {
            "path": inventory_path.relative_to(config.repo_root).as_posix(),
            "run_report_path": inventory_report_path.relative_to(config.repo_root).as_posix(),
            "sha256": inventory_hash,
        },
        "source": {
            "source_id": "osm",
            "path": source.relative_path,
            "bytes": source_size_before,
            "sha256": source_hash_before,
            "expected_sha256": source.expected_sha256,
            "vintage_claim": inventory["sources"]["osm"].get("claimed_vintage"),
            "observed_header_vintage": inventory["sources"]["osm"].get("observed_header_vintage"),
            "inventory_evidence": {
                key: inventory["sources"]["osm"].get(key)
                for key in (
                    "source_url",
                    "source_url_evidence",
                    "retrieval_provenance_status",
                    "license_reference",
                    "license_status",
                    "warnings",
                )
                if key in inventory["sources"]["osm"]
            },
        },
        "coverage": {
            "core_bbox": list(config.core_bbox),
            "extract_bbox": list(config.extract_bbox),
            "expanded_comparison_bbox": list(config.expanded_bbox),
            "crs": config.storage_crs,
            "actual_emitted_coordinate_extent": emitted_extent,
        },
        "inspection": {"crs": config.inspection_crs, "length_method": config.length_method},
        "canonicalization": {"id": "python-json-sorted-compact-1", "python_version": runtime_versions()["python"]},
        "environment": runtime_versions(),
        "counts": {
            "scanned_entities": scanned,
            "inside_extract_nodes": len(inside_ids),
            "selected_ways": selected_way_count,
            "emitted_nodes": files["nodes.jsonl"]["count"],
            "emitted_relations": files["relations.jsonl"]["count"],
            "complete_way_node_reference_total": total_references,
            "unique_required_way_nodes": len(required_ids),
            "unresolved_way_node_references": 0,
            "unresolved_relation_members_by_type": {entity: unresolved_counts[entity] for entity in ("node", "way", "relation")},
            "repeated_way_node_references": repeated_references,
            "segment_count": None,
            "zero_length_segment_count": None,
            "duplicate_geometry_count": None,
        },
        "diagnostics": {"unresolved_relation_member_examples": unresolved_members, "segment_and_geometry_checks": "not_run_task_2_3"},
        "processing": {"pass_durations_seconds": timings, "source_hash_verified_before_and_after": True, "sqlite_index": "disk-backed; removed after extraction"},
        "files": files,
        "limitations": [
            *inventory.get("limitations", []),
            *inventory["sources"]["osm"].get("warnings", []),
            "Node-in-bbox selection may omit a way crossing the bbox without an inside source node.",
            "Complete selected ways do not establish complete routes or source completeness.",
            "Relations are retained by direct selected-node/selected-way membership; relation semantics are not interpreted.",
            "No pedestrian eligibility, connectivity repair, clipping, snapping, or routing graph is produced.",
            "Expanded comparison bounds are configured metadata; this run does not extract the expanded comparison region.",
        ],
    }
    (candidate_dir / "extraction.json").write_bytes(json.dumps(metadata, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n")
    return {"status": status, "metadata": metadata, "files": files, "source_sha256": source_hash_before, "inventory_sha256": inventory_hash}


def _git_revision(repo_root: Path) -> dict[str, str | bool | None]:
    import subprocess

    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, check=True, capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=repo_root, check=True, capture_output=True, text=True).stdout.strip())
        return {"revision": revision, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"revision": None, "dirty": True}

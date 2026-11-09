"""Full, read-only inventory of configured local source files."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import zipfile
from typing import Any

from .code_identity import code_identity
from .config import PipelineConfig, SourceConfig


HASH_CHUNK_BYTES = 1024 * 1024
CENSUS_CHUNK_FEATURES = 8192
REFERENCE_CENSUS_COUNTS = {"census_blocks": 140_345, "census_block_groups": 4_058}
GEOID_WIDTHS = {"census_blocks": 15, "census_block_groups": 12}
SELECTED_CATALOG_FIELDS = ("GEO_ID", "for", "in", "ucgid", "B01003_001E", "B08301_001E")
COUNT_FIELDS = {"census_blocks": ("POP20", "HOUSING20"), "census_block_groups": ()}


def sha256_file(path: Path) -> str:
    """Hash a file using a fixed-size read buffer."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_hash_match(observed: str, expected: str | None) -> bool | None:
    """Return None for discovery mode; never changes a configured hash."""
    if expected is None:
        return None
    return observed.casefold() == expected.casefold()


def _source_record(source: SourceConfig, claimed_vintage: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "source_id": source.source_id,
        "path": source.relative_path,
        "exists": source.path.is_file(),
        "bytes": source.path.stat().st_size if source.path.is_file() else None,
        "sha256": None,
        "expected_sha256": source.expected_sha256,
        "expected_sha256_matches": None,
        "source_url": None,
        "source_url_evidence": None,
        "claimed_vintage": {"value": claimed_vintage, "basis": "archive filename only"} if claimed_vintage else None,
        "observed_header_vintage": None,
        "download_time_utc": None,
        "provenance_status": "incomplete; retrieval and source evidence were not supplied",
        "license_reference": None,
        "crs": None,
        "fields": None,
        "actual_feature_count": None,
        "header_feature_count": None,
        "identifier_checks": None,
        "archive_integrity": None,
        "warnings": ["Archive retrieval URL, retrieval time, and license evidence are unknown; local file time is not used as provenance."],
        "errors": [],
        "validation_status": "pending",
    }
    return record


def _mark_file_stability(record: dict[str, Any], source: SourceConfig, before: tuple[int, int] | None) -> None:
    try:
        stat = source.path.stat()
        after = (stat.st_size, stat.st_mtime_ns)
        record["file_stable_during_inventory"] = before == after
        if before != after:
            record["errors"].append("Source size or modification marker changed during inventory; results may describe different file states.")
            record["validation_status"] = "fail"
    except OSError as error:
        record["file_stable_during_inventory"] = False
        record["errors"].append(f"Could not confirm source stability: {error}")
        record["validation_status"] = "fail"


def _zip_shapefile_members(path: Path) -> tuple[dict[str, Any], str | None]:
    """Check every ZIP member CRC and identify the required sidecar set."""
    with zipfile.ZipFile(path) as archive:
        members = archive.namelist()
        corrupt_member = archive.testzip()
    shapefiles = [name for name in members if name.casefold().endswith(".shp")]
    shp_member = shapefiles[0] if len(shapefiles) == 1 else None
    missing: list[str] = []
    required: list[str] = []
    if shp_member is not None:
        stem = str(PurePosixPath(shp_member).with_suffix(""))
        required = [f"{stem}{extension}" for extension in (".shp", ".shx", ".dbf", ".prj")]
        names = {name.casefold() for name in members}
        missing = [name for name in required if name.casefold() not in names]
    integrity = {
        "member_count": len(members),
        "shapefile_count": len(shapefiles),
        "shapefile_member": shp_member,
        "required_members": required,
        "missing_required_members": missing,
        "crc_test": "fail" if corrupt_member else "pass",
        "first_corrupt_member": corrupt_member,
    }
    return integrity, shp_member


def _is_null(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        return math.isnan(value)
    return False


def _count_values(values: list[Any], state: dict[str, int]) -> None:
    for value in values:
        state["value_count"] += 1
        if value is None:
            state["null_count"] += 1
            continue
        if isinstance(value, bool):
            state["non_numeric_count"] += 1
            continue
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            state["non_numeric_count"] += 1
            continue
        if not math.isfinite(number):
            state["nonfinite_count"] += 1
        elif number < 0:
            state["negative_count"] += 1


def _scan_census_archive(path: Path, source_id: str) -> dict[str, Any]:
    import pyogrio

    archive_integrity, shp_member = _zip_shapefile_members(path)
    details: dict[str, Any] = {"archive_integrity": archive_integrity}
    if archive_integrity["crc_test"] != "pass":
        details.setdefault("errors", []).append(f"ZIP CRC check failed at {archive_integrity['first_corrupt_member']}")
    if archive_integrity["shapefile_count"] != 1:
        details.setdefault("errors", []).append(f"Expected one shapefile; found {archive_integrity['shapefile_count']}")
        return details
    if archive_integrity["missing_required_members"]:
        details.setdefault("errors", []).append(
            "Missing required shapefile members: " + ", ".join(archive_integrity["missing_required_members"])
        )
    if shp_member is None:
        return details

    vsi_path = f"/vsizip/{path.resolve().as_posix()}/{shp_member}"
    info = pyogrio.read_info(vsi_path, force_feature_count=True)
    fields = [str(name) for name in info["fields"].tolist()]
    ogr_types = [str(value) for value in info["ogr_types"]]
    field_info = [{"name": name, "ogr_type": kind} for name, kind in zip(fields, ogr_types, strict=True)]
    field_lookup = {name.casefold(): name for name in fields}
    identifier_name = "GEOID20" if source_id == "census_blocks" else "GEOID"
    required = {identifier_name.casefold(), *(name.casefold() for name in COUNT_FIELDS[source_id])}
    missing_fields = sorted(required - set(field_lookup))
    details.update({
        "crs": info["crs"],
        "fields": field_info,
        "geometry_type": str(info["geometry_type"]),
        "header_feature_count": int(info["features"]) if info["features"] is not None else None,
        "required_fields_present": not missing_fields,
        "missing_required_fields": missing_fields,
    })
    if not info["crs"]:
        details.setdefault("errors", []).append("Shapefile CRS could not be read")
    if missing_fields:
        details.setdefault("errors", []).append("Missing required fields: " + ", ".join(missing_fields))
        return details

    actual_identifier = field_lookup[identifier_name.casefold()]
    identifier_type = next((kind for name, kind in zip(fields, ogr_types, strict=True) if name == actual_identifier), "unknown")
    ids_seen: set[str] = set()
    id_checks = {
        "field": actual_identifier,
        "source_field_type": identifier_type,
        "identifiers_evaluated_as_strings": True,
        "expected_width": GEOID_WIDTHS[source_id],
        "checked_count": 0,
        "null_count": 0,
        "blank_count": 0,
        "duplicate_count": 0,
        "invalid_width_count": 0,
        "invalid_format_count": 0,
        "sample_ids": [],
        "duplicate_examples": [],
        "invalid_examples": [],
    }
    numeric_checks = {
        field_lookup[field.casefold()]: {"value_count": 0, "null_count": 0, "nonfinite_count": 0, "negative_count": 0, "non_numeric_count": 0}
        for field in COUNT_FIELDS[source_id]
    }
    read_columns = [actual_identifier, *numeric_checks]
    actual_count = 0
    offset = 0
    while True:
        frame = pyogrio.read_dataframe(
            vsi_path,
            columns=read_columns,
            read_geometry=False,
            skip_features=offset,
            max_features=CENSUS_CHUNK_FEATURES,
            use_arrow=False,
        )
        chunk_size = len(frame)
        if chunk_size == 0:
            break
        actual_count += chunk_size
        offset += chunk_size
        for value in frame[actual_identifier].tolist():
            id_checks["checked_count"] += 1
            if _is_null(value):
                id_checks["null_count"] += 1
                continue
            identifier = str(value)
            if len(id_checks["sample_ids"]) < 5:
                id_checks["sample_ids"].append(identifier)
            if identifier.strip() == "":
                id_checks["blank_count"] += 1
                continue
            if identifier in ids_seen:
                id_checks["duplicate_count"] += 1
                if len(id_checks["duplicate_examples"]) < 10:
                    id_checks["duplicate_examples"].append(identifier)
            else:
                ids_seen.add(identifier)
            if len(identifier) != GEOID_WIDTHS[source_id]:
                id_checks["invalid_width_count"] += 1
                if len(id_checks["invalid_examples"]) < 10:
                    id_checks["invalid_examples"].append(identifier)
            if re.fullmatch(r"[0-9]+", identifier) is None:
                id_checks["invalid_format_count"] += 1
                if len(id_checks["invalid_examples"]) < 10:
                    id_checks["invalid_examples"].append(identifier)
        for field, state in numeric_checks.items():
            _count_values(frame[field].tolist(), state)
        del frame

    prior_count = REFERENCE_CENSUS_COUNTS[source_id]
    header_count = details["header_feature_count"]
    count_plausibility = {
        "actual_count": actual_count,
        "reported_header_count": header_count,
        "previously_observed_dbf_count": prior_count,
        "matches_reported_header": header_count == actual_count,
        "matches_previous_observation": prior_count == actual_count,
        "previous_observation_is_a_review_reference_not_a_source_authority": True,
    }
    if header_count != actual_count:
        details.setdefault("errors", []).append(f"Read {actual_count} features; OGR reported {header_count}")
    if prior_count != actual_count:
        details.setdefault("warnings", []).append(
            f"Full feature count {actual_count} differs from the previously observed DBF count {prior_count}; review source identity and history."
        )
    if identifier_type.casefold() not in {"oftstring", "oftwidestring"}:
        details.setdefault("errors", []).append(f"Identifier source field is not a string field: {identifier_type}")
    if any(id_checks[key] for key in ("null_count", "blank_count", "duplicate_count", "invalid_width_count", "invalid_format_count")):
        details.setdefault("errors", []).append("Identifier validation found null, blank, duplicate, or malformed values")
    for field, state in numeric_checks.items():
        state["invalid_count"] = sum(state[key] for key in ("null_count", "nonfinite_count", "negative_count", "non_numeric_count"))
        if state["invalid_count"]:
            details.setdefault("errors", []).append(f"Count field {field} has {state['invalid_count']} null, nonfinite, negative, or nonnumeric values")

    details["actual_feature_count"] = actual_count
    details["count_plausibility"] = count_plausibility
    details["identifier_checks"] = id_checks
    details["numeric_count_checks"] = numeric_checks
    details["scan"] = {
        "scope": "complete feature iteration for required attributes",
        "complete": True,
        "chunk_size_features": CENSUS_CHUNK_FEATURES,
        "geometry_validity_checked": False,
    }
    return details


def _scan_pbf(path: Path) -> dict[str, Any]:
    from collections import Counter

    import osmium

    processor = osmium.FileProcessor(path)
    header = processor.header
    header_fields = (
        "generator",
        "osmosis_replication_timestamp",
        "osmosis_replication_sequence_number",
        "osmosis_replication_base_url",
        "sorting",
    )
    header_values = {key: header.get(key, "") or None for key in header_fields}
    header_box = str(header.box())
    entity_counts: Counter[str] = Counter()
    tagged_counts: Counter[str] = Counter()
    tag_key_counts: Counter[tuple[str, str]] = Counter()
    way_reference_count = 0
    ways_without_references = 0
    relation_member_count = 0
    relations_without_members = 0
    valid_node_locations = 0
    invalid_node_locations = 0

    for obj in processor:
        if obj.is_node():
            entity = "node"
            if obj.location.valid():
                valid_node_locations += 1
            else:
                invalid_node_locations += 1
        elif obj.is_way():
            entity = "way"
            ref_count = 0
            for _node in obj.nodes:
                ref_count += 1
            way_reference_count += ref_count
            ways_without_references += ref_count == 0
        elif obj.is_relation():
            entity = "relation"
            member_count = 0
            for _member in obj.members:
                member_count += 1
            relation_member_count += member_count
            relations_without_members += member_count == 0
        else:
            continue
        entity_counts[entity] += 1
        tags = obj.tags
        if len(tags):
            tagged_counts[entity] += 1
            for tag in tags:
                tag_key_counts[(entity, str(tag.k))] += 1

    counts = {name: int(entity_counts[name]) for name in ("node", "way", "relation")}
    return {
        "header": {
            "values": header_values,
            "bounding_box": header_box,
            "observed_replication_timestamp": header_values["osmosis_replication_timestamp"],
            "replication_timestamp_is_not_download_time": True,
        },
        "source_url": header_values["osmosis_replication_base_url"],
        "source_url_evidence": "PBF header field osmosis_replication_base_url; update base URL, not proof of archive retrieval URL.",
        "crs": {"value": "EPSG:4326", "basis": "OSM PBF node coordinates are longitude/latitude; the file header does not declare a CRS."},
        "entity_counts": counts,
        "entity_availability": {name: count > 0 for name, count in counts.items()},
        "tag_diagnostics": {
            "tagged_entity_counts": {name: int(tagged_counts[name]) for name in ("node", "way", "relation")},
            "top_tag_keys_by_entity": [
                {"entity": entity, "key": key, "tag_occurrences": count}
                for (entity, key), count in tag_key_counts.most_common(60)
            ],
        },
        "reference_diagnostics": {
            "way_node_reference_count": way_reference_count,
            "ways_without_node_references": ways_without_references,
            "relation_member_reference_count": relation_member_count,
            "relations_without_members": relations_without_members,
            "references_resolved": False,
            "note": "Reference counts were inventoried; cross-entity reference resolution was not run.",
        },
        "node_location_diagnostics": {"valid_count": valid_node_locations, "invalid_count": invalid_node_locations},
        "scan": {"scope": "complete FileProcessor entity stream", "complete": True, "sampled": False},
    }


def _scan_catalog(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict) or not isinstance(payload.get("variables"), dict):
        raise ValueError("Variables catalog must be a JSON object containing a variables object")
    variables = payload["variables"]
    selected: dict[str, Any] = {}
    for name in SELECTED_CATALOG_FIELDS:
        value = variables.get(name)
        selected[name] = {
            "present": name in variables,
            "metadata_keys": sorted(value) if isinstance(value, dict) else [],
        }
    missing = [name for name, value in selected.items() if not value["present"]]
    return {
        "structure": {"top_level_keys": sorted(payload), "variables_entry_count": len(variables)},
        "selected_field_presence": selected,
        "missing_selected_fields": missing,
        "selected_fields_are_structural_probes_not_approved_indicators": True,
        "acs_observations_retrieved": False,
        "dataset_vintage_verified": False,
        "scan": {"scope": "complete JSON parse", "complete": True},
        "warnings": ["This is a variables metadata catalog; it contains no ACS observation retrieval evidence."],
    }


def build_inventory(config: PipelineConfig) -> dict[str, Any]:
    """Inspect each source without changing configuration or source files."""
    source_results: dict[str, Any] = {}
    expected_sources = ("osm", "census_blocks", "census_block_groups", "variables_catalog")
    for source_id in expected_sources:
        source = config.sources.get(source_id)
        if source is None:
            source_results[source_id] = {
                "source_id": source_id,
                "validation_status": "fail",
                "errors": ["Source is not configured; add its path and expected_sha256 to the TOML config."],
                "warnings": [],
            }
            continue
        claimed_vintage = {"census_blocks": "2020", "census_block_groups": "2024"}.get(source_id)
        record = _source_record(source, claimed_vintage)
        source_results[source_id] = record
        if not source.path.is_file():
            record["errors"].append(f"Source file is missing: {source.relative_path}")
            record["validation_status"] = "fail"
            continue
        initial_stat = source.path.stat()
        before = (initial_stat.st_size, initial_stat.st_mtime_ns)
        record["bytes"] = initial_stat.st_size
        try:
            if source_id == "osm":
                detail = _scan_pbf(source.path)
                record.update(detail)
                record["observed_header_vintage"] = detail["header"]["observed_replication_timestamp"]
            elif source_id in {"census_blocks", "census_block_groups"}:
                detail = _scan_census_archive(source.path, source_id)
                record.update(detail)
                if detail.get("archive_integrity", {}).get("crc_test") != "pass":
                    record["errors"].append("Archive CRC validation did not pass")
            else:
                detail = _scan_catalog(source.path)
                record.update(detail)
            record["sha256"] = sha256_file(source.path)
            record["expected_sha256_matches"] = expected_hash_match(record["sha256"], source.expected_sha256)
            if record["expected_sha256_matches"] is False:
                record["errors"].append("Observed SHA-256 does not match configured expected_sha256; the configuration was not changed.")
            _mark_file_stability(record, source, before)
            # Census scanner errors and malformed catalog fields are source validation findings.
            record_errors = record.get("errors", [])
            if source_id in {"census_blocks", "census_block_groups"} and record_errors:
                pass
            if record["expected_sha256_matches"] is False or record_errors:
                record["validation_status"] = "fail"
            elif source_id == "osm" and not all(record["entity_availability"].values()):
                record["errors"].append("One or more OSM entity types are absent")
                record["validation_status"] = "fail"
            elif source_id == "variables_catalog" and record["missing_selected_fields"]:
                record["warnings"].append("One or more structural probe fields are absent from the catalog.")
                record["validation_status"] = "pass_with_warnings"
            elif source_id in {"census_blocks", "census_block_groups"}:
                plausibility = record.get("count_plausibility", {})
                if not plausibility.get("matches_previous_observation", False):
                    record["validation_status"] = "review_required"
                elif record.get("warnings"):
                    record["validation_status"] = "pass_with_warnings"
                else:
                    record["validation_status"] = "pass"
            elif record.get("warnings"):
                record["validation_status"] = "pass_with_warnings"
            else:
                record["validation_status"] = "pass"
        except Exception as error:  # Preserve a per-source failure record and continue inventorying other sources.
            record["errors"].append(f"Inventory scan failed: {type(error).__name__}: {error}")
            record["validation_status"] = "fail"
            _mark_file_stability(record, source, before)
            try:
                record["sha256"] = sha256_file(source.path)
                record["expected_sha256_matches"] = expected_hash_match(record["sha256"], source.expected_sha256)
            except OSError as hash_error:
                record["errors"].append(f"Could not hash source: {hash_error}")

    statuses = [record.get("validation_status", "fail") for record in source_results.values()]
    status = "fail" if any(value == "fail" for value in statuses) else "review_required" if "review_required" in statuses else "pass_with_warnings" if "pass_with_warnings" in statuses else "pass"
    return {
        "inventory_version": "source-inventory-1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "code_identity": code_identity(),
        "region_id": config.region_id,
        "configuration": config.config_path.relative_to(config.repo_root).as_posix(),
        "inventory_status": status,
        "hashes_are_discovery_candidates_until_reviewed": any(source.expected_sha256 is None for source in config.sources.values()),
        "sources": source_results,
        "limitations": [
            "Unknown source provenance remains unresolved until download receipts, source URLs, and license evidence are supplied.",
            "Census count references reproduce prior local DBF observations; they are not independent official expectations.",
            "Census geometry validity and spatial coverage were not checked; the inventory read required attributes without geometry.",
            "OSM ways and relation members are counted but references are not resolved across entities.",
            "The variables catalog describes available metadata; no ACS observations were retrieved and its vintage is unverified.",
        ],
    }


def inventory_bytes(inventory: dict[str, Any]) -> bytes:
    """Return the canonical JSON bytes used for the run report's inventory hash."""
    return (json.dumps(inventory, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")

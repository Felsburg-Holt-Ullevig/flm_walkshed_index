"""Experimental Census ingestion, geography reconciliation, and local packaging."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import uuid
import zipfile
from typing import Any, Iterable

from .census_http import request_json
from .census_normalize import normalize_quartet
from .census_spec import (
    ACS_REQUEST_FIELDS,
    CONFIGURATION_VERSION,
    COUNTY_FIPS,
    DATASET_PATH,
    GEOGRAPHY_FIELDS,
    NORMALIZATION_VERSION,
    SPECIFICATION_VERSION,
    STATE_FIPS,
    VARIABLES,
)
from .code_identity import code_identity
from .runtime import runtime_versions


ACS_BASE = f"https://api.census.gov/data/{DATASET_PATH}"
TIGER_VINTAGES = {"census_blocks": "2020", "census_block_groups": "2024"}
SOURCE_IDS = ("census_blocks", "census_block_groups", "variables_catalog")
SOURCE_FIELDS = {
    "census_blocks": (
        "STATEFP20", "COUNTYFP20", "TRACTCE20", "BLOCKCE20", "GEOID20",
        "NAME20", "MTFCC20", "UR20", "UACE20", "UATYPE20", "FUNCSTAT20",
        "ALAND20", "AWATER20", "INTPTLAT20", "INTPTLON20", "HOUSING20", "POP20",
    ),
    "census_block_groups": (
        "STATEFP", "COUNTYFP", "TRACTCE", "BLKGRPCE", "GEOID", "GEOIDFQ",
        "NAMELSAD", "MTFCC", "FUNCSTAT", "ALAND", "AWATER", "INTPTLAT", "INTPTLON",
    ),
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HEX_GEOID = re.compile(r"^[0-9]{12}$")


class CensusConfigError(ValueError):
    """Raised when the local Task 5.5 configuration is incomplete or unsafe."""


class CensusSampleError(RuntimeError):
    """Raised when the Census sample cannot be validated for promotion."""


class CensusJoinError(CensusSampleError):
    def __init__(self, message: str, report: dict[str, Any]):
        super().__init__(message)
        self.report = report


@dataclass(frozen=True)
class CensusSource:
    source_id: str
    path: Path
    relative_path: str
    expected_sha256: str


@dataclass(frozen=True)
class CensusSampleConfig:
    config_path: Path
    repo_root: Path
    configuration_version: str
    specification_version: str
    accepted_specification_version: str
    state_fips: str
    county_fips: tuple[str, ...]
    sources: dict[str, CensusSource]
    output_root: Path
    output_relative_path: str
    cache_root: Path
    cache_relative_path: str
    cache_snapshot_id: str
    timeout_seconds: int
    rss_limit_bytes: int
    expected_metadata_sha256: dict[str, str | None]


def _strict_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    extra = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if extra or missing:
        details = []
        if extra:
            details.append(f"unknown fields: {', '.join(extra)}")
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        raise CensusConfigError(f"{label}: {'; '.join(details)}")


def _contained_relative(value: object, label: str, root: Path) -> tuple[Path, str]:
    if not isinstance(value, str) or not value.strip():
        raise CensusConfigError(f"{label} must be a non-empty repository-relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise CensusConfigError(f"{label} must stay within the repository")
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise CensusConfigError(f"{label} resolves outside the repository") from error
    return resolved, path.as_posix()


def load_census_config(config_path: str | Path) -> CensusSampleConfig:
    """Load the explicit local acceptance record and immutable source pins."""
    import tomllib

    path = Path(config_path).resolve()
    if not path.is_file():
        raise CensusConfigError("Census sample configuration does not exist")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise CensusConfigError("Census sample configuration could not be read as UTF-8 TOML") from error
    if not isinstance(raw, dict):
        raise CensusConfigError("Census sample configuration root must be a table")
    _strict_keys(raw, {"config_version", "specification_version", "accepted_specification_version", "state_fips", "county_fips", "sources", "output_root", "cache_root", "cache", "limits", "metadata"}, "configuration")
    if raw["config_version"] != CONFIGURATION_VERSION:
        raise CensusConfigError(f"config_version must be {CONFIGURATION_VERSION!r}")
    if raw["specification_version"] != SPECIFICATION_VERSION:
        raise CensusConfigError(f"specification_version must be {SPECIFICATION_VERSION!r}")
    if raw["accepted_specification_version"] != SPECIFICATION_VERSION:
        raise CensusConfigError("the proposed Census experiment has not been explicitly accepted in this local configuration")
    if raw["state_fips"] != STATE_FIPS or raw["county_fips"] != list(COUNTY_FIPS):
        raise CensusConfigError("state and county allowlist must exactly match the accepted specification")

    repo_root = Path(__file__).resolve().parents[3]
    try:
        path.relative_to(repo_root)
    except ValueError as error:
        raise CensusConfigError("Census sample configuration must be inside the repository") from error
    raw_root = (repo_root / "data" / "raw").resolve()
    sources_raw = raw["sources"]
    if not isinstance(sources_raw, dict):
        raise CensusConfigError("sources must be a table")
    _strict_keys(sources_raw, set(SOURCE_IDS), "sources")
    sources: dict[str, CensusSource] = {}
    for source_id in SOURCE_IDS:
        item = sources_raw[source_id]
        if not isinstance(item, dict):
            raise CensusConfigError(f"sources.{source_id} must be a table")
        _strict_keys(item, {"path", "expected_sha256"}, f"sources.{source_id}")
        source_path, relative = _contained_relative(item["path"], f"sources.{source_id}.path", repo_root)
        try:
            source_path.relative_to(raw_root)
        except ValueError as error:
            raise CensusConfigError(f"sources.{source_id}.path must remain inside data/raw") from error
        expected = item["expected_sha256"]
        if not isinstance(expected, str) or not _SHA256.fullmatch(expected):
            raise CensusConfigError(f"sources.{source_id}.expected_sha256 must contain an explicitly accepted lowercase SHA-256")
        if source_path == repo_root / "data" / "generated" or (repo_root / "data" / "generated") in source_path.parents:
            raise CensusConfigError(f"sources.{source_id}.path cannot point into generated outputs")
        sources[source_id] = CensusSource(source_id, source_path, relative, expected)

    output_root, output_rel = _contained_relative(raw["output_root"], "output_root", repo_root)
    expected_output = (repo_root / "data" / "generated" / "prototype" / "census-samples").resolve()
    if output_root != expected_output:
        raise CensusConfigError("output_root must be data/generated/prototype/census-samples")
    cache_root, cache_rel = _contained_relative(raw["cache_root"], "cache_root", repo_root)
    expected_cache = (repo_root / "data" / "generated" / "prototype" / "census-cache").resolve()
    if cache_root != expected_cache:
        raise CensusConfigError("cache_root must be data/generated/prototype/census-cache")
    cache = raw["cache"]
    if not isinstance(cache, dict):
        raise CensusConfigError("cache must be a table")
    _strict_keys(cache, {"snapshot_id"}, "cache")
    snapshot_id = cache["snapshot_id"]
    if not isinstance(snapshot_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", snapshot_id):
        raise CensusConfigError("cache.snapshot_id must be a short safe identifier; change it only for an explicit refresh")
    for source in sources.values():
        if source.path == output_root or source.path in output_root.parents or output_root in source.path.parents:
            raise CensusConfigError(f"output_root collides with source {source.relative_path}")
        if source.path == cache_root or source.path in cache_root.parents or cache_root in source.path.parents:
            raise CensusConfigError(f"cache_root collides with source {source.relative_path}")

    limits = raw["limits"]
    if not isinstance(limits, dict):
        raise CensusConfigError("limits must be a table")
    _strict_keys(limits, {"seconds", "rss_bytes"}, "limits")
    seconds, rss = limits["seconds"], limits["rss_bytes"]
    if isinstance(seconds, bool) or not isinstance(seconds, int) or not 60 <= seconds <= 3600:
        raise CensusConfigError("limits.seconds must be between 60 and 3600")
    if isinstance(rss, bool) or not isinstance(rss, int) or not 256 * 1024**2 <= rss <= 8 * 1024**3:
        raise CensusConfigError("limits.rss_bytes must be between 256 MiB and 8 GiB")

    metadata = raw["metadata"]
    if not isinstance(metadata, dict):
        raise CensusConfigError("metadata must be a table")
    _strict_keys(metadata, {"B01003_sha256", "B08201_sha256"}, "metadata")
    metadata_hashes: dict[str, str | None] = {}
    for group, value in (("B01003", metadata["B01003_sha256"]), ("B08201", metadata["B08201_sha256"])):
        if value == "":
            metadata_hashes[group] = None
        elif isinstance(value, str) and _SHA256.fullmatch(value):
            metadata_hashes[group] = value
        else:
            raise CensusConfigError(f"metadata.{group}_sha256 must be empty or a lowercase SHA-256")
    return CensusSampleConfig(
        path, repo_root, raw["config_version"], raw["specification_version"],
        raw["accepted_specification_version"], raw["state_fips"], tuple(raw["county_fips"]),
        sources, output_root, output_rel, cache_root, cache_rel, snapshot_id, seconds, rss, metadata_hashes,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _zip_shapefile(path: Path, source_id: str) -> tuple[str, list[str]]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            corrupt_member = archive.testzip()
    except (OSError, zipfile.BadZipFile) as error:
        raise CensusSampleError(f"{source_id} source is not a readable ZIP archive") from error
    if corrupt_member is not None:
        raise CensusSampleError(f"{source_id} source archive failed a CRC check")
    shape_files = [name for name in names if name.casefold().endswith(".shp")]
    if len(shape_files) != 1:
        raise CensusSampleError(f"{source_id} archive must contain exactly one shapefile")
    shape_name = shape_files[0]
    base = str(PurePosixPath(shape_name).with_suffix("")).casefold()
    required = [f"{base}{extension}" for extension in (".shp", ".shx", ".dbf", ".prj")]
    available = {name.casefold() for name in names}
    missing = sorted(set(required) - available)
    if missing:
        raise CensusSampleError(f"{source_id} archive is missing required shapefile members")
    normalized_path = path.resolve().as_posix()
    return f"/vsizip/{normalized_path}/{shape_name}", required


def _text(value: object, field: str, width: int) -> str:
    if not isinstance(value, str) or len(value) != width or not value.isascii() or not value.isdecimal():
        raise CensusSampleError(f"{field} must be a {width}-character decimal string")
    return value


def _integer_count(value: object, field: str) -> int:
    if isinstance(value, bool) or value is None:
        raise CensusSampleError(f"{field} must be a nonnegative whole-number count")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise CensusSampleError(f"{field} must be a nonnegative whole-number count") from error
    if not number.is_finite() or number < 0 or number != number.to_integral_value():
        raise CensusSampleError(f"{field} must be a nonnegative whole-number count")
    return int(number)


def validate_source_geoid(source_id: str, row: dict[str, Any]) -> str:
    if source_id == "census_blocks":
        state = _text(row.get("STATEFP20"), "STATEFP20", 2)
        county = _text(row.get("COUNTYFP20"), "COUNTYFP20", 3)
        tract = _text(row.get("TRACTCE20"), "TRACTCE20", 6)
        block = _text(row.get("BLOCKCE20"), "BLOCKCE20", 4)
        geoid = _text(row.get("GEOID20"), "GEOID20", 15)
        calculated = state + county + tract + block
    elif source_id == "census_block_groups":
        state = _text(row.get("STATEFP"), "STATEFP", 2)
        county = _text(row.get("COUNTYFP"), "COUNTYFP", 3)
        tract = _text(row.get("TRACTCE"), "TRACTCE", 6)
        group = _text(row.get("BLKGRPCE"), "BLKGRPCE", 1)
        geoid = _text(row.get("GEOID"), "GEOID", 12)
        calculated = state + county + tract + group
    else:
        raise CensusSampleError("unknown Census geography source")
    if geoid != calculated:
        raise CensusSampleError(f"{source_id} GEOID does not match its string components")
    if state != STATE_FIPS or county not in COUNTY_FIPS:
        raise CensusSampleError(f"{source_id} returned a geography outside the approved county allowlist")
    return geoid


def validate_acs_response(value: object, expected_county: str) -> list[dict[str, Any]]:
    """Validate a Census table response and preserve arbitrary header ordering."""
    if not isinstance(value, list) or not value or not isinstance(value[0], list):
        raise CensusSampleError("ACS response must be a nonempty header-and-rows JSON array")
    header = value[0]
    if any(not isinstance(item, str) for item in header) or len(set(header)) != len(header):
        raise CensusSampleError("ACS response header must contain unique string column names")
    expected = set(ACS_REQUEST_FIELDS) | set(GEOGRAPHY_FIELDS)
    if set(header) != expected:
        raise CensusSampleError("ACS response columns do not exactly match the requested fields")
    positions = {name: header.index(name) for name in header}
    rows: list[dict[str, Any]] = []
    for index, values in enumerate(value[1:], start=2):
        if not isinstance(values, list) or len(values) != len(header):
            raise CensusSampleError(f"ACS response row {index} has the wrong number of columns")
        if any(item is not None and not isinstance(item, str) for item in values):
            raise CensusSampleError(f"ACS response row {index} has a non-string value")
        row = {name: values[position] for name, position in positions.items()}
        state = _text(row.get("state"), "ACS state", 2)
        county = _text(row.get("county"), "ACS county", 3)
        tract = _text(row.get("tract"), "ACS tract", 6)
        block_group = _text(row.get("block group"), "ACS block group", 1)
        if state != STATE_FIPS or county != expected_county:
            raise CensusSampleError("ACS response contains a row outside the requested county")
        geoid = state + county + tract + block_group
        if not _HEX_GEOID.fullmatch(geoid):
            raise CensusSampleError("ACS GEOID composition failed its 12-character check")
        if not isinstance(row.get("NAME"), str) or not row["NAME"].strip():
            raise CensusSampleError(f"ACS row {index} has no NAME")
        normalized: dict[str, Any] = {"geoid": geoid, "NAME": row["NAME"], "county_fips": county}
        for cell in VARIABLES:
            quartet = normalize_quartet(
                row[f"{cell}E"], row[f"{cell}EA"], row[f"{cell}M"], row[f"{cell}MA"],
            )
            normalized[cell] = quartet.as_dict()
        rows.append(normalized)
    if not rows:
        raise CensusSampleError("ACS response contains a header but no block-group records")
    return rows


def validate_metadata(group: str, value: object) -> None:
    if group not in {"B01003", "B08201"} or not isinstance(value, dict):
        raise CensusSampleError("Census variable metadata response has an unsupported shape")
    variables = value.get("variables")
    if not isinstance(variables, dict):
        raise CensusSampleError("Census variable metadata has no variables object")
    selected = [cell for cell in VARIABLES if cell.startswith(group + "_")]
    for cell in selected:
        expected = VARIABLES[cell]
        for suffix in ("E", "EA", "M", "MA"):
            name = f"{cell}{suffix}"
            item = variables.get(name)
            if not isinstance(item, dict):
                raise CensusSampleError(f"Census variable metadata is missing {name}")
            if item.get("concept") != expected["concept"]:
                raise CensusSampleError(f"Census concept metadata differs for {name}")
            if suffix == "E" and item.get("label") != expected["estimate_label"]:
                raise CensusSampleError(f"Census estimate label differs for {name}")
            expected_type = "string" if suffix in {"EA", "MA"} else "int"
            if item.get("predicateType") != expected_type:
                raise CensusSampleError(f"Census field type metadata differs for {name}")


def join_acs_to_geometries(
    geometry_rows: Iterable[dict[str, Any]],
    acs_rows: Iterable[dict[str, Any]],
    county_fips: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Enforce a complete one-to-one county join and return detailed QA counts."""
    geoms = list(geometry_rows)
    acs = list(acs_rows)
    geometry_ids = [str(row["GEOID"]) for row in geoms]
    acs_ids = [str(row["geoid"]) for row in acs]
    duplicate_geometry = sorted(key for key, count in Counter(geometry_ids).items() if count > 1)
    duplicate_acs = sorted(key for key, count in Counter(acs_ids).items() if count > 1)
    geometry_set, acs_set = set(geometry_ids), set(acs_ids)
    unmatched_geometry = sorted(geometry_set - acs_set)
    unmatched_acs = sorted(acs_set - geometry_set)
    report = {
        "county_fips": county_fips,
        "geometry_rows": len(geoms),
        "acs_rows": len(acs),
        "duplicate_geometry_count": len(duplicate_geometry),
        "duplicate_geometry_examples": duplicate_geometry[:20],
        "duplicate_acs_count": len(duplicate_acs),
        "duplicate_acs_examples": duplicate_acs[:20],
        "unmatched_geometry_count": len(unmatched_geometry),
        "unmatched_geometry_examples": unmatched_geometry[:20],
        "unmatched_acs_count": len(unmatched_acs),
        "unmatched_acs_examples": unmatched_acs[:20],
        "join_cardinality": "one_to_one" if not (duplicate_geometry or duplicate_acs or unmatched_geometry or unmatched_acs) else "incomplete",
    }
    if duplicate_geometry or duplicate_acs or unmatched_geometry or unmatched_acs:
        raise CensusJoinError(f"complete one-to-one join failed for county {county_fips}", report)
    by_id = {row["geoid"]: row for row in acs}
    joined = [{**row, "acs": by_id[str(row["GEOID"])]} for row in geoms]
    return joined, report


def _validate_source_pins(config: CensusSampleConfig) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for source_id, source in config.sources.items():
        if not source.path.is_file():
            raise CensusSampleError(f"configured Census source is missing: {source.relative_path}")
        digest = sha256_file(source.path)
        if digest != source.expected_sha256:
            raise CensusSampleError(f"configured Census source hash does not match for {source.relative_path}")
        hashes[source_id] = digest
    return hashes


def _validate_local_catalog(source: CensusSource) -> dict[str, Any]:
    try:
        value = json.loads(source.path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CensusSampleError("the configured local Census variable catalog is not valid UTF-8 JSON") from error
    variables = value.get("variables") if isinstance(value, dict) else None
    if not isinstance(variables, dict):
        raise CensusSampleError("the configured local Census variable catalog has no variables object")
    for cell, expected in VARIABLES.items():
        item = variables.get(f"{cell}E")
        if not isinstance(item, dict):
            raise CensusSampleError(f"the local Census variable catalog is missing {cell}E")
        if (
            item.get("label") != expected["estimate_label"]
            or item.get("concept") != expected["concept"]
            or item.get("group") != cell.split("_")[0]
            or item.get("predicateType") != "int"
            or item.get("attributes") != f"{cell}EA,{cell}M,{cell}MA"
        ):
            raise CensusSampleError(f"the local Census variable catalog disagrees with the proposed contract for {cell}E")
    return {
        "status": "selected_estimate_labels_and_quartet_attributes_match",
        "vintage": "unverified",
        "entries_checked": len(VARIABLES),
        "annotations_and_moes": "listed_as_attributes; official 2024 group metadata checked separately",
    }


def _read_selected_geometries(source: CensusSource) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    import geopandas as gpd
    import pyogrio
    from shapely.geometry import MultiPolygon, Polygon

    vsi_path, required_members = _zip_shapefile(source.path, source.source_id)
    if source.source_id == "census_blocks":
        fields = SOURCE_FIELDS[source.source_id]
        where = "STATEFP20 = '08' AND COUNTYFP20 IN ('031', '073')"
        identifier = "GEOID20"
    else:
        fields = SOURCE_FIELDS[source.source_id]
        where = "STATEFP = '08' AND COUNTYFP IN ('031', '073')"
        identifier = "GEOID"
    source_info = pyogrio.read_info(vsi_path)
    missing_fields = sorted(set(fields) - set(source_info.get("fields", ())))
    if missing_fields:
        raise CensusSampleError(f"{source.source_id} source is missing required attributes: {', '.join(missing_fields)}")
    frame = pyogrio.read_dataframe(vsi_path, columns=list(fields), where=where, use_arrow=False)
    if frame.empty or frame.crs is None:
        raise CensusSampleError(f"{source.source_id} returned no selected features or has no CRS")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise CensusSampleError(f"{source.source_id} contains null or empty selected geometry")
    if not frame.geometry.is_valid.all():
        bad = [str(frame.iloc[index][identifier]) for index, valid in enumerate(frame.geometry.is_valid.tolist()) if not valid]
        raise CensusSampleError(f"{source.source_id} contains invalid selected polygons: {', '.join(bad[:20])}")
    if not all(isinstance(geometry, (Polygon, MultiPolygon)) for geometry in frame.geometry):
        raise CensusSampleError(f"{source.source_id} contains a non-polygon selected feature")
    records: list[dict[str, Any]] = []
    seen: Counter[str] = Counter()
    county_counts: Counter[str] = Counter()
    for _, series in frame.iterrows():
        row = {}
        for field in fields:
            value = series[field]
            if hasattr(value, "item"):
                value = value.item()
            if isinstance(value, float) and math.isnan(value):
                value = None
            row[field] = value
        geoid = validate_source_geoid(source.source_id, row)
        seen[geoid] += 1
        county = row["COUNTYFP20"] if source.source_id == "census_blocks" else row["COUNTYFP"]
        county_counts[county] += 1
        if source.source_id == "census_blocks":
            row["POP20"] = _integer_count(row["POP20"], "POP20")
            row["HOUSING20"] = _integer_count(row["HOUSING20"], "HOUSING20")
        row["geometry"] = series.geometry
        records.append(row)
    if set(county_counts) != set(COUNTY_FIPS):
        raise CensusSampleError(f"{source.source_id} is missing one or more configured counties")
    return records, frame.crs.to_string(), {
        "selected_feature_count": len(records),
        "county_counts": {county: county_counts[county] for county in COUNTY_FIPS},
        "duplicate_geoid_count": sum(count > 1 for count in seen.values()),
        "duplicate_geoid_examples": sorted(key for key, count in seen.items() if count > 1)[:20],
        "required_members": required_members,
        "geometry_types": sorted({geometry.geom_type for geometry in frame.geometry}),
        "invalid_geometry_count": 0,
        "source_crs": frame.crs.to_string(),
        "planned_diagnostic_crs": "EPSG:26913",
        "transformation_performed": False,
    }


def _fetch_metadata(config: CensusSampleConfig) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshots: dict[str, Any] = {}
    reports: dict[str, Any] = {}
    for group in ("B01003", "B08201"):
        response = request_json(
            f"{ACS_BASE}/groups/{group}.json", (), config.cache_root,
            response_version=f"2024-acs5-group-metadata-1:{config.cache_snapshot_id}",
        )
        validate_metadata(group, response.value)
        expected = config.expected_metadata_sha256[group]
        if expected is not None and response.body_sha256 != expected:
            raise CensusSampleError(f"pinned Census {group} metadata hash does not match")
        snapshots[group] = response.value
        reports[group] = {
            "url": f"{ACS_BASE}/groups/{group}.json",
            "sha256": response.body_sha256,
            "bytes": response.body_bytes,
            "cache_key": response.cache_key,
            "cache_hit": response.cache_hit,
            "retrieved_at_utc": response.retrieved_at_utc,
            "previous_snapshot": _previous_snapshot(config.cache_root, response.request_metadata, response.body_sha256),
        }
    return snapshots, reports


def _fetch_county_acs(config: CensusSampleConfig, county: str, api_key: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    endpoint = f"{ACS_BASE}"
    parameters = (
        ("get", ",".join(sorted(ACS_REQUEST_FIELDS))),
        ("for", "block group:*"),
        ("in", f"state:{STATE_FIPS}"),
        ("in", f"county:{county}"),
        ("in", "tract:*"),
    )
    response = request_json(
        endpoint, parameters, config.cache_root,
        response_version=f"{NORMALIZATION_VERSION}:{config.cache_snapshot_id}",
        requires_key=True,
        api_key=api_key,
    )
    rows = validate_acs_response(response.value, county)
    return rows, {
        "county_fips": county,
        "dataset": DATASET_PATH,
        "requested_field_count": len(ACS_REQUEST_FIELDS),
        "returned_rows": len(rows),
        "response_sha256": response.body_sha256,
        "response_bytes": response.body_bytes,
        "cache_key": response.cache_key,
        "cache_hit": response.cache_hit,
        "retrieved_at_utc": response.retrieved_at_utc,
        "previous_snapshot": _previous_snapshot(config.cache_root, response.request_metadata, response.body_sha256),
        "request": response.request_metadata,
    }


def _previous_snapshot(cache_root: Path, current_request: dict[str, Any], current_sha256: str) -> dict[str, Any] | None:
    """Compare explicit refreshes with the latest intact prior response."""
    matches: list[dict[str, Any]] = []
    for metadata_path in cache_root.glob("*.meta.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(metadata, dict) or not isinstance(metadata.get("request"), dict):
            continue
        prior_request = metadata["request"]
        same_request = all(
            prior_request.get(field) == current_request.get(field)
            for field in ("host", "path", "parameters")
        )
        if not same_request or prior_request.get("response_version") == current_request.get("response_version"):
            continue
        cache_key = metadata.get("cache_key")
        digest = metadata.get("sha256")
        retrieved = metadata.get("retrieved_at_utc")
        if not isinstance(cache_key, str) or not isinstance(digest, str) or not isinstance(retrieved, str):
            continue
        body_path = cache_root / f"{cache_key}.json"
        if not body_path.is_file() or sha256_file(body_path) != digest:
            continue
        matches.append({"retrieved_at_utc": retrieved, "sha256": digest, "cache_key": cache_key})
    if not matches:
        return None
    latest = max(matches, key=lambda item: item["retrieved_at_utc"])
    return {
        **latest,
        "content_changed": latest["sha256"] != current_sha256,
    }


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")


def _write_geopackage(path: Path, rows: list[dict[str, Any]], crs: str, include_acs: bool, source_id: str) -> dict[str, Any]:
    import geopandas as gpd
    import pyogrio

    if include_acs:
        output: list[dict[str, Any]] = []
        for row in rows:
            acs = row["acs"]
            item = {key: value for key, value in row.items() if key not in {"geometry", "acs"}}
            item["NAME"] = acs["NAME"]
            for cell, quartet in acs.items():
                if cell in {"geoid", "NAME", "county_fips"}:
                    continue
                for key, value in quartet.items():
                    item[f"{cell}_{key}"] = value
            item["geometry"] = row["geometry"]
            output.append(item)
    else:
        output = [{**{key: value for key, value in row.items() if key != "geometry"}, "geometry": row["geometry"]} for row in rows]
    frame = gpd.GeoDataFrame(output, geometry="geometry", crs=crs)
    layer = "blocks_2020" if source_id == "census_blocks" else "block_groups_2024_acs"
    pyogrio.write_dataframe(frame, path, layer=layer, driver="GPKG", use_arrow=False)
    reopened = pyogrio.read_dataframe(path, layer=layer, use_arrow=False)
    if len(reopened) != len(frame) or reopened.crs is None or reopened.crs.to_string() != crs:
        raise CensusSampleError(f"{source_id} GeoPackage row count or CRS did not survive reopening")
    id_field = "GEOID20" if source_id == "census_blocks" else "GEOID"
    expected_ids = sorted(str(value) for value in frame[id_field].tolist())
    actual_ids = sorted(str(value) for value in reopened[id_field].tolist())
    if expected_ids != actual_ids or reopened[id_field].isna().any():
        raise CensusSampleError(f"{source_id} GeoPackage GEOIDs did not survive reopening")
    if not reopened.geometry.is_valid.all() or reopened.geometry.is_empty.any():
        raise CensusSampleError(f"{source_id} GeoPackage geometry validation failed after reopening")
    source_by_id = {str(row[id_field]): row for row in output}
    for _, row in reopened.iterrows():
        source = source_by_id[str(row[id_field])]
        if not row.geometry.equals(source["geometry"]):
            raise CensusSampleError(f"{source_id} GeoPackage geometry changed during round trip")
        for field, value in source.items():
            if field == "geometry":
                continue
            observed = row[field]
            if value is None:
                if observed is not None and not (isinstance(observed, float) and math.isnan(observed)):
                    raise CensusSampleError(f"{source_id} GeoPackage null value changed in {field}")
            elif isinstance(value, (int, float, str, bool)) and observed != value:
                raise CensusSampleError(f"{source_id} GeoPackage value changed in {field}")
    return {
        "path": path.name,
        "layer": layer,
        "feature_count": len(reopened),
        "crs": reopened.crs.to_string(),
        "identifier_field": id_field,
        "identifier_count": len(set(actual_ids)),
        "geometries_reopened_and_matched": True,
        "attributes_reconciled": True,
    }


def _normalization_totals(acs_by_county: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for cell in VARIABLES:
        by_county: dict[str, Any] = {}
        estimate_counts: Counter[str] = Counter()
        moe_counts: Counter[str] = Counter()
        for county, rows in acs_by_county.items():
            county_estimates: Counter[str] = Counter()
            county_moes: Counter[str] = Counter()
            for row in rows:
                estimate_counts[row[cell]["estimate_status"]] += 1
                moe_counts[row[cell]["moe_status"]] += 1
                county_estimates[row[cell]["estimate_status"]] += 1
                county_moes[row[cell]["moe_status"]] += 1
            by_county[county] = {
                "estimate_status_counts": dict(sorted(county_estimates.items())),
                "moe_status_counts": dict(sorted(county_moes.items())),
            }
        result[cell] = {
            "estimate_status_counts": dict(sorted(estimate_counts.items())),
            "moe_status_counts": dict(sorted(moe_counts.items())),
            "by_county": by_county,
        }
    return result


def _source_totals(
    blocks: list[dict[str, Any]],
    acs_by_county: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    totals: dict[str, Any] = {}
    for county in COUNTY_FIPS:
        county_blocks = [row for row in blocks if row["COUNTYFP20"] == county]
        census_counts = {
            field: sum(row[field] for row in county_blocks)
            for field in ("POP20", "HOUSING20")
        }
        acs_counts: dict[str, Any] = {}
        for cell in VARIABLES:
            values = [row[cell] for row in acs_by_county[county]]
            valid = [row["estimate"] for row in values if row["estimate_status"] == "valid"]
            acs_counts[cell] = {
                "known_sum_of_valid_estimates": sum(valid),
                "valid_rows": len(valid),
                "unavailable_rows": len(values) - len(valid),
                "complete": len(valid) == len(values),
            }
        totals[county] = {
            "decennial_2020_block_counts": census_counts,
            "acs_2020_2024_block_group_estimate_sums": acs_counts,
            "comparison_between_vintages": "not_performed",
        }
    return totals


def _sample_worker(config: CensusSampleConfig, stage: Path, run_id: str) -> dict[str, Any]:
    started = datetime.now(UTC)
    report: dict[str, Any] = {
        "report_version": "census-sample-run-1",
        "run_id": run_id,
        "status": "running",
        "started_at_utc": started.isoformat(),
        "configuration": {
            "path": config.config_path.relative_to(config.repo_root).as_posix(),
            "sha256": sha256_file(config.config_path),
        },
        "code_identity": code_identity(),
        "environment": runtime_versions(),
        "specification_version": SPECIFICATION_VERSION,
        "normalization_version": NORMALIZATION_VERSION,
        "cache_snapshot_id": config.cache_snapshot_id,
        "dataset": DATASET_PATH,
        "geography": "block_group",
        "state_fips": STATE_FIPS,
        "county_fips": list(COUNTY_FIPS),
        "sources": {},
        "metadata": {},
        "acs_requests": {},
        "geometry": {},
        "joins": {},
        "variable_status_counts": {},
        "outputs": {},
        "diagnostics": [],
        "limitations": [
            "Experimental sample only; no indicator score or spatial allocation is produced.",
            "2020 block counts and 2020-2024 ACS estimates remain separate vintages and geographies.",
            "Published ACS MOEs are retained; uncertainty for later allocation or derived rates is not quantified.",
        ],
    }
    failure_error: Exception | None = None
    try:
        source_hashes = _validate_source_pins(config)
        catalog_check = _validate_local_catalog(config.sources["variables_catalog"])
        report["sources"] = {
            source_id: {
                "path": config.sources[source_id].relative_path,
                "sha256": source_hashes[source_id],
                "vintage": TIGER_VINTAGES.get(source_id, "unverified local catalog vintage"),
                "download_date": None,
                "download_receipt": "not supplied",
            }
            for source_id in config.sources
        }
        report["sources"]["variables_catalog"]["validation"] = catalog_check
        blocks, blocks_crs, blocks_report = _read_selected_geometries(config.sources["census_blocks"])
        groups, groups_crs, groups_report = _read_selected_geometries(config.sources["census_block_groups"])
        report["geometry"] = {
            "census_blocks_2020": blocks_report,
            "block_groups_2024": groups_report,
            "source_crs_match": groups_crs == blocks_crs,
        }
        if blocks_report["duplicate_geoid_count"]:
            raise CensusSampleError("2020 block source contains duplicate GEOIDs; see geometry diagnostics")
        if not report["geometry"]["source_crs_match"]:
            raise CensusSampleError("source Census layers do not have matching CRS identities")
        metadata_values, metadata_report = _fetch_metadata(config)
        report["metadata"] = metadata_report

        api_key = os.environ.get("CENSUS_API_KEY")
        acs_by_county: dict[str, list[dict[str, Any]]] = {}
        for county in COUNTY_FIPS:
            rows, request_report = _fetch_county_acs(config, county, api_key)
            acs_by_county[county] = rows
            report["acs_requests"][county] = request_report

        joined_by_county: dict[str, list[dict[str, Any]]] = {}
        for county in COUNTY_FIPS:
            county_groups = [row for row in groups if row["COUNTYFP"] == county]
            joined, join_report = join_acs_to_geometries(county_groups, acs_by_county[county], county)
            joined_by_county[county] = joined
            report["joins"][county] = join_report

        if not stage.is_dir() or any(item.name != "worker.log" for item in stage.iterdir()):
            raise CensusSampleError("Census sample staging directory has unexpected prior content")
        compact_blocks = [{key: value for key, value in row.items() if key != "geometry"} for row in blocks]
        _write_jsonl(stage / "blocks-2020.jsonl", compact_blocks)
        compact_joined = [
            {key: value for key, value in row.items() if key != "geometry"}
            for county in COUNTY_FIPS for row in joined_by_county[county]
        ]
        _write_jsonl(stage / "block-groups-2024-acs.jsonl", compact_joined)
        gpkg_blocks = _write_geopackage(stage / "blocks-2020.gpkg", blocks, blocks_crs, False, "census_blocks")
        all_joined = [row for county in COUNTY_FIPS for row in joined_by_county[county]]
        gpkg_groups = _write_geopackage(stage / "block-groups-2024-acs.gpkg", all_joined, groups_crs, True, "census_block_groups")
        report["outputs"] = {
            "blocks_2020": gpkg_blocks,
            "block_groups_2024_acs": gpkg_groups,
        }
        report["source_counts"] = {
            "blocks_2020": len(blocks),
            "block_groups_2024": len(groups),
            "acs_block_groups": sum(len(rows) for rows in acs_by_county.values()),
            "joined_block_groups": len(all_joined),
            "by_county": {
                county: {
                    "blocks_2020": sum(row["COUNTYFP20"] == county for row in blocks),
                    "block_groups_2024": sum(row["COUNTYFP"] == county for row in groups),
                    "acs_rows": len(acs_by_county[county]),
                    "joined_rows": len(joined_by_county[county]),
                }
                for county in COUNTY_FIPS
            },
        }
        report["source_totals_by_county"] = _source_totals(blocks, acs_by_county)
        report["variable_status_counts"] = _normalization_totals(acs_by_county)
        if _validate_source_pins(config) != source_hashes:
            raise CensusSampleError("a configured Census source changed while the worker was running")
        report["checks"] = {
            "all_source_hashes_match": True,
            "source_hashes_stable_during_run": True,
            "official_metadata_validated": set(metadata_values) == {"B01003", "B08201"},
            "both_county_queries_validated": set(report["acs_requests"]) == set(COUNTY_FIPS),
            "complete_one_to_one_joins": all(item["join_cardinality"] == "one_to_one" for item in report["joins"].values()),
            "source_and_joined_geopackages_reopened": True,
            "vintages_kept_separate": True,
        }
        report["attribution"] = {
            "source": "U.S. Census Bureau",
            "products": ["2020 Census tabulation blocks", "2024 TIGER/Line block groups", "2020-2024 ACS five-year Detailed Tables"],
            "citation_and_no_warranty_notice": "Preserve Census suggested citation and no-warranty notice in any later distribution.",
            "public_or_client_redistribution": "not_authorized_by_this_prototype_run",
        }
        if not report["geometry"]["source_crs_match"]:
            raise CensusSampleError("source Census layers do not have matching CRS identities")
        if any(not value for value in report["checks"].values()):
            raise CensusSampleError("one or more Census sample acceptance checks failed")
        report["status"] = "complete"
    except Exception as error:
        report["status"] = "fail"
        report["diagnostics"].append(str(error))
        if isinstance(error, CensusJoinError):
            report.setdefault("join_failures", {})[str(error.report["county_fips"])] = error.report
        failure_error = error
    finally:
        report["finished_at_utc"] = datetime.now(UTC).isoformat()
        report["duration_seconds"] = round((datetime.now(UTC) - started).total_seconds(), 3)
    if failure_error is not None:
        if stage.exists():
            _write_json(stage / "worker-report.json", report)
        raise CensusSampleError(str(failure_error)) from None
    report["outputs"]["files"] = {
        path.name: {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in sorted(stage.iterdir()) if path.is_file() and path.name != "worker-report.json"
    }
    _write_json(stage / "worker-report.json", report)
    return report


def census_sample_worker(config_path: Path, stage: Path, result_path: Path, run_id: str) -> int:
    """Supervised child entry point. Its result and logs contain no request URL key."""
    try:
        config = load_census_config(config_path)
        result = _sample_worker(config, stage, run_id)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(result_path, {"status": result["status"], "report": result})
        return 0 if result["status"] == "complete" else 1
    except Exception as error:
        safe_message = str(error)
        key = os.environ.get("CENSUS_API_KEY")
        if key:
            safe_message = safe_message.replace(key, "[REDACTED]")
        result_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(result_path, {"status": "fail", "error": safe_message})
        print(f"Census sample worker failed: {safe_message}", flush=True)
        return 1


def _secret_scan(directory: Path, api_key: str | None) -> None:
    if not api_key:
        return
    secret = api_key.encode("utf-8")
    if len(secret) < 8:
        raise CensusSampleError("CENSUS_API_KEY is unexpectedly short; refusing output promotion")
    for path in directory.rglob("*"):
        if path.is_file() and secret in path.read_bytes():
            raise CensusSampleError("Census API key appeared in a candidate output; promotion refused")


def run_census_sample(config_path: str | Path) -> tuple[int, dict[str, Any]]:
    """Run the source-pinned sample in a supervised worker and promote atomically."""
    import sys

    from .cli import _promote_directory, _supervise, _write_json

    config = load_census_config(config_path)
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    stage_root = config.repo_root / "data" / "staging" / "prototype" / "census-samples"
    stage = stage_root / run_id
    final_dir = config.output_root / run_id
    if stage.exists() or final_dir.exists():
        raise CensusSampleError(f"Refusing to reuse Census sample run ID {run_id}")
    stage.mkdir(parents=True, exist_ok=False)
    result_path = stage / "worker-result.json"
    worker_log = stage / "worker.log"
    command = [
        sys.executable, "-m", "flm_pipeline", "_census-worker",
        "--config", str(config.config_path), "--stage", str(stage),
        "--result", str(result_path), "--run-id", run_id,
    ]
    supervision = _supervise(command, config.repo_root, worker_log, config.timeout_seconds, config.rss_limit_bytes)
    if supervision.get("exit_code") != 0 or supervision.get("failure_reason") or not supervision.get("child_cleanup_complete"):
        worker_result = None
        if result_path.is_file():
            try:
                worker_result = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                worker_result = {"status": "fail", "error": "worker result could not be read"}
        diagnostics = worker_result.get("error") if isinstance(worker_result, dict) else None
        failure = {"status": "fail", "supervision": supervision, "reason": "worker failed, exceeded a limit, or left a child process", "worker_result": worker_result}
        _write_json(stage / "failure.json", failure)
        return 1, {"status": "fail", "run_id": run_id, "staging_directory": stage.relative_to(config.repo_root).as_posix(), "diagnostics": [diagnostics] if isinstance(diagnostics, str) else [], "supervision": supervision}
    promoted = False
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        report = result.get("report") if isinstance(result, dict) else None
        if not isinstance(report, dict) or result.get("status") != "complete" or report.get("status") != "complete":
            raise CensusSampleError("supervised Census worker did not produce a complete validated sample")
        if report.get("configuration", {}).get("sha256") != sha256_file(config.config_path):
            raise CensusSampleError("Census configuration changed while the worker was running")
        from .code_identity import code_identity

        if report.get("code_identity", {}).get("sha256") != code_identity().get("sha256"):
            raise CensusSampleError("Census ingestion code changed while the worker was running")
        _secret_scan(stage, os.environ.get("CENSUS_API_KEY"))
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        _promote_directory(stage, final_dir)
        promoted = True
        report["supervision"] = supervision
        report["cache_root"] = config.cache_relative_path
        report["final_directory"] = final_dir.relative_to(config.repo_root).as_posix()
        report["outputs"]["files"] = {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in sorted(final_dir.iterdir()) if path.is_file() and path.name not in {"run-report.json", "worker-report.json", "worker-result.json", "worker.log"}
        }
        report_path = final_dir / "run-report.json"
        _write_json(report_path, report)
        for extra in (final_dir / "worker-report.json", final_dir / "worker-result.json"):
            extra.unlink(missing_ok=True)
        return 0, {
            "status": "complete",
            "run_id": run_id,
            "output_directory": final_dir.relative_to(config.repo_root).as_posix(),
            "run_report": report_path.relative_to(config.repo_root).as_posix(),
            "counts": report["source_counts"],
            "supervision": supervision,
        }
    except (CensusSampleError, OSError, ValueError, json.JSONDecodeError) as error:
        failure_dir = final_dir if promoted else stage
        _write_json(failure_dir / "failure.json", {"status": "fail", "run_id": run_id, "reason": str(error), "supervision": supervision})
        return 1, {"status": "fail", "run_id": run_id, "staging_directory": failure_dir.relative_to(config.repo_root).as_posix(), "diagnostics": [str(error)], "supervision": supervision}

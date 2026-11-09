"""Strict loading and validation for the local prototype configuration."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
import tomllib
from typing import Any

class ConfigError(ValueError):
    """Raised when a configuration does not match the supported contract."""


@dataclass(frozen=True)
class SourceConfig:
    source_id: str
    path: Path
    relative_path: str
    expected_sha256: str | None


@dataclass(frozen=True)
class PipelineConfig:
    config_path: Path
    repo_root: Path
    config_version: str
    region_id: str
    sources: dict[str, SourceConfig]
    core_bbox: tuple[float, float, float, float]
    extract_bbox: tuple[float, float, float, float]
    expanded_bbox: tuple[float, float, float, float]
    station_lonlat: tuple[float, float]
    storage_crs: str
    inspection_crs: str
    length_method: str
    limit_seconds: int
    limit_rss_bytes: int
    output_root: Path
    output_relative_path: str


_TOP_LEVEL_KEYS = {
    "config_version",
    "region_id",
    "core_bbox",
    "extract_bbox",
    "expanded_bbox",
    "station_lonlat",
    "storage_crs",
    "inspection_crs",
    "length_method",
    "output_root",
    "limits",
    "sources",
}
_SOURCE_KEYS = {"path", "expected_sha256"}
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    extra = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if extra or missing:
        details = []
        if extra:
            details.append(f"unknown fields: {', '.join(extra)}")
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        raise ConfigError(f"{label}: {'; '.join(details)}")


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{label} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ConfigError(f"{label} must be finite")
    return result


def _bbox(value: Any, label: str) -> tuple[float, float, float, float]:
    if not isinstance(value, list) or len(value) != 4:
        raise ConfigError(f"{label} must contain west, south, east, north")
    west, south, east, north = (_number(item, label) for item in value)
    if not (-180 <= west <= 180 and -180 <= east <= 180):
        raise ConfigError(f"{label} longitude values must be within [-180, 180]")
    if not (-90 <= south <= 90 and -90 <= north <= 90):
        raise ConfigError(f"{label} latitude values must be within [-90, 90]")
    if west >= east or south >= north:
        raise ConfigError(f"{label} must have positive width and height")
    return west, south, east, north


def _point(value: Any, label: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ConfigError(f"{label} must contain longitude and latitude")
    longitude, latitude = (_number(item, label) for item in value)
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        raise ConfigError(f"{label} is outside longitude/latitude ranges")
    return longitude, latitude


def _contains(outer: tuple[float, float, float, float], inner: tuple[float, float, float, float]) -> bool:
    return outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]


def _relative_path(value: Any, label: str, repo_root: Path) -> tuple[Path, str]:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{label} must be a non-empty repository-relative path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ConfigError(f"{label} must stay within the repository")
    resolved = (repo_root / relative).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError as error:
        raise ConfigError(f"{label} resolves outside the repository") from error
    return resolved, relative.as_posix()


def load_config(config_path: str | Path) -> PipelineConfig:
    """Load a strict TOML config; paths are rooted at the repository checkout."""
    path = Path(config_path).resolve()
    if not path.is_file():
        raise ConfigError(f"Configuration file does not exist: {path}")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"Could not read TOML configuration: {error}") from error
    if not isinstance(raw, dict):
        raise ConfigError("Configuration root must be a TOML table")
    _keys(raw, _TOP_LEVEL_KEYS, "configuration")

    pipeline_dir = Path(__file__).resolve().parents[2]
    repo_root = pipeline_dir.parent.resolve()
    if raw["config_version"] != "prototype-config-1":
        raise ConfigError("config_version must be 'prototype-config-1'")
    for key in ("region_id", "storage_crs", "inspection_crs", "length_method"):
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise ConfigError(f"{key} must be a non-empty string")
    try:
        from pyproj import CRS
        from pyproj.exceptions import CRSError
    except ImportError as error:
        raise ConfigError("pyproj is required to validate CRS settings") from error
    for key in ("storage_crs", "inspection_crs"):
        try:
            CRS.from_user_input(raw[key])
        except (CRSError, TypeError, ValueError) as error:
            raise ConfigError(f"{key} is not a recognized CRS") from error
    if raw["length_method"] != "wgs84_ellipsoidal_geodesic_meters":
        raise ConfigError("unsupported length_method")

    limits = raw["limits"]
    if not isinstance(limits, dict):
        raise ConfigError("limits must be a table")
    _keys(limits, {"seconds", "rss_bytes"}, "limits")
    for key in ("seconds", "rss_bytes"):
        if isinstance(limits[key], bool) or not isinstance(limits[key], int) or limits[key] <= 0:
            raise ConfigError(f"limits.{key} must be a positive integer")

    core_bbox = _bbox(raw["core_bbox"], "core_bbox")
    extract_bbox = _bbox(raw["extract_bbox"], "extract_bbox")
    expanded_bbox = _bbox(raw["expanded_bbox"], "expanded_bbox")
    if not _contains(extract_bbox, core_bbox) or not _contains(expanded_bbox, extract_bbox):
        raise ConfigError("bboxes must be nested: core_bbox within extract_bbox within expanded_bbox")
    station_lonlat = _point(raw["station_lonlat"], "station_lonlat")
    if not (extract_bbox[0] <= station_lonlat[0] <= extract_bbox[2] and extract_bbox[1] <= station_lonlat[1] <= extract_bbox[3]):
        raise ConfigError("station_lonlat must be within extract_bbox")

    sources_raw = raw["sources"]
    required_sources = {"osm", "census_blocks", "census_block_groups"}
    allowed_sources = required_sources | {"variables_catalog"}
    if (
        not isinstance(sources_raw, dict)
        or not required_sources <= set(sources_raw)
        or not set(sources_raw) <= allowed_sources
    ):
        raise ConfigError("sources must define osm, census_blocks, and census_block_groups; variables_catalog is optional")
    sources: dict[str, SourceConfig] = {}
    for source_id, item in sources_raw.items():
        if not isinstance(item, dict):
            raise ConfigError(f"sources.{source_id} must be a table")
        _keys(item, _SOURCE_KEYS, f"sources.{source_id}")
        source_path, relative_path = _relative_path(item["path"], f"sources.{source_id}.path", repo_root)
        expected = item["expected_sha256"]
        if expected == "":
            expected = None
        if expected is not None and (not isinstance(expected, str) or not _SHA256.fullmatch(expected)):
            raise ConfigError(f"sources.{source_id}.expected_sha256 must be empty or a 64-character hex SHA-256")
        sources[source_id] = SourceConfig(source_id, source_path, relative_path, expected)

    output_path, output_relative = _relative_path(raw["output_root"], "output_root", repo_root)
    raw_root = (repo_root / "data" / "raw").resolve()
    if output_path == raw_root or raw_root in output_path.parents:
        raise ConfigError("output_root cannot be inside data/raw")
    for source in sources.values():
        if source.path == output_path or source.path in output_path.parents or output_path in source.path.parents:
            raise ConfigError(f"output_root collides with source path {source.relative_path}")

    return PipelineConfig(
        config_path=path,
        repo_root=repo_root,
        config_version=raw["config_version"],
        region_id=raw["region_id"],
        sources=sources,
        core_bbox=core_bbox,
        extract_bbox=extract_bbox,
        expanded_bbox=expanded_bbox,
        station_lonlat=station_lonlat,
        storage_crs=raw["storage_crs"],
        inspection_crs=raw["inspection_crs"],
        length_method=raw["length_method"],
        limit_seconds=limits["seconds"],
        limit_rss_bytes=limits["rss_bytes"],
        output_root=output_path,
        output_relative_path=output_relative,
    )


def validate_source_files(config: PipelineConfig) -> list[str]:
    """Return missing or invalid input paths without reading their contents."""
    errors = []
    for source in config.sources.values():
        if not source.path.is_file():
            errors.append(f"sources.{source.source_id} is missing: {source.relative_path}")
    return errors

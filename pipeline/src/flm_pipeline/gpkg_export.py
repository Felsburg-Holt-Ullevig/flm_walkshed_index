"""Export a validated regional source subset to an inspectable GeoPackage."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time
import uuid
from typing import Any

import geopandas as gpd
import pandas as pd
import pyogrio
from pyproj import CRS, Geod, Transformer
from shapely.geometry import LineString, Point, Polygon, box

from .code_identity import code_identity
from .config import ConfigError, PipelineConfig, load_config
from .extractor import sha256_file
from .runtime import environment_errors, runtime_versions


_CONTRACT_VERSION = "source-network-1"
_SELECTION_ID = "highway-node-in-bbox-complete-way-1"
_BATCH_SIZE = 5_000
_ID_CHARS = set("0123456789")
_SPATIAL_LAYERS = {"source_nodes", "source_ways", "source_segments", "coverage"}


class ExportFailure(RuntimeError):
    """An invalid extraction or GeoPackage export with useful diagnostics."""

    def __init__(self, message: str, diagnostics: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics or []


def _json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ExportFailure(f"Value cannot be represented as contract JSON: {error}") from error


def _json_text(value: Any) -> str:
    return _json_bytes(value).decode("utf-8")


def _numeric_key(osm_id: str) -> tuple[int, str]:
    return len(osm_id), osm_id


def _valid_id(value: Any, entity: str, line_number: int) -> str:
    if not isinstance(value, str) or not value or value[0] == "0" or any(char not in _ID_CHARS for char in value):
        raise ExportFailure(
            f"Invalid {entity} ID at line {line_number}: {value!r}",
            [{"entity_type": entity, "line": line_number, "osm_id": value, "reason": "ID must be a positive decimal string"}],
        )
    return value


def _tags(value: Any, entity: str, osm_id: str, line_number: int) -> dict[str, str]:
    if not isinstance(value, dict) or any(not isinstance(key, str) or not isinstance(tag_value, str) for key, tag_value in value.items()):
        raise ExportFailure(
            f"Malformed tags for {entity} {osm_id}",
            [{"entity_type": entity, "osm_id": osm_id, "line": line_number, "reason": "tags must map strings to strings"}],
        )
    return value


def _iter_jsonl(path: Path, entity: str, fields: set[str]) -> Iterator[dict[str, Any]]:
    previous: tuple[int, str] | None = None
    with path.open("rb") as stream:
        for line_number, raw_line in enumerate(stream, 1):
            try:
                record = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ExportFailure(
                    f"Malformed {entity} JSONL record at line {line_number}: {error}",
                    [{"entity_type": entity, "line": line_number, "reason": str(error)}],
                ) from error
            if not isinstance(record, dict) or set(record) != fields:
                raise ExportFailure(f"Unexpected fields for {entity} at line {line_number}")
            if raw_line != _json_bytes(record) + b"\n":
                raise ExportFailure(f"Noncanonical {entity} JSONL record at line {line_number}")
            osm_id = _valid_id(record["osm_id"], entity, line_number)
            key = _numeric_key(osm_id)
            if previous is not None and key <= previous:
                raise ExportFailure(f"{entity} records are not strictly sorted by numeric OSM ID at line {line_number}")
            previous = key
            record["osm_id"] = osm_id
            record["tags"] = _tags(record["tags"], entity, osm_id, line_number)
            if entity == "node":
                lon, lat = record["lon"], record["lat"]
                if (
                    isinstance(lon, bool)
                    or isinstance(lat, bool)
                    or not isinstance(lon, (int, float))
                    or not isinstance(lat, (int, float))
                    or not math.isfinite(lon)
                    or not math.isfinite(lat)
                    or not (-180 <= lon <= 180)
                    or not (-90 <= lat <= 90)
                ):
                    raise ExportFailure(
                        f"Invalid coordinates for node {osm_id}",
                        [{"entity_type": "node", "osm_id": osm_id, "line": line_number, "reason": "coordinates must be finite WGS84 longitude/latitude"}],
                    )
                record["lon"], record["lat"] = float(lon), float(lat)
            elif entity == "way":
                refs = record["node_refs"]
                if not isinstance(refs, list) or len(refs) < 2:
                    raise ExportFailure(
                        f"Way {osm_id} has fewer than two node references",
                        [{"entity_type": "way", "osm_id": osm_id, "line": line_number, "reason": "at least two ordered node references are required"}],
                    )
                record["node_refs"] = [_valid_id(ref, "way node reference", line_number) for ref in refs]
            else:
                members = record["members"]
                if not isinstance(members, list):
                    raise ExportFailure(f"Relation {osm_id} members must be an array")
                for member_index, member in enumerate(members):
                    if (
                        not isinstance(member, dict)
                        or set(member) != {"type", "ref", "role", "resolved"}
                        or member.get("type") not in {"node", "way", "relation"}
                        or not isinstance(member.get("role"), str)
                        or not isinstance(member.get("resolved"), bool)
                    ):
                        raise ExportFailure(f"Malformed member {member_index} on relation {osm_id}")
                    _valid_id(member["ref"], "relation member reference", line_number)
            yield record

def _validate_file_metadata(extraction_dir: Path, metadata: dict[str, Any]) -> None:
    files = metadata.get("files")
    expected_names = {"nodes.jsonl", "ways.jsonl", "relations.jsonl"}
    if not isinstance(files, dict) or set(files) != expected_names:
        raise ExportFailure("Extraction metadata does not list the three canonical JSONL files")
    for name in sorted(expected_names):
        path = extraction_dir / name
        record = files[name]
        if not isinstance(record, dict) or not path.is_file():
            raise ExportFailure(f"Extraction file is missing or has invalid metadata: {name}")
        actual_hash = sha256_file(path)
        if record.get("sha256") != actual_hash or record.get("semantic_sha256") != actual_hash:
            raise ExportFailure(f"Extraction file hash does not match metadata: {name}")
        if record.get("bytes") != path.stat().st_size:
            raise ExportFailure(f"Extraction file size does not match metadata: {name}")


def _validate_extraction(config: PipelineConfig, extraction_path: str | Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    directory = Path(extraction_path).resolve()
    try:
        directory.relative_to(config.output_root.resolve())
    except ValueError as error:
        raise ConfigError("Extraction directory must be inside the configured generated output root") from error
    if not directory.is_dir():
        raise ConfigError(f"Extraction directory does not exist: {directory}")
    metadata_path = directory / "extraction.json"
    report_path = directory / "run-report.json"
    manifest_path = directory / "code-manifest.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        extraction_report = json.loads(report_path.read_text(encoding="utf-8"))
        code_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExportFailure(f"Could not read extraction provenance files: {error}") from error
    if not isinstance(metadata, dict) or metadata.get("contract_version") != _CONTRACT_VERSION:
        raise ExportFailure(f"Extraction must use contract_version {_CONTRACT_VERSION}")
    if metadata.get("selection_id") != _SELECTION_ID:
        raise ExportFailure("Extraction selection_id is unsupported")
    if metadata.get("status") not in {"pass", "empty"}:
        raise ExportFailure("Extraction status must be pass or explicit empty")
    if not isinstance(extraction_report, dict) or extraction_report.get("status") != metadata["status"]:
        raise ExportFailure("Extraction run report status does not match extraction metadata")
    if extraction_report.get("run_id") != metadata.get("run_id"):
        raise ExportFailure("Extraction run report ID does not match extraction metadata")

    identity = code_identity()
    identity_record = metadata.get("code_identity")
    if not isinstance(identity_record, dict) or identity_record.get("sha256") != identity["sha256"]:
        raise ExportFailure("Extraction code identity is stale; regenerate the extraction with the current pipeline")
    report_identity = extraction_report.get("code_identity")
    if not isinstance(report_identity, dict) or (
        report_identity.get("algorithm") != identity_record.get("algorithm")
        or report_identity.get("sha256") != identity_record.get("sha256")
    ):
        raise ExportFailure("Extraction run report code identity does not match extraction metadata")
    if code_manifest != {"algorithm": identity["algorithm"], "files": identity["manifest"]}:
        raise ExportFailure("Extraction code manifest does not match its code identity")

    config_hash = sha256_file(config.config_path)
    config_rel = config.config_path.relative_to(config.repo_root).as_posix()
    configuration = metadata.get("configuration")
    report_configuration = extraction_report.get("configuration")
    if configuration != {"path": config_rel, "sha256": config_hash} or report_configuration != configuration:
        raise ExportFailure("Extraction configuration path or hash does not match the current configuration")
    if metadata.get("region_id") != config.region_id:
        raise ExportFailure("Extraction region_id does not match the current configuration")
    coverage = metadata.get("coverage")
    if not isinstance(coverage, dict) or (
        coverage.get("core_bbox") != list(config.core_bbox)
        or coverage.get("extract_bbox") != list(config.extract_bbox)
        or coverage.get("expanded_comparison_bbox") != list(config.expanded_bbox)
        or coverage.get("crs") != config.storage_crs
    ):
        raise ExportFailure("Extraction coverage metadata does not match the current configuration")
    inspection = metadata.get("inspection")
    if inspection != {"crs": config.inspection_crs, "length_method": config.length_method}:
        raise ExportFailure("Extraction inspection CRS or length method does not match the current configuration")
    if not CRS.from_user_input(config.storage_crs).equals(CRS.from_epsg(4326)):
        raise ExportFailure("source-network-1 GeoPackage layers require storage CRS EPSG:4326")
    if not CRS.from_user_input(config.inspection_crs).equals(CRS.from_epsg(26913)):
        raise ExportFailure("source-network-1 projected diagnostic lengths require EPSG:26913")
    if config.length_method != "wgs84_ellipsoidal_geodesic_meters":
        raise ExportFailure("Unsupported length method")

    source = metadata.get("source")
    configured_source = config.sources["osm"]
    if (
        not isinstance(source, dict)
        or source.get("source_id") != "osm"
        or source.get("path") != configured_source.relative_path
        or source.get("expected_sha256") != configured_source.expected_sha256
        or configured_source.expected_sha256 is None
    ):
        raise ExportFailure("Export requires an extraction linked to the currently configured, pinned OSM source")
    if not configured_source.path.is_file():
        raise ExportFailure(f"Configured OSM source is missing: {configured_source.relative_path}")
    source_hash = sha256_file(configured_source.path)
    if source_hash != source.get("sha256") or source_hash.casefold() != configured_source.expected_sha256.casefold():
        raise ExportFailure("Configured OSM source hash does not match extraction provenance")
    if configured_source.path.stat().st_size != source.get("bytes"):
        raise ExportFailure("Configured OSM source byte size does not match extraction provenance")

    counts = metadata.get("counts")
    if not isinstance(counts, dict):
        raise ExportFailure("Extraction metadata has no counts object")
    for name, field in (("nodes.jsonl", "emitted_nodes"), ("ways.jsonl", "selected_ways"), ("relations.jsonl", "emitted_relations")):
        if counts.get(field) != metadata["files"][name].get("count"):
            raise ExportFailure(f"Extraction count {field} does not match {name}")
        if extraction_report.get("output_hashes", {}).get(name) != metadata["files"][name].get("sha256"):
            raise ExportFailure(f"Extraction run report hash does not match {name}")
    if (metadata["status"] == "empty") != (counts.get("selected_ways") == 0):
        raise ExportFailure("Extraction empty status does not match selected-way count")
    if extraction_report.get("output_hashes", {}).get("extraction.json") != sha256_file(metadata_path):
        raise ExportFailure("Extraction run report hash does not match extraction.json")
    if extraction_report.get("source_inventory_sha256") != metadata.get("accepted_source_inventory", {}).get("sha256"):
        raise ExportFailure("Extraction run report inventory hash does not match extraction metadata")
    _validate_file_metadata(directory, metadata)
    return directory, metadata, identity


def _inside(lon: float, lat: float, bbox: tuple[float, float, float, float]) -> int:
    west, south, east, north = bbox
    return int(west <= lon <= east and south <= lat <= north)


def _coordinates(geometry: Any) -> list[list[float]] | list[float]:
    if isinstance(geometry, Point):
        return [float(geometry.x), float(geometry.y)]
    if isinstance(geometry, LineString):
        return [[float(x), float(y)] for x, y in geometry.coords]
    if isinstance(geometry, Polygon):
        return [[float(x), float(y)] for x, y in geometry.exterior.coords]
    raise ExportFailure(f"Unsupported output geometry type: {geometry.geom_type}")


def _geometry_fingerprint(coordinates: list[tuple[float, float]]) -> str:
    forward = tuple(coordinates)
    reverse = tuple(reversed(forward))
    canonical = min(forward, reverse)
    return hashlib.sha256(_json_bytes(canonical)).hexdigest()


class _LayerWriter:
    def __init__(self, path: Path, name: str, columns: dict[str, str], geometry_type: str, crs: str = "EPSG:4326") -> None:
        self.path = path
        self.name = name
        self.columns = columns
        self.geometry_type = geometry_type
        self.crs = crs
        self.count = 0
        self.digest = hashlib.sha256()
        self.started = False

    def _write(self, records: list[dict[str, Any]]) -> None:
        if records:
            frame = gpd.GeoDataFrame(records, geometry="geometry", crs=self.crs)
        else:
            frame_data = {name: pd.Series(dtype=dtype) for name, dtype in self.columns.items()}
            frame_data["geometry"] = gpd.GeoSeries([], dtype="geometry", crs=self.crs)
            frame = gpd.GeoDataFrame(frame_data, geometry="geometry", crs=self.crs)
        pyogrio.write_dataframe(
            frame,
            self.path,
            layer=self.name,
            driver="GPKG",
            geometry_type=self.geometry_type,
            append=self.path.exists(),
        )
        self.started = True

    def add(self, record: dict[str, Any]) -> None:
        geometry = record["geometry"]
        semantic = {key: value for key, value in record.items() if key != "geometry"}
        semantic["geometry"] = _coordinates(geometry)
        self.digest.update(_json_bytes(semantic) + b"\n")
        self._write([record])
        self.count += 1

    def add_batch(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        for record in records:
            geometry = record["geometry"]
            semantic = {key: value for key, value in record.items() if key != "geometry"}
            semantic["geometry"] = _coordinates(geometry)
            self.digest.update(_json_bytes(semantic) + b"\n")
        self._write(records)
        self.count += len(records)

    def finish(self) -> None:
        if not self.started:
            self._write([])

    @property
    def semantic_sha256(self) -> str:
        return self.digest.hexdigest()


class _TableWriter:
    def __init__(self, path: Path, name: str, columns: dict[str, str]) -> None:
        self.path, self.name, self.columns = path, name, columns
        self.count = 0
        self.digest = hashlib.sha256()
        self.started = False

    def add_batch(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        for record in records:
            self.digest.update(_json_bytes(record) + b"\n")
        frame = pd.DataFrame(records, columns=list(self.columns))
        pyogrio.write_dataframe(frame, self.path, layer=self.name, driver="GPKG", append=self.path.exists())
        self.started = True
        self.count += len(records)

    def finish(self) -> None:
        if not self.started:
            frame = pd.DataFrame({name: pd.Series(dtype=dtype) for name, dtype in self.columns.items()})
            pyogrio.write_dataframe(frame, self.path, layer=self.name, driver="GPKG", append=self.path.exists())
            self.started = True

    @property
    def semantic_sha256(self) -> str:
        return self.digest.hexdigest()


def _put_geometry_key(connection: sqlite3.Connection, kind: str, fingerprint: str, feature_id: str) -> bool:
    inserted = connection.execute(
        "INSERT OR IGNORE INTO geometry_seen (kind, fingerprint, first_id, occurrences) VALUES (?, ?, ?, 1)",
        (kind, fingerprint, feature_id),
    ).rowcount
    if inserted:
        return False
    connection.execute("UPDATE geometry_seen SET occurrences = occurrences + 1 WHERE kind = ? AND fingerprint = ?", (kind, fingerprint))
    return True


def _read_nodes(connection: sqlite3.Connection, path: Path, gpkg: Path, core_bbox: tuple[float, float, float, float], extract_bbox: tuple[float, float, float, float]) -> _LayerWriter:
    writer = _LayerWriter(gpkg, "source_nodes", {"osm_id": "object", "lon": "float64", "lat": "float64", "tags_json": "object", "inside_core": "int64", "inside_extract": "int64"}, "Point")
    batch: list[dict[str, Any]] = []
    try:
        connection.execute("BEGIN")
        for line_number, record in enumerate(_iter_jsonl(path, "node", {"osm_id", "lon", "lat", "tags"}), 1):
            osm_id, lon, lat = record["osm_id"], record["lon"], record["lat"]
            try:
                connection.execute("INSERT INTO nodes (osm_id, lon, lat) VALUES (?, ?, ?)", (osm_id, lon, lat))
            except sqlite3.IntegrityError as error:
                raise ExportFailure(f"Duplicate source node ID {osm_id}", [{"entity_type": "node", "osm_id": osm_id, "line": line_number, "reason": "duplicate identifier"}]) from error
            batch.append({
                "osm_id": osm_id,
                "lon": lon,
                "lat": lat,
                "tags_json": _json_text(record["tags"]),
                "inside_core": _inside(lon, lat, core_bbox),
                "inside_extract": _inside(lon, lat, extract_bbox),
                "geometry": Point(lon, lat),
            })
            if len(batch) >= _BATCH_SIZE:
                writer.add_batch(batch)
                connection.commit()
                connection.execute("BEGIN")
                batch = []
        if batch:
            writer.add_batch(batch)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    writer.finish()
    return writer


def _fetch_node(connection: sqlite3.Connection, way_id: str, sequence: int, node_id: str) -> tuple[float, float]:
    row = connection.execute("SELECT lon, lat FROM nodes WHERE osm_id = ?", (node_id,)).fetchone()
    if row is None:
        raise ExportFailure(
            f"Way {way_id} references missing emitted node {node_id} at sequence {sequence}",
            [{"entity_type": "way", "osm_id": way_id, "sequence": sequence, "node_id": node_id, "reason": "endpoint reference is absent from source_nodes"}],
        )
    return float(row[0]), float(row[1])


def _read_ways_and_segments(
    connection: sqlite3.Connection,
    path: Path,
    gpkg: Path,
    geod: Geod,
    transformer: Transformer,
    diagnostics: dict[str, Any],
) -> tuple[_LayerWriter, _LayerWriter, int, int]:
    ways_writer = _LayerWriter(gpkg, "source_ways", {"osm_id": "object", "node_refs_json": "object", "tags_json": "object", "node_count": "int64"}, "LineString")
    segments_writer = _LayerWriter(
        gpkg,
        "source_segments",
        {"segment_id": "object", "way_id": "object", "from_node_id": "object", "to_node_id": "object", "sequence": "int64", "tags_json": "object", "length_geodesic_m": "float64", "length_projected_m": "float64", "zero_length": "int64"},
        "LineString",
    )
    way_batch: list[dict[str, Any]] = []
    segment_batch: list[dict[str, Any]] = []
    total_refs = repeated_refs = zero_segments = 0
    diagnostics["repeated_way_node_reference_examples"] = []
    diagnostics["zero_length_segment_examples"] = []
    diagnostics["degenerate_geometry_count"] = 0
    diagnostics["degenerate_geometry_examples"] = []
    diagnostics["duplicate_geometries"] = {
        "source_ways": {"duplicate_feature_count": 0, "duplicate_group_count": 0, "examples": []},
        "source_segments": {"duplicate_feature_count": 0, "duplicate_group_count": 0, "examples": []},
    }
    try:
        for line_number, record in enumerate(_iter_jsonl(path, "way", {"osm_id", "node_refs", "tags"}), 1):
            way_id, refs = record["osm_id"], record["node_refs"]
            coordinates: list[tuple[float, float]] = []
            seen_refs: set[str] = set()
            tags_json = _json_text(record["tags"])
            for sequence, node_id in enumerate(refs):
                if node_id in seen_refs:
                    repeated_refs += 1
                    if len(diagnostics["repeated_way_node_reference_examples"]) < 20:
                        diagnostics["repeated_way_node_reference_examples"].append({"way_id": way_id, "node_id": node_id, "sequence": sequence})
                seen_refs.add(node_id)
                coordinates.append(_fetch_node(connection, way_id, sequence, node_id))
            if len(coordinates) != len(refs) or len(coordinates) < 2:
                raise ExportFailure(f"Way {way_id} coordinate/reference count is invalid")
            way_geometry = LineString(coordinates)
            if way_geometry.is_empty:
                raise ExportFailure(f"Way {way_id} produced an empty LineString")
            if not way_geometry.is_valid:
                diagnostics["degenerate_geometry_count"] += 1
                if len(diagnostics["degenerate_geometry_examples"]) < 20:
                    diagnostics["degenerate_geometry_examples"].append({"layer": "source_ways", "feature_id": way_id})
            fingerprint = _geometry_fingerprint(coordinates)
            if _put_geometry_key(connection, "source_ways", fingerprint, way_id):
                summary = diagnostics["duplicate_geometries"]["source_ways"]
                summary["duplicate_feature_count"] += 1
                if len(summary["examples"]) < 20:
                    summary["examples"].append({"first_id": connection.execute("SELECT first_id FROM geometry_seen WHERE kind = 'source_ways' AND fingerprint = ?", (fingerprint,)).fetchone()[0], "duplicate_id": way_id})
            way_batch.append({"osm_id": way_id, "node_refs_json": _json_text(refs), "tags_json": tags_json, "node_count": len(refs), "geometry": way_geometry})
            total_refs += len(refs)

            for sequence, (from_id, to_id, start, end) in enumerate(zip(refs, refs[1:], coordinates, coordinates[1:])):
                segment_id = f"way/{way_id}/segment/{sequence}"
                geometry = LineString([start, end])
                if geometry.is_empty:
                    raise ExportFailure(f"Segment {segment_id} produced an empty LineString")
                if not geometry.is_valid:
                    diagnostics["degenerate_geometry_count"] += 1
                    if len(diagnostics["degenerate_geometry_examples"]) < 20:
                        diagnostics["degenerate_geometry_examples"].append({"layer": "source_segments", "feature_id": segment_id})
                _, _, geodesic_length = geod.inv(start[0], start[1], end[0], end[1])
                x1, y1 = transformer.transform(start[0], start[1], errcheck=True)
                x2, y2 = transformer.transform(end[0], end[1], errcheck=True)
                projected_length = math.hypot(x2 - x1, y2 - y1)
                if not all(math.isfinite(value) for value in (geodesic_length, projected_length)):
                    raise ExportFailure(
                        f"Nonfinite segment length for {segment_id}",
                        [{"entity_type": "segment", "segment_id": segment_id, "reason": "computed length is not finite"}],
                    )
                zero_length = int(geodesic_length == 0.0)
                if zero_length:
                    zero_segments += 1
                    if len(diagnostics["zero_length_segment_examples"]) < 20:
                        diagnostics["zero_length_segment_examples"].append({"segment_id": segment_id, "from_node_id": from_id, "to_node_id": to_id})
                segment_fingerprint = _geometry_fingerprint([start, end])
                if _put_geometry_key(connection, "source_segments", segment_fingerprint, segment_id):
                    summary = diagnostics["duplicate_geometries"]["source_segments"]
                    summary["duplicate_feature_count"] += 1
                    if len(summary["examples"]) < 20:
                        first_id = connection.execute("SELECT first_id FROM geometry_seen WHERE kind = 'source_segments' AND fingerprint = ?", (segment_fingerprint,)).fetchone()[0]
                        summary["examples"].append({"first_id": first_id, "duplicate_id": segment_id})
                segment_batch.append({
                    "segment_id": segment_id,
                    "way_id": way_id,
                    "from_node_id": from_id,
                    "to_node_id": to_id,
                    "sequence": sequence,
                    "tags_json": tags_json,
                    "length_geodesic_m": float(geodesic_length),
                    "length_projected_m": float(projected_length),
                    "zero_length": zero_length,
                    "geometry": geometry,
                })
                if len(segment_batch) >= _BATCH_SIZE:
                    segments_writer.add_batch(segment_batch)
                    segment_batch = []
            if len(way_batch) >= _BATCH_SIZE:
                ways_writer.add_batch(way_batch)
                way_batch = []
        ways_writer.add_batch(way_batch)
        segments_writer.add_batch(segment_batch)
    except Exception:
        connection.rollback()
        raise
    ways_writer.finish()
    segments_writer.finish()
    for kind, summary in diagnostics["duplicate_geometries"].items():
        row = connection.execute("SELECT COUNT(*), COALESCE(SUM(occurrences - 1), 0) FROM geometry_seen WHERE kind = ? AND occurrences > 1", (kind,)).fetchone()
        summary["duplicate_group_count"], summary["duplicate_feature_count"] = int(row[0]), int(row[1])
    diagnostics["repeated_way_node_reference_count"] = repeated_refs
    diagnostics["zero_length_segment_count"] = zero_segments
    return ways_writer, segments_writer, total_refs, repeated_refs


def _read_relations(path: Path, gpkg: Path) -> _TableWriter:
    writer = _TableWriter(gpkg, "source_relations", {"osm_id": "object", "members_json": "object", "tags_json": "object"})
    batch: list[dict[str, Any]] = []
    for line_number, record in enumerate(_iter_jsonl(path, "relation", {"osm_id", "members", "tags"}), 1):
        for member_index, member in enumerate(record["members"]):
            _valid_id(member["ref"], "relation member reference", line_number)
        batch.append({"osm_id": record["osm_id"], "members_json": _json_text(record["members"]), "tags_json": _json_text(record["tags"])})
        if len(batch) >= _BATCH_SIZE:
            writer.add_batch(batch)
            batch = []
    writer.add_batch(batch)
    writer.finish()
    return writer


def _read_coverage(gpkg: Path, metadata: dict[str, Any]) -> _LayerWriter:
    boxes = metadata["coverage"]
    rows = []
    for coverage_kind, key in (("core", "core_bbox"), ("extract", "extract_bbox"), ("expanded_comparison", "expanded_comparison_bbox")):
        west, south, east, north = boxes[key]
        rows.append({"coverage_kind": coverage_kind, "selection_id": metadata["selection_id"], "geometry": box(west, south, east, north)})
    writer = _LayerWriter(gpkg, "coverage", {"coverage_kind": "object", "selection_id": "object"}, "Polygon")
    writer.add_batch(rows)
    writer.finish()
    return writer


def _create_unique_indexes(gpkg_path: Path) -> None:
    indexes = {
        "source_nodes": "osm_id",
        "source_ways": "osm_id",
        "source_segments": "segment_id",
        "source_relations": "osm_id",
        "coverage": "coverage_kind",
    }
    with sqlite3.connect(gpkg_path) as connection:
        for layer, field in indexes.items():
            connection.execute(f'CREATE UNIQUE INDEX "uq_{layer}_{field}" ON "{layer}" ("{field}")')
        check = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise ExportFailure(f"GeoPackage SQLite integrity check failed: {check}")


def _close_enough(actual: float, expected: float, tolerance: float) -> bool:
    return math.isfinite(float(actual)) and abs(float(actual) - expected) <= tolerance


def _actual_rows(gpkg: Path, layer: str, spatial: bool, expected_crs: str | None = None) -> Iterator[pd.DataFrame]:
    offset = 0
    while True:
        frame = pyogrio.read_dataframe(gpkg, layer=layer, read_geometry=spatial, skip_features=offset, max_features=_BATCH_SIZE)
        if spatial:
            if frame.crs is None or not CRS.from_user_input(frame.crs).equals(CRS.from_user_input(expected_crs or "EPSG:4326")):
                raise ExportFailure(f"GeoPackage layer {layer} CRS does not round-trip as {expected_crs or 'EPSG:4326'}")
        if frame.empty:
            break
        offset += len(frame)
        yield frame


def _expected_nodes(path: Path, core_bbox: tuple[float, float, float, float], extract_bbox: tuple[float, float, float, float]) -> Iterator[dict[str, Any]]:
    for record in _iter_jsonl(path, "node", {"osm_id", "lon", "lat", "tags"}):
        lon, lat = float(record["lon"]), float(record["lat"])
        yield {"osm_id": record["osm_id"], "lon": lon, "lat": lat, "tags_json": _json_text(record["tags"]), "inside_core": _inside(lon, lat, core_bbox), "inside_extract": _inside(lon, lat, extract_bbox), "geometry": Point(lon, lat)}


def _expected_ways(path: Path, connection: sqlite3.Connection) -> Iterator[dict[str, Any]]:
    for record in _iter_jsonl(path, "way", {"osm_id", "node_refs", "tags"}):
        coordinates = [_fetch_node(connection, record["osm_id"], sequence, node_id) for sequence, node_id in enumerate(record["node_refs"])]
        yield {"osm_id": record["osm_id"], "node_refs_json": _json_text(record["node_refs"]), "tags_json": _json_text(record["tags"]), "node_count": len(coordinates), "geometry": LineString(coordinates)}


def _expected_segments(path: Path, connection: sqlite3.Connection, geod: Geod, transformer: Transformer) -> Iterator[dict[str, Any]]:
    for record in _iter_jsonl(path, "way", {"osm_id", "node_refs", "tags"}):
        refs = record["node_refs"]
        coordinates = [_fetch_node(connection, record["osm_id"], sequence, node_id) for sequence, node_id in enumerate(refs)]
        tags_json = _json_text(record["tags"])
        for sequence, (from_id, to_id, start, end) in enumerate(zip(refs, refs[1:], coordinates, coordinates[1:])):
            _, _, geodesic_length = geod.inv(start[0], start[1], end[0], end[1])
            x1, y1 = transformer.transform(start[0], start[1], errcheck=True)
            x2, y2 = transformer.transform(end[0], end[1], errcheck=True)
            projected_length = math.hypot(x2 - x1, y2 - y1)
            yield {
                "segment_id": f"way/{record['osm_id']}/segment/{sequence}",
                "way_id": record["osm_id"],
                "from_node_id": from_id,
                "to_node_id": to_id,
                "sequence": sequence,
                "tags_json": tags_json,
                "length_geodesic_m": float(geodesic_length),
                "length_projected_m": float(projected_length),
                "zero_length": int(geodesic_length == 0.0),
                "geometry": LineString([start, end]),
            }


def _expected_relations(path: Path) -> Iterator[dict[str, Any]]:
    for record in _iter_jsonl(path, "relation", {"osm_id", "members", "tags"}):
        yield {"osm_id": record["osm_id"], "members_json": _json_text(record["members"]), "tags_json": _json_text(record["tags"])}


def _expected_coverage(metadata: dict[str, Any]) -> Iterator[dict[str, Any]]:
    coverage = metadata["coverage"]
    for kind, key in (("core", "core_bbox"), ("extract", "extract_bbox"), ("expanded_comparison", "expanded_comparison_bbox")):
        west, south, east, north = coverage[key]
        yield {"coverage_kind": kind, "selection_id": metadata["selection_id"], "geometry": box(west, south, east, north)}


def _verify_layer(
    gpkg: Path,
    layer: str,
    expected: Iterable[dict[str, Any]],
    *,
    spatial: bool,
    geometry_type: str | None = None,
    float_fields: set[str] | None = None,
) -> int:
    expected_iterator = iter(expected)
    actual_iterator = (row for frame in _actual_rows(gpkg, layer, spatial) for _, row in frame.iterrows())
    count = 0
    float_fields = float_fields or set()
    while True:
        try:
            expected_row = next(expected_iterator)
        except StopIteration:
            expected_row = None
        try:
            actual_row = next(actual_iterator)
        except StopIteration:
            actual_row = None
        if expected_row is None and actual_row is None:
            break
        if expected_row is None or actual_row is None:
            raise ExportFailure(f"GeoPackage layer {layer} feature count does not match its source records")
        for field, value in expected_row.items():
            if field == "geometry":
                actual_geometry = actual_row.geometry
                if actual_geometry is None or actual_geometry.is_empty or actual_geometry.geom_type != geometry_type:
                    raise ExportFailure(f"GeoPackage layer {layer} geometry type/emptiness mismatch at row {count}")
                if geometry_type == "Point":
                    if not _close_enough(actual_geometry.x, value.x, 1e-9) or not _close_enough(actual_geometry.y, value.y, 1e-9):
                        raise ExportFailure(f"GeoPackage layer {layer} coordinate round-trip mismatch at row {count}")
                elif not actual_geometry.equals_exact(value, 1e-9):
                    raise ExportFailure(f"GeoPackage layer {layer} geometry sequence mismatch at row {count}")
            elif field in float_fields:
                tolerance = max(1e-6, 1e-9 * abs(float(value)))
                if not _close_enough(actual_row[field], float(value), tolerance):
                    raise ExportFailure(f"GeoPackage layer {layer} field {field} mismatch at row {count}")
            elif field in {"inside_core", "inside_extract", "node_count", "sequence", "zero_length"}:
                if int(actual_row[field]) != int(value):
                    raise ExportFailure(f"GeoPackage layer {layer} field {field} mismatch at row {count}")
            elif actual_row[field] != value:
                raise ExportFailure(f"GeoPackage layer {layer} field {field} mismatch at row {count}")
        count += 1
    return count


def _verify_gpkg(
    gpkg: Path,
    metadata: dict[str, Any],
    node_index: sqlite3.Connection,
    gpkg_sqlite: sqlite3.Connection,
    geod: Geod,
    transformer: Transformer,
) -> dict[str, int]:
    expected_layers = {"source_nodes", "source_ways", "source_segments", "source_relations", "coverage"}
    layer_info = pyogrio.list_layers(gpkg)
    actual_layers = {str(row[0]) for row in layer_info.tolist()}
    if actual_layers != expected_layers:
        raise ExportFailure(f"GeoPackage layers do not match the source-network contract: {sorted(actual_layers)}")
    geometry_by_layer = {str(row[0]): row[1] for row in layer_info.tolist()}
    expected_geometry = {"source_nodes": "Point", "source_ways": "LineString", "source_segments": "LineString", "coverage": "Polygon", "source_relations": None}
    if geometry_by_layer != expected_geometry:
        raise ExportFailure(f"GeoPackage geometry types do not match the contract: {geometry_by_layer}")
    extraction_dir = Path(metadata["_extraction_dir"])
    core_bbox = tuple(metadata["coverage"]["core_bbox"])
    extract_bbox = tuple(metadata["coverage"]["extract_bbox"])
    ways_path = extraction_dir / "ways.jsonl"
    counts = {
        "source_nodes": _verify_layer(gpkg, "source_nodes", _expected_nodes(extraction_dir / "nodes.jsonl", core_bbox, extract_bbox), spatial=True, geometry_type="Point"),
        "source_ways": _verify_layer(gpkg, "source_ways", _expected_ways(ways_path, node_index), spatial=True, geometry_type="LineString"),
        "source_segments": _verify_layer(gpkg, "source_segments", _expected_segments(ways_path, node_index, geod, transformer), spatial=True, geometry_type="LineString", float_fields={"length_geodesic_m", "length_projected_m"}),
        "source_relations": _verify_layer(gpkg, "source_relations", _expected_relations(extraction_dir / "relations.jsonl"), spatial=False),
        "coverage": _verify_layer(gpkg, "coverage", _expected_coverage(metadata), spatial=True, geometry_type="Polygon"),
    }
    for layer, count in counts.items():
        table_count = gpkg_sqlite.execute(f'SELECT COUNT(*) FROM "{layer}"').fetchone()[0]
        if table_count != count:
            raise ExportFailure(f"GeoPackage layer {layer} SQL count does not match reopened count")
    return counts


def _write_report(path: Path, report: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _promote(source: Path, destination: Path) -> None:
    for delay in (0.1, 0.25, 0.5, None):
        try:
            os.replace(source, destination)
            return
        except PermissionError as error:
            if getattr(error, "winerror", None) not in {5, 32} or delay is None:
                raise
            time.sleep(delay)


def _build_export(config_path: str | Path, extraction_path: str | Path, run_id: str, stage_dir: Path) -> tuple[int, dict[str, Any]]:
    """Create and validate a run-scoped source-network GeoPackage."""
    try:
        config = load_config(config_path)
        errors = environment_errors()
        if errors:
            return 1, {"status": "fail", "phase": "environment", "errors": errors}
        extraction_dir, metadata, identity = _validate_extraction(config, extraction_path)
    except (ConfigError, ExportFailure, OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        return 1, {"status": "fail", "phase": "preflight", "errors": [str(error)]}

    final_dir = config.output_root / run_id
    candidate_dir = stage_dir / "candidate"
    candidate_dir.mkdir()
    gpkg_path = candidate_dir / "source-network.gpkg"
    index_path = candidate_dir / "export-index.sqlite"
    started = time.monotonic()
    report: dict[str, Any] = {
        "report_version": "source-network-export-1",
        "status": "fail",
        "export_run_id": run_id,
        "extraction_run_id": metadata["run_id"],
        "contract_version": metadata["contract_version"],
        "selection_id": metadata["selection_id"],
        "region_id": config.region_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "code_identity": {"algorithm": identity["algorithm"], "sha256": identity["sha256"]},
        "configuration": {"path": config.config_path.relative_to(config.repo_root).as_posix(), "sha256": sha256_file(config.config_path)},
        "extraction_directory": extraction_dir.relative_to(config.repo_root).as_posix(),
        "extraction_metadata_sha256": sha256_file(extraction_dir / "extraction.json"),
        "source": {"path": metadata["source"]["path"], "bytes": metadata["source"]["bytes"], "sha256": metadata["source"]["sha256"]},
        "accepted_source_inventory_sha256": metadata["accepted_source_inventory"]["sha256"],
        "coverage": metadata["coverage"],
        "storage_crs": "EPSG:4326",
        "inspection_crs": config.inspection_crs,
        "length_method": config.length_method,
        "environment": runtime_versions(),
        "input_hashes": {name: record["sha256"] for name, record in metadata["files"].items()},
        "extraction_counts": metadata["counts"],
        "output": {"path": (final_dir / "source-network.gpkg").relative_to(config.repo_root).as_posix()},
        "counts": {},
        "diagnostics": {},
        "checks": {},
        "limitations": [
            "The GeoPackage preserves source evidence; it does not classify pedestrian eligibility or establish routing completeness.",
            "Duplicate geometries are detected by exact coordinate sequences with reversal treated as equivalent; near-overlaps are not classified as duplicates.",
            "Projected segment lengths are EPSG:26913 diagnostics; geodesic lengths use the WGS84 ellipsoid.",
        ],
    }
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(index_path)
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA cache_size=-32768")
        connection.execute("PRAGMA temp_store=FILE")
        connection.executescript(
            "CREATE TABLE nodes (osm_id TEXT PRIMARY KEY, lon REAL NOT NULL, lat REAL NOT NULL) WITHOUT ROWID;"
            "CREATE TABLE geometry_seen (kind TEXT NOT NULL, fingerprint TEXT NOT NULL, first_id TEXT NOT NULL, occurrences INTEGER NOT NULL, PRIMARY KEY(kind, fingerprint)) WITHOUT ROWID;"
        )
        core_bbox = tuple(config.core_bbox)
        extract_bbox = tuple(config.extract_bbox)
        node_writer = _read_nodes(connection, extraction_dir / "nodes.jsonl", gpkg_path, core_bbox, extract_bbox)
        geod = Geod(ellps="WGS84")
        transformer = Transformer.from_crs("EPSG:4326", config.inspection_crs, always_xy=True)
        diagnostics: dict[str, Any] = {}
        way_writer, segment_writer, total_refs, repeated_refs = _read_ways_and_segments(
            connection, extraction_dir / "ways.jsonl", gpkg_path, geod, transformer, diagnostics
        )
        relation_writer = _read_relations(extraction_dir / "relations.jsonl", gpkg_path)
        coverage_writer = _read_coverage(gpkg_path, metadata)
        _create_unique_indexes(gpkg_path)
        # Keep provenance paths out of the accepted extraction metadata; they are local export-run state only.
        metadata_for_verify = dict(metadata)
        metadata_for_verify["_extraction_dir"] = str(extraction_dir)
        gpkg_sqlite = sqlite3.connect(gpkg_path)
        try:
            output_counts = _verify_gpkg(gpkg_path, metadata_for_verify, connection, gpkg_sqlite, geod, transformer)
        finally:
            gpkg_sqlite.close()
        _validate_file_metadata(extraction_dir, metadata)
        if sha256_file(config.sources["osm"].path) != metadata["source"]["sha256"]:
            raise ExportFailure("Configured OSM source changed while GeoPackage export was running")
        if sha256_file(config.config_path) != report["configuration"]["sha256"]:
            raise ExportFailure("Configuration changed while GeoPackage export was running")
        if code_identity()["sha256"] != identity["sha256"]:
            raise ExportFailure("Pipeline code changed while GeoPackage export was running")
        if sha256_file(extraction_dir / "extraction.json") != report["extraction_metadata_sha256"]:
            raise ExportFailure("Extraction metadata changed while GeoPackage export was running")
        metadata_counts = metadata["counts"]
        if total_refs != metadata_counts.get("complete_way_node_reference_total"):
            raise ExportFailure("Export way-reference total does not match extraction counts")
        expected_segments = total_refs - way_writer.count
        if segment_writer.count != expected_segments:
            raise ExportFailure("Export segment count is inconsistent with ordered way references")
        if output_counts["source_nodes"] != metadata_counts["emitted_nodes"] or output_counts["source_ways"] != metadata_counts["selected_ways"] or output_counts["source_relations"] != metadata_counts["emitted_relations"]:
            raise ExportFailure("GeoPackage counts do not reconcile to extraction counts")
        for kind, summary in diagnostics["duplicate_geometries"].items():
            summary["duplicate_group_count"] = int(connection.execute("SELECT COUNT(*) FROM geometry_seen WHERE kind = ? AND occurrences > 1", (kind,)).fetchone()[0])
        diagnostics["repeated_way_node_reference_count"] = repeated_refs
        report["counts"] = {
            **output_counts,
            "complete_way_node_reference_total": total_refs,
            "repeated_way_node_reference_count": repeated_refs,
            "zero_length_segment_count": diagnostics["zero_length_segment_count"],
            "duplicate_geometry_feature_count": sum(item["duplicate_feature_count"] for item in diagnostics["duplicate_geometries"].values()),
        }
        report["diagnostics"] = diagnostics
        report["semantic_layer_sha256"] = {
            "source_nodes": node_writer.semantic_sha256,
            "source_ways": way_writer.semantic_sha256,
            "source_segments": segment_writer.semantic_sha256,
            "source_relations": relation_writer.semantic_sha256,
            "coverage": coverage_writer.semantic_sha256,
        }
        report["checks"] = {
            "extraction_hashes_and_provenance_match": True,
            "coordinates_finite_and_in_range": True,
            "endpoint_references_resolve": True,
            "identifier_uniqueness_enforced": True,
            "ordered_way_geometry_preserved": True,
            "segment_direction_and_sequence_preserved": True,
            "crs_and_length_round_trip": True,
            "source_counts_reconciled": True,
            "all_geopackage_layers_reopened": True,
            "gpkg_integrity_check": True,
        }
        warnings = (
            repeated_refs > 0
            or diagnostics["zero_length_segment_count"] > 0
            or diagnostics["degenerate_geometry_count"] > 0
            or report["counts"]["duplicate_geometry_feature_count"] > 0
        )
        report["status"] = "empty" if metadata["status"] == "empty" else ("pass_with_warnings" if warnings else "pass")
        report["output"]["bytes"] = gpkg_path.stat().st_size
        report["output"]["sha256"] = sha256_file(gpkg_path)
        report["finished_at_utc"] = datetime.now(UTC).isoformat()
        report["duration_seconds"] = round(time.monotonic() - started, 3)
        report["output_directory"] = final_dir.relative_to(config.repo_root).as_posix()
        connection.close()
        connection = None
        index_path.unlink(missing_ok=True)
        _write_report(candidate_dir / "run-report.json", report)
        return (0 if report["status"] in {"pass", "pass_with_warnings", "empty"} else 1), {
            "status": report["status"],
            "export_run_id": run_id,
            "source_network_gpkg": gpkg_path.relative_to(config.repo_root).as_posix(),
            "run_report": (candidate_dir / "run-report.json").relative_to(config.repo_root).as_posix(),
            "counts": report["counts"],
            "diagnostics": report["diagnostics"],
            "semantic_layer_sha256": report["semantic_layer_sha256"],
        }
    except Exception as error:
        report["status"] = "fail"
        report["finished_at_utc"] = datetime.now(UTC).isoformat()
        report["duration_seconds"] = round(time.monotonic() - started, 3)
        report["diagnostics"] = {**report.get("diagnostics", {}), "failure": str(error), "details": getattr(error, "diagnostics", [])}
        try:
            _write_report(stage_dir / "run-report.json", report)
        except OSError:
            pass
        return 1, {
            "status": "fail",
            "export_run_id": run_id,
            "run_report": (stage_dir / "run-report.json").relative_to(config.repo_root).as_posix(),
            "errors": [str(error)],
        }
    finally:
        if connection is not None:
            connection.close()
        try:
            index_path.unlink(missing_ok=True)
        except OSError:
            pass


def export_worker(config_path: Path, extraction_path: Path, run_id: str, stage_dir: Path, result_path: Path) -> int:
    try:
        code, result = _build_export(config_path, extraction_path, run_id, stage_dir)
        _write_report(result_path, result)
        return code
    except Exception as error:
        _write_report(result_path, {"status": "fail", "errors": [str(error)]})
        return 1


def export_extraction(config_path: str | Path, extraction_path: str | Path) -> tuple[int, dict[str, Any]]:
    """Supervise construction/verification, then atomically promote the validated directory."""
    try:
        config = load_config(config_path)
        errors = environment_errors()
        if errors:
            return 1, {"status": "fail", "phase": "environment", "errors": errors}
    except (ConfigError, OSError, ValueError) as error:
        return 1, {"status": "fail", "phase": "preflight", "errors": [str(error)]}
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    stage_dir = config.repo_root / "data" / "staging" / "prototype" / run_id
    final_dir = config.output_root / run_id
    candidate = stage_dir / "candidate"
    if stage_dir.exists() or final_dir.exists():
        raise FileExistsError(f"Refusing to reuse export run directory: {run_id}")
    stage_dir.mkdir(parents=True)
    result_path = stage_dir / "worker-result.json"
    initial_identity = code_identity()["sha256"]
    initial_config_hash = sha256_file(config.config_path)
    command = [os.sys.executable, "-m", "flm_pipeline", "_export-worker", "--config", str(config.config_path), "--extraction", str(Path(extraction_path).resolve()), "--run-id", run_id, "--stage", str(stage_dir), "--result", str(result_path)]
    supervised = None
    result: dict[str, Any] = {}
    report: dict[str, Any] = {}
    promoted = False
    try:
        from .cli import _supervise
        supervised = _supervise(command, config.repo_root, stage_dir / "export-worker.log", config.limit_seconds, config.limit_rss_bytes)
        if result_path.is_file():
            result = json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(result, dict):
            result = {}
            raise ExportFailure("Export worker result must be a JSON object")
        if supervised["exit_code"] != 0 or supervised["failure_reason"] is not None or not supervised.get("child_cleanup_complete", False) or result.get("status") not in {"pass", "pass_with_warnings", "empty"}:
            worker_errors = result.get("errors", [])
            error_text = "; ".join(str(item) for item in worker_errors) if isinstance(worker_errors, list) else str(worker_errors)
            reason = supervised["failure_reason"] or error_text or f"Export worker failed or child cleanup incomplete (exit {supervised['exit_code']})"
            raise ExportFailure(reason)
        report_path = candidate / "run-report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            report = {}
            raise ExportFailure("Export worker report must be a JSON object")
        checks = report.get("checks")
        if report.get("report_version") != "source-network-export-1" or report.get("export_run_id") != run_id or report.get("status") != result["status"] or not isinstance(checks, dict) or not checks or not all(value is True for value in checks.values()):
            raise ExportFailure("Export worker report identity, status or checks are invalid")
        if report.get("code_identity", {}).get("sha256") != initial_identity or code_identity()["sha256"] != initial_identity or sha256_file(config.config_path) != initial_config_hash:
            raise ExportFailure("Code or configuration changed during GeoPackage export")
        if report.get("counts") != result.get("counts") or report.get("semantic_layer_sha256") != result.get("semantic_layer_sha256") or report.get("configuration", {}).get("sha256") != initial_config_hash:
            raise ExportFailure("Export result and candidate report provenance or counts disagree")
        if (candidate / "source-network.gpkg").stat().st_size != report["output"]["bytes"]:
            raise ExportFailure("Validated candidate GeoPackage size changed before promotion")
        report["worker"] = supervised
        report["resource_limits"] = {"timeout_seconds": config.limit_seconds, "rss_bytes": config.limit_rss_bytes, "scope": "worker preflight, construction, and verification; parent promotion/report I/O excluded"}
        report_path.unlink()
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        if final_dir.exists():
            raise FileExistsError(f"Refusing to replace export directory: {run_id}")
        _promote(candidate, final_dir)
        promoted = True
        _write_report(final_dir / "run-report.json", report)
        return 0, {**result, "source_network_gpkg": (final_dir / "source-network.gpkg").relative_to(config.repo_root).as_posix(), "run_report": (final_dir / "run-report.json").relative_to(config.repo_root).as_posix(), "worker": supervised}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ExportFailure) as error:
        if promoted and final_dir.exists():
            try:
                _promote(final_dir, candidate)
            except OSError as rollback_error:
                report["rollback_error"] = str(rollback_error)
        failed = {**report, "report_version": "source-network-export-1", "status": "fail", "export_run_id": run_id, "worker": supervised, "errors": [str(error)], "finished_at_utc": datetime.now(UTC).isoformat()}
        _write_report(stage_dir / "run-report.json", failed)
        return 1, {"status": "fail", "phase": result.get("phase", "worker_or_promotion"), "export_run_id": run_id, "run_report": (stage_dir / "run-report.json").relative_to(config.repo_root).as_posix(), "errors": [str(error)]}

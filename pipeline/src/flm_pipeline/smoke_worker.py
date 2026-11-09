"""Bounded reads of the local sample sources and a temporary GIS round-trip."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import zipfile
from typing import Any

import geopandas as gpd
import osmium
import pyogrio
from shapely.geometry.base import BaseGeometry

from .config import PipelineConfig
from .roundtrip import write_and_verify_roundtrip


SAMPLE_LIMIT = 20


def _pbf_header_and_samples(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    samples: dict[str, Any] = {}
    header_values: dict[str, Any] = {}
    entity_types = (
        ("node", osmium.osm.NODE),
        ("way", osmium.osm.WAY),
        ("relation", osmium.osm.RELATION),
    )
    for name, entity_type in entity_types:
        processor = osmium.FileProcessor(path, entities=entity_type)
        header = processor.header
        if not header_values:
            candidate_header_keys = (
                "generator",
                "osmosis_replication_timestamp",
                "osmosis_replication_sequence_number",
                "osmosis_replication_base_url",
            )
            header_values = {
                "generator": header.get("generator", ""),
                "replication_timestamp": header.get("osmosis_replication_timestamp", ""),
                "reported_header_options": [key for key in candidate_header_keys if header.get(key, "")],
            }
        rows: list[dict[str, Any]] = []
        for obj in processor:
            if name == "node":
                location = obj.location
                rows.append({
                    "id": str(obj.id),
                    "tags": {tag.k: tag.v for tag in obj.tags},
                    "lon": float(location.lon) if location.valid() else None,
                    "lat": float(location.lat) if location.valid() else None,
                })
            elif name == "way":
                rows.append({
                    "id": str(obj.id),
                    "tags": {tag.k: tag.v for tag in obj.tags},
                    "node_refs": [str(node.ref) for node in obj.nodes],
                })
            else:
                rows.append({
                    "id": str(obj.id),
                    "tags": {tag.k: tag.v for tag in obj.tags},
                    "members": [{"type": member.type, "ref": str(member.ref), "role": member.role} for member in obj.members],
                })
            if len(rows) >= SAMPLE_LIMIT:
                break
        samples[name] = {"sample_count": len(rows), "sample_limit": SAMPLE_LIMIT, "sample_complete": False, "objects": rows}
        del processor
        if not rows:
            raise RuntimeError(f"PBF produced no {name} objects in the bounded sample")
    return header_values, samples


def _zip_shapefile_path(archive_path: Path) -> tuple[str, list[str]]:
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.namelist()
    shp_files = [name for name in members if name.lower().endswith(".shp")]
    if len(shp_files) != 1:
        raise RuntimeError(f"Expected one shapefile in {archive_path.name}; found {len(shp_files)}")
    shp = shp_files[0]
    base = str(PurePosixPath(shp).with_suffix("")).lower()
    required = [f"{base}{extension}" for extension in (".shp", ".shx", ".dbf", ".prj")]
    member_names = {name.lower() for name in members}
    missing = [name for name in required if name not in member_names]
    if missing:
        raise RuntimeError(f"{archive_path.name} is missing shapefile members: {', '.join(missing)}")
    normalized_archive_path = archive_path.resolve().as_posix()
    if len(normalized_archive_path) >= 2 and normalized_archive_path[1] == ":":
        pass
    vsi_path = f"/vsizip/{normalized_archive_path}/{shp}"
    return vsi_path, required


def _read_census_sample(source_path: Path, source_id: str, identifier_field: str) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    vsi_path, required_members = _zip_shapefile_path(source_path)
    frame = pyogrio.read_dataframe(vsi_path, max_features=5, use_arrow=False)
    if frame.empty:
        raise RuntimeError(f"{source_id} returned no features in the sample")
    if frame.crs is None:
        raise RuntimeError(f"{source_id} shapefile has no readable CRS")
    fields = list(frame.columns)
    field_lookup = {name.casefold(): name for name in fields}
    required = {identifier_field.casefold()}
    if source_id == "census_blocks":
        required.update({"pop20", "housing20"})
    missing_fields = sorted(required - set(field_lookup))
    if missing_fields:
        raise RuntimeError(f"{source_id} sample is missing required fields: {', '.join(missing_fields)}")
    identifier_values = frame[field_lookup[identifier_field.casefold()]]
    if identifier_values.isna().any():
        raise RuntimeError(f"{source_id} sample has a null {identifier_field}")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise RuntimeError(f"{source_id} sample has empty geometry")
    if not frame.geometry.is_valid.all():
        raise RuntimeError(f"{source_id} sample has invalid geometry")
    summary = {
        "sample_count": int(len(frame)),
        "sample_limit": 5,
        "sample_complete": False,
        "crs": frame.crs.to_string(),
        "fields": fields,
        "required_members_present": required_members,
        "identifier_field": field_lookup[identifier_field.casefold()],
        "identifier_sample": [str(value) for value in identifier_values.tolist()],
        "geometry_types": sorted(str(value) for value in frame.geometry.geom_type.unique()),
    }
    return frame, summary


def run_worker(config: PipelineConfig, result_path: Path, gpkg_path: Path) -> dict[str, Any]:
    osm = config.sources["osm"]
    blocks = config.sources["census_blocks"]
    block_groups = config.sources["census_block_groups"]
    header, pbf_samples = _pbf_header_and_samples(osm.path)
    blocks_frame, blocks_report = _read_census_sample(blocks.path, "census_blocks", "GEOID20")
    groups_frame, groups_report = _read_census_sample(block_groups.path, "census_block_groups", "GEOID")

    polygon_source = groups_frame if len(groups_frame) else blocks_frame
    polygon = polygon_source.geometry.iloc[0]
    geoid_field = groups_report["identifier_field"] if len(groups_frame) else blocks_report["identifier_field"]
    census_geoid = str(polygon_source.iloc[0][geoid_field])
    if polygon_source.crs is None:
        raise RuntimeError("Census polygon source has no CRS")
    polygon_wgs84 = gpd.GeoSeries([polygon], crs=polygon_source.crs).to_crs(config.storage_crs).iloc[0]
    if not isinstance(polygon_wgs84, BaseGeometry) or polygon_wgs84.is_empty or not polygon_wgs84.is_valid:
        raise RuntimeError("Census sample polygon could not be transformed to valid storage-CRS geometry")
    roundtrip = write_and_verify_roundtrip(gpkg_path, polygon_wgs84, census_geoid)
    way_sample_preserved = all(
        "tags" in row and isinstance(row["node_refs"], list) and bool(row["node_refs"])
        for row in pbf_samples["way"]["objects"]
    )
    geopackage_values_preserved = all(
        layer["feature_count"] == 1
        and layer["crs"] == config.storage_crs
        and bool(layer["geometry_types"])
        and layer["string_id_preserved"]
        for layer in roundtrip.values()
    )
    result = {
        "pbf": {
            "header": header,
            "samples": pbf_samples,
            "selected_way_retains_tags_and_ordered_node_refs": way_sample_preserved,
        },
        "census": {"census_blocks": blocks_report, "census_block_groups": groups_report},
        "geopackage": {"path": str(gpkg_path), "layers": roundtrip, "gdal_layers": pyogrio.list_layers(gpkg_path).tolist()},
        "checks": {
            "pbf_header_read": bool(header),
            "pbf_node_way_relation_samples_read": all(pbf_samples[name]["sample_count"] > 0 for name in ("node", "way", "relation")),
            "pbf_way_tags_and_ordered_node_refs": way_sample_preserved,
            "census_samples_read": blocks_report["sample_count"] > 0 and groups_report["sample_count"] > 0,
            "gpkg_three_layer_roundtrip": set(roundtrip) == {"nodes", "lines", "polygons"},
            "gpkg_ids_crs_counts_geometry": geopackage_values_preserved,
        },
        "limitations": [
            "PBF and Census reads are bounded samples, not full source validation.",
            "Source SHA-256 inventory and archive-wide CRC checks are deferred to task 1.3.",
            "The GeoPackage node and line layers are synthetic interoperability fixtures; the polygon layer uses a sampled Census feature.",
        ],
    }
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result

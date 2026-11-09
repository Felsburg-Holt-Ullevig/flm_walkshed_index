"""Small GeoPackage round-trip fixture used by smoke and tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import pyogrio
from shapely.geometry import LineString, Point, Polygon


def _fixture_layers(polygon: Polygon, census_geoid: str) -> dict[str, gpd.GeoDataFrame]:
    crs = "EPSG:4326"
    return {
        "nodes": gpd.GeoDataFrame(
            [{"osm_id": "node-001", "raw_tags_json": json.dumps({"amenity": "station"}), "geometry": Point(-105.0, 39.75)}],
            geometry="geometry",
            crs=crs,
        ),
        "lines": gpd.GeoDataFrame(
            [{"osm_id": "way-002", "node_refs_json": json.dumps(["101", "102"]), "raw_tags_json": json.dumps({"highway": "footway"}), "geometry": LineString([(-105.0, 39.75), (-104.999, 39.751)])}],
            geometry="geometry",
            crs=crs,
        ),
        "polygons": gpd.GeoDataFrame(
            [{"census_geoid": census_geoid, "geometry": polygon}],
            geometry="geometry",
            crs=crs,
        ),
    }


def write_and_verify_roundtrip(path: str | Path, polygon: Polygon, census_geoid: str = "000000000001") -> dict[str, Any]:
    """Write node, line, and polygon layers; reopen and validate each layer."""
    target = Path(path)
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite GeoPackage: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    layers = _fixture_layers(polygon, census_geoid)
    for index, (layer_name, frame) in enumerate(layers.items()):
        frame.to_file(target, layer=layer_name, driver="GPKG", engine="pyogrio", mode="w" if index == 0 else "a")

    results: dict[str, Any] = {}
    for layer_name, expected in layers.items():
        actual = gpd.read_file(target, layer=layer_name, engine="pyogrio")
        if len(actual) != len(expected):
            raise RuntimeError(f"GeoPackage layer {layer_name} count changed: {len(actual)} != {len(expected)}")
        if actual.crs is None or not actual.crs.equals(expected.crs):
            raise RuntimeError(f"GeoPackage layer {layer_name} CRS changed")
        if actual.geometry.isna().any() or actual.geometry.is_empty.any():
            raise RuntimeError(f"GeoPackage layer {layer_name} contains empty geometry")
        if not all(actual.geometry.geom_type == expected.geometry.geom_type):
            raise RuntimeError(f"GeoPackage layer {layer_name} geometry type changed")
        if layer_name == "nodes" and (actual.loc[0, "osm_id"] != "node-001" or actual.loc[0, "raw_tags_json"] != '{"amenity": "station"}'):
            raise RuntimeError("GeoPackage node string ID or raw tags changed")
        if layer_name == "lines" and (actual.loc[0, "osm_id"] != "way-002" or actual.loc[0, "node_refs_json"] != '["101", "102"]'):
            raise RuntimeError("GeoPackage line string ID or ordered node references changed")
        if layer_name == "polygons" and actual.loc[0, "census_geoid"] != census_geoid:
            raise RuntimeError("GeoPackage Census identifier lost string type or leading zero")
        results[layer_name] = {
            "feature_count": int(len(actual)),
            "crs": actual.crs.to_string(),
            "geometry_types": sorted(str(value) for value in actual.geometry.geom_type.unique()),
            "string_id_preserved": (layer_name == "polygons" and actual.loc[0, "census_geoid"] == census_geoid) or (layer_name != "polygons" and actual.loc[0, "osm_id"].startswith(("node-", "way-"))),
        }

    info = pyogrio.list_layers(target)
    if set(info[:, 0].tolist()) != set(layers):
        raise RuntimeError("GeoPackage layer list did not match the written layers")
    return results

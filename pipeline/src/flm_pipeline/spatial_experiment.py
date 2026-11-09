"""Local experimental GIS adapter; count aggregation is delegated to pure TypeScript."""
from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import shapely
from pyproj import CRS, Transformer
from shapely.geometry import GeometryCollection, MultiPoint, MultiPolygon
from shapely.ops import unary_union

FT = 0.3048
AREA_TOLERANCE_SQFT = 1e-6
POLYGON_VERSION = "corridor-polygon-experiment-1"


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path: Path, value) -> None:
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, allow_nan=False, sort_keys=True, indent=2)
        stream.write('\n')


def polygon_valid(geometry, *, empty=False):
    if geometry is None or (geometry.is_empty and not empty):
        raise ValueError('missing or empty polygon')
    if geometry.is_empty:
        return
    if geometry.geom_type not in {'Polygon', 'MultiPolygon'} or not geometry.is_valid:
        raise ValueError('invalid polygon; repair is not authorized')
    if not math.isfinite(geometry.area) or geometry.area <= 0:
        raise ValueError('nonpositive or nonfinite polygon area')
    if not all(math.isfinite(v) for v in geometry.bounds):
        raise ValueError('nonfinite polygon coordinates')


@lru_cache(maxsize=8)
def _projector(source_crs: str, target_crs: str):
    source = CRS.from_user_input(source_crs)
    target = CRS.from_user_input(target_crs)
    if not source.is_geographic or target != CRS.from_epsg(26913):
        raise ValueError('expected explicit geographic source and EPSG:26913 target')
    return Transformer.from_crs(source, target, always_xy=True)


def project(geometry, source_crs: str, target_crs='EPSG:26913'):
    projector = _projector(source_crs, target_crs)
    bounds = geometry.bounds
    if not geometry.is_empty and not (-110 < bounds[0] <= bounds[2] < -100 and 36 < bounds[1] <= bounds[3] < 42):
        raise ValueError('geometry outside Colorado sample; check CRS or swapped axes')
    return shapely.transform(geometry, projector.transform, interleaved=False)


def corridor(lines, half_width_ft: int, *, units='international_feet'):
    if half_width_ft not in {25, 50}:
        raise ValueError('unapproved corridor width')
    if units not in {'international_feet', 'meters'}:
        raise ValueError('unsupported planar unit')
    width = half_width_ft * (FT if units == 'meters' else 1)
    pieces = []
    for line in lines:
        if line.geom_type != 'LineString' or not all(math.isfinite(v) for v in line.bounds):
            raise ValueError('invalid reached line')
        if line.length == 0:
            continue
        if not line.is_valid:
            raise ValueError('invalid reached line')
        if line.length > 0:
            pieces.append(line.buffer(width, cap_style='flat', join_style='mitre', mitre_limit=5))
    result = unary_union(pieces) if pieces else GeometryCollection()
    polygon_valid(result, empty=True)
    return result


def negative_hull(lines):
    points = [point for line in lines if line.length > 0 for point in (line.coords[0], line.coords[-1])]
    hull = MultiPoint(points).convex_hull if points else GeometryCollection()
    return hull if hull.geom_type == 'Polygon' else GeometryCollection()


def geometry_summary(geometry, divisor=1):
    polygon_valid(geometry, empty=True)
    parts = list(geometry.geoms) if geometry.geom_type == 'MultiPolygon' else ([] if geometry.is_empty else [geometry])
    return {'valid': geometry.is_valid, 'empty': geometry.is_empty,
            'area_sqft': geometry.area / divisor, 'area_acres': geometry.area / divisor / 43560,
            'components': len(parts), 'holes': sum(len(part.interiors) for part in parts)}


def measurements(units, polygon, *, divisor=1):
    """Keep full source polygons and point evidence, including zero-weight/missing records."""
    polygon_valid(polygon, empty=True)
    rows, evidence = [], []
    seen = set()
    for identifier, geometry, counts, attributes in sorted(units, key=lambda unit: unit[0]):
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise ValueError('duplicate or invalid source GEOID')
        seen.add(identifier)
        polygon_valid(geometry)
        point = geometry.representative_point()
        overlap = geometry.intersection(polygon)
        area = overlap.area / divisor
        if not math.isfinite(area):
            raise ValueError('nonfinite intersection')
        rows.append({'id': identifier, 'sourceAreaSqft': geometry.area / divisor,
                     'intersectionAreaSqft': area, 'representativeCovered': polygon.covers(point), 'counts': counts})
        evidence.append({'id': identifier, 'point_x': point.x, 'point_y': point.y,
                         'source_area_sqft': geometry.area / divisor, 'intersection_area_sqft': area,
                         'representative_covered': polygon.covers(point),
                         'source_attributes': json.dumps(attributes, sort_keys=True, allow_nan=False),
                         'geometry': point})
    return rows, evidence


def reopen_layer(path, layer, expected):
    actual = gpd.read_file(path, layer=layer)
    if len(actual) != len(expected) or actual.crs != expected.crs:
        raise ValueError(f'{layer}: reopened count/CRS mismatch')
    for i in range(len(actual)):
        if not actual.geometry.iloc[i].equals_exact(expected.geometry.iloc[i], 1e-9):
            raise ValueError(f'{layer}: reopened geometry mismatch')
        for field in expected.columns:
            if field != 'geometry' and actual[field].iloc[i] != expected[field].iloc[i]:
                raise ValueError(f'{layer}: reopened attribute mismatch: {field}')


def save_layer(path, layer, rows, crs):
    if not rows:
        return
    frame = gpd.GeoDataFrame(rows, geometry='geometry', crs=crs)
    # GeoPackage promotes mixed Polygon/MultiPolygon layers to MultiPolygon.
    # Make that wrapper explicit before exact reopen comparison; no coordinates change.
    if 'MultiPolygon' in set(frame.geometry.geom_type):
        frame.geometry = frame.geometry.map(lambda geometry: MultiPolygon([geometry]) if geometry.geom_type == 'Polygon' else geometry)
    frame.to_file(path, layer=layer, driver='GPKG', engine='pyogrio')
    reopen_layer(path, layer, frame)


def land_water_evidence(record, *, block):
    land_key, water_key = ('ALAND20', 'AWATER20') if block else ('ALAND', 'AWATER')
    land, water = record[land_key], record[water_key]
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0
           for value in (land, water)):
        raise ValueError('invalid source land/water area')
    total = land + water
    return {land_key:land, water_key:water, 'source_area_attribute_units':'square_meters',
            'reported_land_fraction':land/total if total else None,
            'reported_water_fraction':water/total if total else None,
            'allocation_denominator':'full_projected_geometry_not_source_land_area'}


def source_units(census_dir: Path, name: str):
    if name == 'blocks_2020':
        filename, id_field = 'blocks-2020', 'GEOID20'
        variables = ['POP20', 'HOUSING20']
    else:
        filename, id_field = 'block-groups-2024-acs', 'GEOID'
        variables = ['B01003_001', 'B08201_001', 'B08201_002']
    frame = gpd.read_file(census_dir / f'{filename}.gpkg', layer=name)
    if frame.crs != CRS.from_epsg(4269):
        raise ValueError('unexpected Census CRS')
    compact = [json.loads(line) for line in (census_dir / f'{filename}.jsonl').read_text(encoding='utf-8').splitlines()]
    records = {row[id_field]: row for row in compact}
    if len(records) != len(compact) or set(frame[id_field]) != set(records):
        raise ValueError('Census compact/GIS ID mismatch')
    units = []
    for row in frame.itertuples():
        identifier = getattr(row, id_field)
        record = records[identifier]
        counts = {variable: record[variable] for variable in variables} if name == 'blocks_2020' else {
            variable: record['acs'][variable]['estimate'] for variable in variables}
        attributes = land_water_evidence(record, block=name == 'blocks_2020')
        if name != 'blocks_2020':
            attributes['source_quartets'] = record['acs']
        units.append((identifier, project(row.geometry, 'EPSG:4269'), counts, attributes))
    return units, variables


def verified_report(path: Path, expected_sha256: str):
    if digest(path) != expected_sha256:
        raise ValueError(f'input report hash mismatch: {path.name}')
    report = json.loads(path.read_text(encoding='utf-8'))
    if report.get('status') not in {'complete', 'completed_with_incomplete_regional_results'} or not report.get('checks') or not all(report['checks'].values()):
        raise ValueError('input report incomplete')
    return report

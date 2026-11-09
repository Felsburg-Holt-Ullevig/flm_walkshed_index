from __future__ import annotations

import json
import subprocess

import pytest
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import substring, unary_union

from flm_pipeline.spatial_experiment import (
    AREA_TOLERANCE_SQFT, FT, corridor, geometry_summary, measurements,
    negative_hull, polygon_valid, project, save_layer, land_water_evidence,
)


def test_p01_p02_independent_rectangles_and_partial_offsets():
    source = LineString([(0, 0), (100, 0)])
    for width, expected in [(25, 5000), (50, 10000)]:
        actual = corridor([source], width)
        rectangle = box(0, -width, 100, width)
        assert actual.area == pytest.approx(expected, abs=AREA_TOLERANCE_SQFT)
        assert actual.symmetric_difference(rectangle).area <= AREA_TOLERANCE_SQFT
    partial = substring(source, 0, 40)
    assert corridor([partial], 25).symmetric_difference(box(0, -25, 40, 25)).area <= AREA_TOLERANCE_SQFT
    assert corridor([partial], 25).area == pytest.approx(2000, abs=AREA_TOLERANCE_SQFT)
    assert corridor([], 25).is_empty
    assert corridor([LineString([(0, 0), (0, 0)])], 25).is_empty


def test_p03_barrier_and_disconnected_components_do_not_create_routes():
    line = LineString([(0, 0), (100, 0)])
    actual = corridor([line], 25)
    assert actual.covers(Point(50, 15))  # Accepted spillover case, not a legal route.
    assert actual.covers(Point(50, 25))  # Boundary included.
    assert not actual.covers(Point(50, 25.01))
    separated = corridor([line, LineString([(0, 100), (100, 100)])], 25)
    assert geometry_summary(separated)['components'] == 2
    assert not separated.covers(Point(50, 50))
    assert negative_hull([line, LineString([(0, 100), (100, 100)])]).covers(Point(50, 50))
    assert negative_hull([line]).is_empty
    assert corridor([line, line], 25).equals(actual)


def test_a01_a02_a05_a06_a07_full_geometry_denominators():
    unit = ('u', box(0, 0, 100, 100), {'pop': 100, 'housing': 40}, {'ALAND': 6000})
    rows, evidence = measurements([unit], box(0, 0, 30, 100))
    assert rows[0]['sourceAreaSqft'] == 10000
    assert rows[0]['intersectionAreaSqft'] == 3000
    assert not rows[0]['representativeCovered']
    assert (evidence[0]['point_x'], evidence[0]['point_y']) == (50, 50)
    assert measurements([unit], box(0, 0, 50, 50))[0][0]['intersectionAreaSqft'] == 2500
    a, b = box(0, 0, 60, 100), box(40, 0, 100, 100)
    assert measurements([unit], a)[0][0]['intersectionAreaSqft'] == 6000
    assert measurements([unit], b)[0][0]['intersectionAreaSqft'] == 6000
    assert measurements([unit], unary_union([a, b]))[0][0]['intersectionAreaSqft'] == 10000
    rural = ('r', box(0, 0, 1000, 1000), {'pop': 1000}, {})
    rows, _ = measurements([rural], box(0, 0, 100, 100))
    assert rows[0]['intersectionAreaSqft'] / rows[0]['sourceAreaSqft'] == 0.01
    assert not rows[0]['representativeCovered']
    first = Polygon([(0,0),(100,0),(100,100),(0,100)], holes=[[(40,40),(60,40),(60,60),(40,60)]])
    multipart = MultiPolygon([first, box(200, 0, 250, 100)])
    rows, _ = measurements([('m', multipart, {'pop': 146}, {})], box(0, 0, 50, 100))
    assert rows[0]['sourceAreaSqft'] == 14600
    assert rows[0]['intersectionAreaSqft'] == 4800
    assert geometry_summary(multipart)['holes'] == 1


def test_invalid_missing_and_duplicate_units_fail_without_repair():
    for geometry in [None, Polygon(), LineString([(0,0),(1,1)]), Polygon([(0,0),(1,1),(0,1),(1,0)])]:
        with pytest.raises(ValueError):
            polygon_valid(geometry)
    unit = ('u', box(0,0,1,1), {'pop': None}, {})
    with pytest.raises(ValueError, match='duplicate'):
        measurements([unit, unit], box(0,0,1,1))


def test_projection_axis_order_and_roundtrip_with_explicit_units():
    # Independent UTM central-meridian invariant: longitude -105 maps to easting 500000m.
    point = Point(-105, 40)
    projected = project(point, 'EPSG:4269')
    assert projected.x == pytest.approx(500000, abs=1e-6)
    inverse = Transformer.from_crs(26913, 4269, always_xy=True)
    restored = shapely.transform(projected, inverse.transform, interleaved=False)
    assert restored.distance(point) < 1e-9  # Degrees, separate from area tolerance.
    line = LineString([(0,0),(100 * FT,0)])
    assert corridor([line], 25, units='meters').area / FT**2 == pytest.approx(5000, abs=1e-6)
    with pytest.raises(ValueError, match='swapped axes'):
        project(Point(40,-105), 'EPSG:4269')
    with pytest.raises(ValueError, match='geographic source'):
        project(Point(500000,4400000), 'EPSG:26913')


def test_geopackage_reopens_point_evidence_and_polygons(tmp_path):
    path = tmp_path / 'experiment.gpkg'
    save_layer(path, 'corridor', [{'id': 'p01', 'geometry': corridor([LineString([(0,0),(100,0)])],25)}], 'EPSG:26913')
    _, evidence = measurements([('u',box(0,0,100,100),{'pop':100},{})], box(0,0,30,100))
    save_layer(path, 'points', evidence, 'EPSG:26913')
    save_layer(path, 'mixed', [{'id':'single','geometry':box(0,0,1,1)},
               {'id':'multi','geometry':MultiPolygon([box(2,0,3,1),box(4,0,5,1)])}], 'EPSG:26913')


def test_actual_geometry_to_typescript_boundary_and_missing_rate(tmp_path):
    rows, _ = measurements([('u',box(0,0,100,100),{'B01003_001':100,'B08201_001':None,'B08201_002':None},{})],box(0,0,30,100))
    value = {'version':'allocation-weights-1','polygonId':'p01','sourceReleaseId':'synthetic',
             'coverage':'not_established','sets':[{'id':'a01','stationIds':['A'],
             'operation':'geometric_union_before_intersection',
             'variables':['B01003_001','B08201_001','B08201_002'],'rows':rows}]}
    source, target = tmp_path/'weights.json', tmp_path/'results.json'
    source.write_text(json.dumps(value),encoding='utf-8')
    result = subprocess.run(['node','scripts/allocate-experiment.mjs',str(source),str(target)],capture_output=True,text=True,timeout=30)
    assert result.returncode == 0, result.stderr
    outcome = json.loads(target.read_text())['results'][0]['comparisons'][0]
    assert outcome['totals']['B01003_001']['total'] == 30
    assert outcome['householdShare']['percent'] is None
    assert outcome['householdShare']['reason'] == 'missing_pairs'
    assert outcome['totals']['B08201_001']['total'] is None
    value['sets'][0]['rows'][0]['intersectionAreaSqft'] = -1
    source.write_text(json.dumps(value),encoding='utf-8')
    result = subprocess.run(['node','scripts/allocate-experiment.mjs',str(source),str(tmp_path/'bad.json')],capture_output=True,text=True,timeout=30)
    assert result.returncode != 0
    assert not (tmp_path/'bad.json').exists()


def test_land_water_shares_are_separate_source_evidence_not_area_denominators():
    evidence = land_water_evidence({'ALAND':6000,'AWATER':4000},block=False)
    assert evidence['reported_land_fraction'] == 0.6
    assert evidence['reported_water_fraction'] == 0.4
    assert evidence['ALAND'] == 6000
    assert evidence['allocation_denominator'] == 'full_projected_geometry_not_source_land_area'
    assert land_water_evidence({'ALAND20':0,'AWATER20':0},block=True)['reported_land_fraction'] is None
    with pytest.raises(ValueError):
        land_water_evidence({'ALAND':-1,'AWATER':0},block=False)

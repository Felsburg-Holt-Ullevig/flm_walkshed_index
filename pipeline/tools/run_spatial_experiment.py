"""Supervised, ignored local polygon/allocation demonstration. No API requests."""
from __future__ import annotations

import argparse
import csv
import hashlib
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import subprocess
import sys
import uuid

import geopandas as gpd
import jsonschema
import pyproj
import shapely
from shapely.geometry import LineString, Point, box, mapping
from shapely.ops import unary_union

from flm_pipeline.cli import _supervise
from flm_pipeline.spatial_experiment import (
    FT, POLYGON_VERSION, corridor, digest, geometry_summary, measurements,
    negative_hull, project, save_layer, source_units, verified_report, write_json,
)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'data/generated/prototype/spatial-experiments'
STAGING = ROOT / 'data/staging/prototype/spatial-experiments'


def local_path(value):
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('path outside repository')
    return path


def implementation_hashes():
    names = ['pipeline/tools/run_spatial_experiment.py',
             'pipeline/src/flm_pipeline/spatial_experiment.py', 'src/domain/allocation.ts',
             'scripts/allocate-experiment.mjs', 'contracts/allocation-experiment/v1/weights.schema.json',
             'pipeline/spatial-allocation-spec.md', 'pnpm-lock.yaml']
    return {name: digest(ROOT / name) for name in names}


def worker(config, stage):
    started = datetime.now(UTC)
    identities = implementation_hashes()
    census_path = local_path(config['census_report'])
    routing_path = local_path(config['routing_report'])
    census = verified_report(census_path, config['census_report_sha256'])
    routing = verified_report(routing_path, config['routing_report_sha256'])
    gpkg = local_path(config['routing_gpkg'])
    if digest(gpkg) != config['routing_gpkg_sha256']:
        raise ValueError('frozen routing GeoPackage hash mismatch')
    pinned = {str(census_path): digest(census_path), str(routing_path): digest(routing_path), str(gpkg): digest(gpkg)}
    for name, identity in census['outputs']['files'].items():
        path = census_path.parent / name
        if digest(path) != identity['sha256']:
            raise ValueError('Census output hash mismatch')
        pinned[str(path)] = identity['sha256']
    portions = gpd.read_file(gpkg, layer='reachable_edge_portions')
    if portions.crs != pyproj.CRS.from_epsg(4326):
        raise ValueError('unexpected reached interval CRS')
    if any(portions['to_offset_ft'] <= portions['from_offset_ft']):
        raise ValueError('nonpositive reached source interval')
    lines = [project(geometry, 'EPSG:4326') for geometry in portions.geometry]
    save_layer(stage/'comparison.gpkg', 'reached_source_intervals',
               [{**row, 'geometry': geometry} for row, geometry in zip(portions.drop(columns='geometry').to_dict('records'), lines)], 'EPSG:26913')
    polygons = {width: corridor(lines, width, units='meters') for width in (25,50)}
    hull = negative_hull(lines)
    polygon_id = digest(gpkg) + ':' + POLYGON_VERSION
    sets, point_rows, source_rows, polygon_rows, comparison = [], [], [], [], {}
    units_by_name = {name: source_units(census_path.parent, name) for name in ('blocks_2020','block_groups_2024_acs')}
    for name, (units, _) in units_by_name.items():
        source_rows.extend({'source_id': identifier, 'vintage': name, 'geometry': geometry} for identifier,geometry,_,_ in units)
    save_layer(stage/'comparison.gpkg','full_census_units',source_rows,'EPSG:26913')

    def add_set(identifier, station_ids, polygon, sample_name, units, variables):
        rows, points = measurements(units, polygon, divisor=FT**2)
        sets.append({'id':identifier,'stationIds':station_ids,'operation':'geometric_union_before_intersection',
                     'variables':variables,'rows':rows})
        point_rows.extend({**row,'set_id':identifier} for row in points
                          if row['intersection_area_sqft'] > 0 or row['representative_covered'])
        polygon_rows.append({'polygon_id':identifier,'sample_kind':sample_name,'allocation_allowed':True,'geometry':polygon})

    for width, polygon in polygons.items():
        comparison[str(width)] = geometry_summary(polygon, FT**2)
        for name,(units,variables) in units_by_name.items():
            denver = [unit for unit in units if unit[0][2:5] == '031']
            add_set(f'denver-{width}ft-{name}', ['accepted-source-node-7581419196'], polygon,
                    'source_node_diagnostic_not_verified_station', denver, variables)
    # Real rural source records; deliberately synthetic areas, with no route or station claim.
    for name,(units,variables) in units_by_name.items():
        rural = [unit for unit in units if unit[0][2:5] == '073']
        anchor = max(rural, key=lambda unit: (unit[1].area, unit[0]))[1].representative_point()
        x,y = anchor.x,anchor.y
        a = box(x-50*FT,y-50*FT,x+50*FT,y+50*FT)
        b = box(x,y-50*FT,x+100*FT,y+50*FT)
        for label, polygon, ids in [('A',a,['synthetic-A']),('B',b,['synthetic-B']),
                                    ('unique',unary_union([a,b]),['synthetic-A','synthetic-B'])]:
            add_set(f'lincoln-synthetic-{label}-{name}',ids,polygon,'synthetic_area_no_route_claim',rural,variables)
    if not hull.is_empty:
        polygon_rows.append({'polygon_id':'denver-negative-hull','sample_kind':'negative_control_no_allocation',
                             'allocation_allowed':False,'geometry':hull})
    save_layer(stage/'comparison.gpkg','polygon_comparisons',polygon_rows,'EPSG:26913')
    save_layer(stage/'comparison.gpkg','representative_points',point_rows,'EPSG:26913')
    weights = {'version':'allocation-weights-1','polygonId':polygon_id,'sourceReleaseId':census['run_id'],
               'coverage':'not_established','sets':sets}
    schema = json.loads((ROOT/'contracts/allocation-experiment/v1/weights.schema.json').read_text(encoding='utf-8'))
    jsonschema.Draft7Validator(schema).validate(weights)
    write_json(stage/'weights.json',weights)
    execution = subprocess.run(['node','scripts/allocate-experiment.mjs',str(stage/'weights.json'),str(stage/'allocations.json')],
                               cwd=ROOT,capture_output=True,text=True,timeout=120)
    if execution.returncode:
        raise ValueError('TypeScript allocation adapter failed: '+execution.stderr[:2000])
    outcomes = json.loads((stage/'allocations.json').read_text(encoding='utf-8'))
    if len(outcomes['results']) != len(sets):
        raise ValueError('allocation set mismatch')
    # Separate high-accuracy summation checks the domain result against geometry measurements.
    independent_checks = 0
    for data, result in zip(sets, outcomes['results']):
        if data['id'] != result['id']:
            raise ValueError('allocation set identity mismatch')
        for method in result['comparisons']:
            for variable in data['variables']:
                relevant = [row for row in data['rows'] if row['intersectionAreaSqft'] > 0 or row['representativeCovered']]
                missing = sum(row['counts'][variable] is None for row in relevant)
                reference = math.fsum(row['counts'][variable] * (
                    min(1,row['intersectionAreaSqft']/row['sourceAreaSqft']) if method['method']=='uniform_area'
                    else int(row['representativeCovered'])) for row in relevant if row['counts'][variable] is not None)
                total = method['totals'][variable]
                if (not math.isclose(reference,total['knownSubtotal'],rel_tol=1e-12,abs_tol=1e-9)
                    or missing != total['missingUnits'] or (total['total'] is None) != bool(missing)):
                    raise ValueError('independent allocation reconciliation failed')
                independent_checks += 1
    with (stage/'comparison.csv').open('x',encoding='utf-8',newline='') as stream:
        table = csv.writer(stream)
        table.writerow(['case','method','variable','complete_total','known_subtotal','missing_units','missing_intersection_sqft','derived_uncertainty'])
        for result in outcomes['results']:
            for method in result['comparisons']:
                for variable,total in method['totals'].items():
                    table.writerow([result['id'],method['method'],variable,total['total'],total['knownSubtotal'],
                                    total['missingUnits'],total['missingIntersectionSqft'],'not_quantified'])
    # Independent rectangle reference, not a second invocation of buffer as its own oracle.
    synthetic_line = LineString([(0,0),(100,0)])
    synthetic = []
    for width in (25,50):
        actual = corridor([synthetic_line],width)
        difference = actual.symmetric_difference(box(0,-width,100,width)).area
        if difference > 1e-6:
            raise ValueError('literal corridor rectangle comparison failed')
        synthetic.append({'width_ft':width,'area_sqft':actual.area,'symmetric_difference_sqft':difference})
    write_json(stage/'synthetic-reference.geojson',{'type':'FeatureCollection','coordinate_units':'international_feet',
               'crs_status':'local_synthetic_plane_not_geographic','features':[
               {'type':'Feature','properties':{'case':'P01-P03','width_ft':25},'geometry':mapping(corridor([synthetic_line],25))},
               {'type':'Feature','properties':{'case':'P03','meaning':'conceptual_barrier_spillover_expected'},'geometry':mapping(Point(50,15))}]})
    subset_error = polygons[25].difference(polygons[50]).area / FT**2
    midpoints = [line.interpolate(0.5,normalized=True) for line in lines]
    checks = {'source_reports_and_payload_hashes':True,'geopackages_reopened':True,
              'literal_rectangle_symmetric_difference':all(item['symmetric_difference_sqft'] <= 1e-6 for item in synthetic),
              'width_monotonicity':subset_error <= 1e-6,
              'reached_midpoints_covered':all(polygons[25].covers(point) for point in midpoints),
              'no_source_mutation':all(digest(Path(path)) == identity for path,identity in pinned.items()),
              'implementation_stable':identities == implementation_hashes(),
              'independent_allocation_reconciliation':independent_checks > 0}
    if not all(checks.values()):
        raise ValueError('spatial experiment verification failed')
    report = {'version':'spatial-experiment-run-1','status':'complete_experimental_evidence',
              'polygon_version':POLYGON_VERSION,'allocation_version':'allocation-comparison-1',
              'polygon_id':polygon_id,'allocation_id':digest(stage/'weights.json'),
              'source_release_id':census['run_id'],'reachability_run_id':routing['run_id'],
              'inputs':pinned,'implementation_hashes':identities,
              'settings':{'half_widths_ft':[25,50],'caps':'flat','joins':'mitre','mitre_limit':5,
                          'source_crs':['EPSG:4326','EPSG:4269'],'target_crs':'EPSG:26913','axis_order':'always_xy',
                          'feet_to_meters':FT,'weight_overshoot_tolerance':1e-12,
                          'synthetic_area_tolerance_sqft':1e-6,'regional_subset_tolerance_sqft':1e-6},
              'arithmetic_checks':{'independent_totals_checked':independent_checks,
                                   'absolute_tolerance_counts':1e-9,'relative_tolerance_counts':1e-12,
                                   'tolerance_role':'engineering_reconciliation_not_source_precision'},
              'geometry_library':{'shapely':shapely.__version__,'geos':shapely.geos_version_string,'pyproj':pyproj.__version__},
              'corridors':comparison,'width_symmetric_difference_sqft':polygons[25].symmetric_difference(polygons[50]).area/FT**2,
              'subset_error_sqft':subset_error,'synthetic_references':synthetic,
              'critical_points':{'reached_midpoints':len(midpoints),'P03_barrier_spillover':True,
                                 'named_regional_barriers':'not_reviewed_no_barrier_mask'},
              'checks':checks,'coverage':'not_established','derived_uncertainty':'not_quantified',
              'limitations':['Network corridor coverage experiment, not verified accessible land or approved FLM scores.',
                             'Regional network restrictions and coverage remain incomplete; origin is not a verified entrance.',
                             'All household/no-vehicle quartets are missing in the accepted Census sample.',
                             'No regional water/parcel/barrier mask or cross-vintage redistribution.',
                             'Lincoln polygons are synthetic; no regional network coverage is claimed.',
                             'Python geometry is experimental; TypeScript performs count/rate arithmetic.',
                             'Regional GIS visual/barrier inspection and browser polygon integration are not run.'],
              'duration_seconds':(datetime.now(UTC)-started).total_seconds()}
    report['settings_sha256'] = hashlib.sha256(json.dumps(report['settings'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    report['started_at_utc'] = started.isoformat()
    report['finished_at_utc'] = datetime.now(UTC).isoformat()
    report['environment'] = {'python':sys.version,'node':subprocess.check_output(['node','--version'],text=True).strip()}
    write_json(stage/'worker-report.json',report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--handoff',type=Path)
    parser.add_argument('--worker-config',type=Path)
    parser.add_argument('--stage',type=Path)
    args = parser.parse_args()
    if args.worker_config:
        if not args.stage or not args.stage.resolve().is_relative_to(STAGING.resolve()):
            raise ValueError('worker stage outside ignored spatial directory')
        worker(json.loads(args.worker_config.read_text(encoding='utf-8')),args.stage)
        return
    if not args.handoff:
        parser.error('--handoff required')
    handoff = json.loads(args.handoff.read_text(encoding='utf-8'))
    if handoff.get('task_5_4_status') != 'accepted_local_experiment_2026-11-05':
        raise ValueError('accepted experiment marker required')
    config = {'census_report':handoff['task_5_5_run_report'],'census_report_sha256':handoff['task_5_5_run_report_sha256'],
              'routing_report':handoff['task_4_4_regional_report'],'routing_report_sha256':handoff['task_4_4_regional_report_sha256'],
              'routing_gpkg':handoff['task_4_4_geopackage'],'routing_gpkg_sha256':handoff['task_4_4_geopackage_sha256']}
    run = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    stage, final = STAGING/run, OUTPUT/run
    stage.mkdir(parents=True,exist_ok=False)
    write_json(stage/'config.json',config)
    supervision = _supervise([sys.executable,str(Path(__file__).resolve()),'--worker-config',str(stage/'config.json'),
                             '--stage',str(stage)],ROOT,stage/'worker.log',1200,4294967296)
    if supervision.get('exit_code') != 0 or supervision.get('failure_reason') or not supervision.get('child_cleanup_complete'):
        write_json(stage/'failure.json',supervision)
        raise SystemExit(f'Spatial experiment failed; inspect {stage.relative_to(ROOT)}/worker.log')
    report = json.loads((stage/'worker-report.json').read_text(encoding='utf-8'))
    if not all(report['checks'].values()) or report['implementation_hashes'] != implementation_hashes():
        raise ValueError('worker report invalid or implementation changed')
    report.update(run_id=run,supervision=supervision,output_directory=final.relative_to(ROOT).as_posix(),
                  config_sha256=digest(stage/'config.json'))
    report['outputs'] = {path.name:{'sha256':digest(path),'bytes':path.stat().st_size}
                         for path in stage.iterdir() if path.is_file() and path.name not in {'worker-report.json','worker.log'}}
    # A failed run has no completion report. Successful directory is promoted once.
    OUTPUT.mkdir(parents=True,exist_ok=True)
    stage.rename(final)
    write_json(final/'run-report.json',report)
    print(json.dumps({'status':report['status'],'run_id':run,'report':str(final/'run-report.json')},indent=2))


if __name__ == '__main__':
    main()

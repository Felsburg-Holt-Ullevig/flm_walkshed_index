"""Prepare source-backed navigation cases from a completed regional GeoPackage.

This local review utility selects examples only; it does not assess walking access.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sqlite3

import pyogrio
from shapely.geometry import Point

from flm_pipeline.code_identity import code_identity
from flm_pipeline.config import load_config
from flm_pipeline.extractor import sha256_file

parser = argparse.ArgumentParser()
parser.add_argument("--config", type=Path, required=True)
parser.add_argument("--export", dest="export_dir", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
args.export_dir = args.export_dir.resolve()
args.output = args.output.resolve()
config = load_config(args.config)
report_path = args.export_dir / "run-report.json"
report = json.loads(report_path.read_text(encoding="utf-8"))
gpkg = args.export_dir / "source-network.gpkg"
assert report["status"] in {"pass", "pass_with_warnings", "empty"}
assert report["code_identity"]["sha256"] == code_identity()["sha256"]
assert report["configuration"]["sha256"] == sha256_file(config.config_path)
assert report["output"]["sha256"] == sha256_file(gpkg)
assert report["source"]["sha256"] == config.sources["osm"].expected_sha256
args.output.mkdir(parents=True, exist_ok=False)
station = Point(config.station_lonlat)
west, south, east, north = config.extract_bbox
best = {}


def consider(key, feature, score):
    rank = (float(score), len(feature["osm_id"]), feature["osm_id"])
    if key not in best or rank < best[key][0]:
        best[key] = (rank, feature)


for offset in range(0, report["counts"]["source_ways"], 1000):
    frame = pyogrio.read_dataframe(gpkg, layer="source_ways", skip_features=offset, max_features=1000)
    for _, row in frame.iterrows():
        tags = json.loads(row.tags_json)
        geom = row.geometry
        feature = {"osm_id": str(row.osm_id), "node_refs": json.loads(row.node_refs_json), "tags": tags, "geometry": geom}
        distance = geom.distance(station)
        consider("station", feature, distance)
        if tags.get("highway") in {"residential", "tertiary", "secondary", "primary", "unclassified", "living_street"}:
            consider("ordinary_street", feature, distance)
        if tags.get("highway") in {"footway", "path", "cycleway", "steps"}:
            consider("path", feature, distance)
        if tags.get("footway") == "crossing":
            consider("crossing", feature, distance)
        if tags.get("bridge") not in (None, "", "no"):
            consider("bridge", feature, distance)
        if tags.get("tunnel") not in (None, "", "no"):
            consider("tunnel", feature, distance)
        label = " ".join(tags.get(key, "") for key in ("name", "official_name", "alt_name")).casefold()
        for key, search in (("millennium", "millennium"), ("cherry_creek", "cherry creek"), ("wewatta", "wewatta"), ("speer", "speer")):
            if search in label:
                consider(key, feature, distance)
        minx, miny, maxx, maxy = geom.bounds
        for key, qualifies in (("west", minx < west), ("east", maxx > east), ("south", miny < south), ("north", maxy > north)):
            if qualifies:
                consider("edge_" + key, feature, distance)
        for key, xy in (("sw", (west, south)), ("se", (east, south)), ("nw", (west, north)), ("ne", (east, north))):
            consider("corner_" + key, feature, geom.distance(Point(xy)))

cases = []
facts = []


def add(case_id, name, source_ids, lon, lat, criteria, expected, raw=None):
    cases.append({"case_id": case_id, "place": name, "longitude": lon, "latitude": lat, "source_ids": "; ".join(source_ids), "selection_criteria": criteria, "expected_observation": expected, "status": "not_run", "reviewer": "", "date": "", "observation": "", "imagery_date": "", "screenshot_path": "", "follow_up": ""})
    facts.append({"case_id": case_id, "source_ids": source_ids, "longitude": lon, "latitude": lat, "raw_source_evidence": raw})


labels = [("station", "Station vicinity"), ("path", "Path-type source way"), ("crossing", "Source way tagged as a crossing"), ("bridge", "Bridge-tagged source way"), ("tunnel", "Tunnel-tagged source way"), ("millennium", "Millennium name match"), ("cherry_creek", "Cherry Creek name match"), ("wewatta", "Wewatta name match"), ("speer", "Speer name match")]
labels += [("ordinary_street", "Ordinary street source example")]
labels += [("edge_" + side, side.capitalize() + " extract-edge overhang") for side in ("west", "east", "south", "north")]
labels += [("corner_" + corner, corner.upper() + " extract-corner vicinity") for corner in ("sw", "se", "nw", "ne")]
missing = []
for number, (key, label) in enumerate(labels, 1):
    if key not in best:
        missing.append({"case": key, "reason": "No matching selected source way found by the stated raw-tag/bounds criterion"})
        continue
    feature = best[key][1]
    point = feature["geometry"].interpolate(0.5, normalized=True)
    criteria = "Raw source tag/name or extent match; nearest example to configured station (degree-distance ranks navigation examples only)"
    if key.startswith("corner_"):
        criteria = "Nearest selected way to configured extract corner; does not establish corner coverage"
    expected = "Inspect the full source way, ordered node IDs and raw tags. Source geometry and tags do not establish walking permission."
    if key.startswith("edge_"):
        expected = "The selected complete way extends outside this extract edge. Confirm its outside vertices remain visible; the rectangle does not prove route completeness."
    add(f"REG-{number:02d}", label, ["way/" + feature["osm_id"]], point.x, point.y, criteria, expected, {k:v for k,v in feature.items() if k != "geometry"})

with sqlite3.connect(gpkg) as connection:
    row = connection.execute("SELECT osm_id, lon, lat, tags_json FROM source_nodes WHERE tags_json LIKE ? ORDER BY (lon-?)*(lon-?)+(lat-?)*(lat-?), length(osm_id), osm_id LIMIT 1", ('%"barrier":%',station.x,station.x,station.y,station.y)).fetchone()
    if row and "barrier" in json.loads(row[3]):
        add("REG-30", "Source barrier tag", ["node/" + row[0]], row[1], row[2], "Nearest source node whose raw tags include barrier", "Read the barrier and access tags; no walking-rule interpretation is applied.", json.loads(row[3]))
    junction = connection.execute("WITH refs AS (SELECT from_node_id AS node_id, way_id FROM source_segments UNION ALL SELECT to_node_id AS node_id, way_id FROM source_segments), shared AS (SELECT node_id FROM refs GROUP BY node_id HAVING COUNT(DISTINCT way_id)>1) SELECT n.osm_id,n.lon,n.lat FROM shared s JOIN source_nodes n ON n.osm_id=s.node_id ORDER BY (n.lon-?)*(n.lon-?)+(n.lat-?)*(n.lat-?),length(n.osm_id),n.osm_id LIMIT 1", (station.x,station.x,station.y,station.y)).fetchone()
    if junction:
        incident = connection.execute("SELECT segment_id,way_id,from_node_id,to_node_id FROM source_segments WHERE from_node_id=? OR to_node_id=? ORDER BY segment_id", (junction[0],junction[0])).fetchall()
        add("REG-31", "Shared source-node junction", ["node/"+junction[0]]+[row[0] for row in incident], junction[1], junction[2], "Multiple source ways reference this exact node ID", "Check shared endpoint IDs on incident segments. A source junction is not an approved walking connection.", incident)
    coincident = connection.execute("SELECT lon,lat,COUNT(*) FROM source_nodes GROUP BY lon,lat HAVING COUNT(*)>1 ORDER BY (lon-?)*(lon-?)+(lat-?)*(lat-?),lon,lat LIMIT 1", (station.x,station.x,station.y,station.y)).fetchone()
    if coincident:
        ids = [row[0] for row in connection.execute("SELECT osm_id FROM source_nodes WHERE lon=? AND lat=? ORDER BY length(osm_id),osm_id", coincident[:2])]
        add("REG-32", "Distinct coincident source nodes", ["node/"+key for key in ids], coincident[0],coincident[1], "Exact equal coordinates with distinct source IDs", "Inspect each ID separately. Coordinate coincidence alone does not merge IDs.", {"node_ids":ids})

# Locate one actual XY crossing between disjoint source-reference lists.
bridge = best.get("bridge")
crossing_found = False
if bridge:
    candidate = bridge[1]
    refs = set(candidate["node_refs"])
    for offset in range(0, report["counts"]["source_ways"], 1000):
        frame = pyogrio.read_dataframe(gpkg, layer="source_ways", skip_features=offset, max_features=1000)
        for _, row in frame.iterrows():
            other_refs = json.loads(row.node_refs_json)
            if str(row.osm_id) == candidate["osm_id"] or refs.intersection(other_refs) or not candidate["geometry"].intersects(row.geometry):
                continue
            intersection = candidate["geometry"].intersection(row.geometry)
            point = intersection.representative_point()
            add("REG-33", "Geometric overlap with disjoint source IDs", ["way/"+candidate["osm_id"],"way/"+str(row.osm_id)],point.x,point.y,"Actual source line intersection and no shared node IDs between these two complete ways", "Read the source reference lists; screen overlap does not establish a shared source node.", {"intersection_type":intersection.geom_type,"first_node_refs":candidate["node_refs"],"second_node_refs":other_refs,"first_tags":candidate["tags"],"second_tags":json.loads(row.tags_json)})
            crossing_found = True
            break
        if crossing_found:
            break
if not crossing_found:
    missing.append({"case":"geometric_crossing","reason":"No disjoint-reference overlap found against the selected bridge example; not a regional absence claim"})

for number, (kind, examples) in enumerate((("zero_length", report["diagnostics"].get("zero_length_segment_examples", [])), ("repeated_reference", report["diagnostics"].get("repeated_way_node_reference_examples", [])), ("duplicate_segment", report["diagnostics"].get("duplicate_geometries", {}).get("source_segments", {}).get("examples", []))), 34):
    if not examples:
        missing.append({"case":kind,"reason":"GeoPackage report contains no example of this diagnostic"})
        continue
    example = examples[0]
    sid = example.get("segment_id") or example.get("duplicate_id")
    if sid:
        row = pyogrio.read_dataframe(gpkg, layer="source_segments", where="segment_id='"+sid.replace("'","''")+"'").iloc[0]
        point = row.geometry.interpolate(0.5, normalized=True)
        source_ids = [sid]
    else:
        node = example["node_id"]
        with sqlite3.connect(gpkg) as connection:
            lon,lat = connection.execute("SELECT lon,lat FROM source_nodes WHERE osm_id=?",(node,)).fetchone()
        point = Point(lon,lat)
        source_ids = ["way/"+example["way_id"],"node/"+node]
    add(f"REG-{number:02d}", kind.replace("_"," ").capitalize(), source_ids,point.x,point.y,"Actual reported diagnostic example","Inspect retained source IDs and report the observed geometry without repairing the final file.",example)

metadata_path = config.repo_root / report['extraction_directory'] / 'extraction.json'
assert sha256_file(metadata_path) == report['extraction_metadata_sha256']
metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
unresolved = metadata.get('diagnostics', {}).get('unresolved_relation_member_examples', [])
relation_case = False
for example in unresolved:
    with sqlite3.connect(gpkg) as connection:
        row = connection.execute('SELECT members_json FROM source_relations WHERE osm_id=?',(str(example['relation_id']),)).fetchone()
    if row is None:
        continue
    for member in json.loads(row[0]):
        if not member['resolved']:
            continue
        if member['type'] == 'node':
            with sqlite3.connect(gpkg) as connection:
                found = connection.execute('SELECT lon,lat FROM source_nodes WHERE osm_id=?',(member['ref'],)).fetchone()
            if not found:
                continue
            point = Point(*found)
        elif member['type'] == 'way':
            frame = pyogrio.read_dataframe(gpkg,layer='source_ways',where="osm_id='"+member['ref'].replace("'","''")+"'")
            if frame.empty:
                continue
            point = frame.iloc[0].geometry.interpolate(0.5,normalized=True)
        else:
            continue
        add('REG-37','Unresolved relation member',['relation/'+str(example['relation_id']),member['type']+'/'+member['ref']],point.x,point.y,'Actual unresolved member; marker context comes from a resolved member','Inspect the unresolved member ref/role in companion evidence. No relation geometry or restriction semantics are invented.',example)
        relation_case = True
        break
    if relation_case:
        break
if not relation_case:
    missing.append({'case':'unresolved_relation','reason':'No unresolved relation example with a resolved spatial context; inspect full relation evidence if relevant'})

with (args.output/'review-cases.csv').open('w',encoding='utf-8-sig',newline='') as stream:
    writer=csv.DictWriter(stream,fieldnames=list(cases[0]) if cases else ['case_id','status'])
    writer.writeheader()
    writer.writerows(cases)
(args.output/'review-observations-template.csv').write_bytes((args.output/'review-cases.csv').read_bytes())
with (args.output/'case-source-evidence.jsonl').open('w',encoding='utf-8',newline='\n') as stream:
    for fact in facts:
        stream.write(json.dumps(fact,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n')
manifest={'scope':'navigation and source-object review cases only; not a full network map or walking eligibility decision','source_sha256':report['source']['sha256'],'export_report':report_path.relative_to(config.repo_root).as_posix(),'export_report_sha256':sha256_file(report_path),'geopackage_sha256':report['output']['sha256'],'pipeline_code_identity':code_identity()['sha256'],'review_script_sha256':sha256_file(Path(__file__)),'case_count':len(cases),'missing_cases':missing,'manual_review_status':'not_run','files':{name:{'bytes':(args.output/name).stat().st_size,'sha256':sha256_file(args.output/name)} for name in ('review-cases.csv','review-observations-template.csv','case-source-evidence.jsonl')}}
(args.output/'review-dispatch-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
print(json.dumps(manifest,indent=2))

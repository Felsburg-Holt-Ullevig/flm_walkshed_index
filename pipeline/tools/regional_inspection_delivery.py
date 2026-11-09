"""Produce a complete, partitioned local KMZ review set from accepted GIS evidence.

This display-only adapter has its own version/hash and does not change the frozen
upstream pipeline identity or canonical data. All geometries remain whole.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
from datetime import UTC, datetime
import html
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import uuid
import xml.etree.ElementTree as ET
import zipfile

from flm_pipeline.code_identity import code_identity
from flm_pipeline.config import load_config
from flm_pipeline.extractor import sha256_file
from flm_pipeline.gpkg_export import _validate_extraction, _promote
from flm_pipeline.kml_export import (_atomic_json, _bounds, _feature_description, _line_xml, _placemark, _point_xml, _polygon_xml, _safe_xml_id, _write_evidence, _write_icons, MAX_PLACEMARKS, MAX_VERTICES, MAX_PAYLOAD_BYTES)

VERSION = 'regional-inspection-delivery-1'
NS = {'k': 'http://www.opengis.net/kml/2.2'}
FOLDERS = {'information':'Package information','cases':'Review cases','coverage':'Coverage','node':'Source nodes','segment':'Source segments','way':'Source ways','diagnostic':'Diagnostics'}
SEGMENTS = ('segment_id','way_id','from_node_id','to_node_id','sequence','tags_json','length_geodesic_m','length_projected_m','zero_length')
STYLES = '<Style id="line"><LineStyle><color>ff24a148</color><width>2</width></LineStyle></Style><Style id="way"><LineStyle><color>aa0072b2</color><width>1</width></LineStyle></Style><Style id="node"><IconStyle><scale>0.75</scale><Icon><href>icons/source-node.png</href></Icon></IconStyle></Style><Style id="case"><IconStyle><Icon><href>icons/review-case.png</href></Icon></IconStyle></Style><Style id="diagnostic"><IconStyle><Icon><href>icons/diagnostic.png</href></Icon></IconStyle></Style><Style id="coverage"><LineStyle><color>ff666666</color><width>2</width></LineStyle><PolyStyle><fill>0</fill><outline>1</outline></PolyStyle></Style>'


def numeric(value):
    return len(value),value


def node_rows(source, refs):
    values = sorted(set(refs),key=numeric)
    rows = {}
    for offset in range(0,len(values),500):
        keys=values[offset:offset+500]
        for row in source.execute('SELECT osm_id,lon,lat,tags_json,inside_core,inside_extract FROM source_nodes WHERE osm_id IN ('+','.join('?'*len(keys))+')',keys):
            rows[row['osm_id']]=dict(row)
    if set(rows)!=set(refs):
        raise ValueError('A complete way references absent source nodes')
    return rows


class Part:
    def __init__(self, root, name, package_id, work, cap, vertices, cell=None):
        self.root,self.name,self.package_id,self.work = root,name,package_id,work
        self.cap,self.vertex_cap,self.cell=cap,vertices,cell
        self.count=0;self.vertices=0;self.counts={key:0 for key in FOLDERS};self.nodes=set()
        self.paths={key:root/('.'+name+'.'+key+'.xml') for key in FOLDERS}
        self.streams={key:path.open('w',encoding='utf-8',newline='\n') for key,path in self.paths.items()}
    def fits(self,count,vertices):
        return self.count+count<=self.cap and self.vertices+vertices<=self.vertex_cap
    def emit(self,folder,xml,vertices,source_id=None):
        if not self.fits(1,vertices):
            raise ValueError('Partition limit exceeded: '+self.name)
        self.streams[folder].write(xml)
        self.count+=1;self.vertices+=vertices;self.counts[folder]+=1
        if source_id is not None:
            self.work.execute('INSERT INTO membership VALUES (?,?,?)',(folder,source_id,self.name))
    def finish(self):
        for stream in self.streams.values():stream.close()
        with zipfile.ZipFile(self.root/self.name,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            with archive.open('doc.kml','w') as target:
                target.write(('<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>'+html.escape(self.package_id+' — '+self.name)+'</name><description>Complete source geometries; use the overview and membership index to locate features across this review set.</description>'+STYLES).encode('utf-8'))
                for key,name in FOLDERS.items():
                    target.write(('<Folder><name>'+name+'</name><visibility>'+('0' if key in {'node','way','diagnostic'} else '1')+'</visibility>').encode('utf-8'))
                    with self.paths[key].open('rb') as source:shutil.copyfileobj(source,target,1024*1024)
                    target.write(b'</Folder>')
                target.write(b'</Document></kml>')
            for path in sorted((self.root/'icons').glob('*.png')):archive.write(path,'icons/'+path.name)
        for path in self.paths.values():path.unlink()
        self.nodes.clear()
        return {'file':self.name,'anchor_cell':self.cell,'placemarks':self.count,'vertices':self.vertices,'folder_counts':self.counts}


def emit_node(part,row):
    oid=row['osm_id'];tags=json.loads(row['tags_json'])
    fields={**row,'package_id':part.package_id}
    description=_feature_description('Node '+oid,[('Node ID',oid)],tags,[('Longitude',row['lon']),('Latitude',row['lat']),('Inside core area',bool(row['inside_core'])),('Inside extract area',bool(row['inside_extract'])),('Package ID',part.package_id)])
    part.emit('node',_placemark(xml_id=_safe_xml_id('node',oid),name='node/'+oid,description=description,geometry_xml=_point_xml(row['lon'],row['lat']),fields=fields,style='node'),1,oid)
    part.nodes.add(oid)


def verify_part(path,declared,source,work):
    with zipfile.ZipFile(path) as archive:
        if set(archive.namelist())!={'doc.kml','icons/source-node.png','icons/review-case.png','icons/diagnostic.png'} or archive.testzip() is not None:raise ValueError('Invalid KMZ archive '+path.name)
        root=ET.fromstring(archive.read('doc.kml'))
    if root.tag!='{http://www.opengis.net/kml/2.2}kml' or root.findall('.//k:NetworkLink',NS):raise ValueError('Invalid KML namespace or network link')
    if any((node.text or '') not in {'icons/source-node.png','icons/review-case.png','icons/diagnostic.png'} for node in root.findall('.//k:href',NS)):raise ValueError('Nonlocal KML resource')
    ids=set();count=vertices=0;source_extent=None;folder_counts={key:0 for key in FOLDERS}
    folder_keys={value:key for key,value in FOLDERS.items()}
    for folder in root.findall('.//k:Folder',NS):
        kind=folder_keys[folder.findtext('k:name',namespaces=NS)]
        for feature in folder.findall('k:Placemark',NS):
            xml_id=feature.get('id')
            if not xml_id or xml_id in ids:raise ValueError('Duplicate or absent KML ID')
            ids.add(xml_id);count+=1;folder_counts[kind]+=1
            fields={item.get('name'):item.findtext('k:value',namespaces=NS) or '' for item in feature.findall('k:ExtendedData/k:Data',NS)}
            coordinates=[]
            for element in feature.findall('.//k:coordinates',NS):
                for token in (element.text or '').split():
                    lon,lat=map(float,token.split(',')[:2])
                    if not math.isfinite(lon+lat) or not -180<=lon<=180 or not -90<=lat<=90:raise ValueError('Invalid KML coordinate')
                    coordinates.append((lon,lat))
            vertices+=len(coordinates)
            if kind not in {'node','way','segment'}:continue
            for lon,lat in coordinates:
                source_extent=[lon,lat,lon,lat] if source_extent is None else [min(source_extent[0],lon),min(source_extent[1],lat),max(source_extent[2],lon),max(source_extent[3],lat)]
            oid=fields.get('segment_id' if kind=='segment' else 'osm_id')
            expected_file=work.execute('SELECT 1 FROM membership WHERE kind=? AND source_id=? AND file=?',(kind,oid,path.name)).fetchone()
            if expected_file is None:raise ValueError('Unexpected feature membership')
            row=source.execute('SELECT * FROM source_'+{'node':'nodes','way':'ways','segment':'segments'}[kind]+' WHERE '+('segment_id' if kind=='segment' else 'osm_id')+'=?',(oid,)).fetchone()
            if row is None or json.loads(fields['tags_json'])!=json.loads(row['tags_json']):raise ValueError('Source identity or tag mismatch')
            if kind=='node':
                expected=[(row['lon'],row['lat'])]
                for key in ('inside_core','inside_extract'):
                    if int(fields[key])!=row[key]:raise ValueError('Node coverage flag mismatch')
            elif kind=='way':
                refs=json.loads(row['node_refs_json'])
                if json.loads(fields['node_refs_json'])!=refs:raise ValueError('Ordered references changed')
                nodes=node_rows(source,refs);expected=[(nodes[ref]['lon'],nodes[ref]['lat']) for ref in refs]
            else:
                for key in ('way_id','from_node_id','to_node_id'):
                    if fields[key]!=row[key]:raise ValueError('Segment reference mismatch')
                if int(fields['sequence'])!=row['sequence'] or int(fields['zero_length'])!=row['zero_length']:raise ValueError('Segment sequence/flag mismatch')
                for key in ('length_geodesic_m','length_projected_m'):
                    if not math.isclose(float(fields[key]),row[key],rel_tol=1e-12,abs_tol=1e-8):raise ValueError('Segment length mismatch')
                nodes=node_rows(source,[row['from_node_id'],row['to_node_id']]);expected=[(nodes[ref]['lon'],nodes[ref]['lat']) for ref in (row['from_node_id'],row['to_node_id'])]
            if len(coordinates)!=len(expected) or any(abs(a-c)>1e-9 or abs(b-d)>1e-9 for (a,b),(c,d) in zip(coordinates,expected)):raise ValueError('Coordinate sequence changed')
            work.execute('INSERT INTO parsed VALUES (?,?,?)',(kind,oid,path.name))
    declared['actual_source_extent']=source_extent
    if count!=declared['placemarks'] or vertices!=declared['vertices'] or folder_counts!=declared['folder_counts'] or count>MAX_PLACEMARKS or vertices>MAX_VERTICES:raise ValueError('Partition counts or hard limits mismatch')


def verify_evidence(path,source,work,expected_counts):
    work.execute('CREATE TABLE evidence_seen(kind TEXT,id TEXT,PRIMARY KEY(kind,id)) WITHOUT ROWID')
    counts={kind:0 for kind in expected_counts};digest=hashlib.sha256()
    with path.open('rb') as stream:
        for line in stream:
            digest.update(line);record=json.loads(line);kind=record['entity_type']
            oid=record['segment_id'] if kind=='segment' else record['osm_id']
            if not isinstance(oid,str):raise ValueError('Evidence ID is not text')
            work.execute('INSERT INTO evidence_seen VALUES (?,?)',(kind,oid));counts[kind]+=1
            table={'node':'source_nodes','way':'source_ways','relation':'source_relations','segment':'source_segments'}[kind]
            row=source.execute('SELECT * FROM '+table+' WHERE '+('segment_id' if kind=='segment' else 'osm_id')+'=?',(oid,)).fetchone()
            if row is None:raise ValueError('Evidence source record is absent')
            if kind=='node':expected={'entity_type':kind,'osm_id':oid,'lon':row['lon'],'lat':row['lat'],'tags':json.loads(row['tags_json'])}
            elif kind=='way':expected={'entity_type':kind,'osm_id':oid,'node_refs':json.loads(row['node_refs_json']),'tags':json.loads(row['tags_json'])}
            elif kind=='relation':expected={'entity_type':kind,'osm_id':oid,'members':json.loads(row['members_json']),'tags':json.loads(row['tags_json'])}
            else:
                expected={key:row[key] for key in SEGMENTS};expected['entity_type']=kind
                nodes=node_rows(source,[row['from_node_id'],row['to_node_id']]);expected['coordinates_lon_lat']=[[nodes[ref]['lon'],nodes[ref]['lat']] for ref in (row['from_node_id'],row['to_node_id'])]
            if record!=expected:raise ValueError('Evidence values differ from parent source record')
    if counts!=expected_counts:raise ValueError('Reopened evidence counts differ')
    return digest.hexdigest()


def build(args, candidate, package_id):
    config=load_config(args.config)
    parent_report=args.export_dir.resolve()/'run-report.json';report=json.loads(parent_report.read_text(encoding='utf-8'))
    if report.get('status') not in {'pass','pass_with_warnings','empty'}:raise ValueError('Completed GeoPackage required')
    extraction,metadata,identity=_validate_extraction(config,config.repo_root/report['extraction_directory'])
    gpkg=args.export_dir.resolve()/'source-network.gpkg'
    if report['code_identity']['sha256']!=identity['sha256'] or sha256_file(gpkg)!=report['output']['sha256'] or sha256_file(config.config_path)!=report['configuration']['sha256']:raise ValueError('Parent identity/hash mismatch')
    acceptance_hash=sha256_file(args.acceptance)
    acceptance=json.loads(args.acceptance.read_text(encoding='utf-8'))
    if acceptance['sha256']!=metadata['source']['sha256']:raise ValueError('Source acceptance does not identify these bytes')
    case_manifest_path=args.cases/'review-dispatch-manifest.json';case_manifest_hash=sha256_file(case_manifest_path);case_manifest=json.loads(case_manifest_path.read_text(encoding='utf-8'))
    if case_manifest['geopackage_sha256']!=report['output']['sha256']:raise ValueError('Cases are linked to another GeoPackage')
    for name,record in case_manifest['files'].items():
        if Path(name).name!=name or sha256_file(args.cases/name)!=record['sha256']:raise ValueError('Case payload hash mismatch')
    with (args.cases/'review-cases.csv').open(encoding='utf-8-sig',newline='') as stream:cases=list(csv.DictReader(stream))
    if len({row['case_id'] for row in cases})!=len(cases):raise ValueError('Duplicate case IDs')
    candidate.mkdir(parents=True,exist_ok=False);_write_icons(candidate)
    db_path=candidate/'.delivery.sqlite';work=sqlite3.connect(db_path);work.row_factory=sqlite3.Row
    source=sqlite3.connect('file:'+gpkg.as_posix()+'?mode=ro',uri=True);source.row_factory=sqlite3.Row
    parts=[];active={};sequence={}
    west,south,east,north=config.extract_bbox
    def tile(lon,lat):return (min(args.grid-1,max(0,int((lon-west)/(east-west)*args.grid))),min(args.grid-1,max(0,int((lat-south)/(north-south)*args.grid))))
    def allocate(cell,features,vertices):
        part=active.get(cell)
        if part is None or not part.fits(features,vertices):
            if part is not None:parts.append(part.finish())
            sequence[cell]=sequence.get(cell,0)+1
            part=Part(candidate,('case-network' if args.case_only else 'network')+f'-x{cell[0]:02d}-y{cell[1]:02d}-{sequence[cell]:03d}.kmz',package_id,work,args.network_cap,args.vertex_cap,list(cell));active[cell]=part
        if not part.fits(features,vertices):raise ValueError('A whole source-way group exceeds one file limit; no geometry was split')
        return part
    try:
        work.execute('PRAGMA cache_size=-32768');work.execute('PRAGMA temp_store=FILE')
        work.execute('CREATE TABLE membership(kind TEXT,source_id TEXT,file TEXT,PRIMARY KEY(kind,source_id,file)) WITHOUT ROWID')
        work.execute('CREATE TABLE evidence_relations(source_id TEXT PRIMARY KEY) WITHOUT ROWID')
        work.execute('CREATE TABLE parsed(kind TEXT,source_id TEXT,file TEXT,PRIMARY KEY(kind,source_id,file)) WITHOUT ROWID')
        work.execute('CREATE TABLE segments(segment_id TEXT PRIMARY KEY,way_id TEXT,from_node_id TEXT,to_node_id TEXT,sequence INTEGER,tags_json TEXT,length_geodesic_m REAL,length_projected_m REAL,zero_length INTEGER)')
        cursor=source.execute('SELECT '+','.join(SEGMENTS)+' FROM source_segments')
        while rows:=cursor.fetchmany(5000):work.executemany('INSERT INTO segments VALUES (?,?,?,?,?,?,?,?,?)',rows)
        work.execute('CREATE INDEX segments_by_way ON segments(way_id,sequence)');work.commit()
        requested_ways=set();requested_nodes=set()
        if args.case_only:
            for case in cases:
                for identifier in case['source_ids'].split('; '):
                    if '/segment/' in identifier:
                        found=source.execute('SELECT way_id FROM source_segments WHERE segment_id=?',(identifier,)).fetchone()
                        if found is None:raise ValueError('Requested segment absent: '+identifier)
                        requested_ways.add(found[0])
                    else:
                        kind,oid=identifier.split('/',1)
                        if kind=='way':requested_ways.add(oid)
                        elif kind=='node':requested_nodes.add(oid)
                        elif kind!='relation':raise ValueError('Unknown case source identifier')
            if requested_nodes:
                node_rows(source,list(requested_nodes))
                keys=sorted(requested_nodes,key=numeric)
                for offset in range(0,len(keys),400):
                    chunk=keys[offset:offset+400];marks=','.join('?'*len(chunk))
                    requested_ways.update(row[0] for row in work.execute('SELECT DISTINCT way_id FROM segments WHERE from_node_id IN ('+marks+') OR to_node_id IN ('+marks+')',chunk+chunk))

        for row in source.execute('SELECT osm_id,node_refs_json,tags_json,node_count FROM source_ways ORDER BY length(osm_id),osm_id'):
            oid=row['osm_id']
            if args.case_only and oid not in requested_ways:continue
            refs=json.loads(row['node_refs_json']);nodes=node_rows(source,refs);coords=[(nodes[ref]['lon'],nodes[ref]['lat']) for ref in refs]
            cell=tile(sum(x for x,y in coords)/len(coords),sum(y for x,y in coords)/len(coords))
            edges=list(work.execute('SELECT * FROM segments WHERE way_id=? ORDER BY sequence',(oid,)))
            if len(edges)!=len(refs)-1:raise ValueError('Source way and segment count mismatch')
            current=active.get(cell);new_nodes=set(refs)-(current.nodes if current else set())
            features=1+len(edges)+len(new_nodes);vertices=len(coords)+2*len(edges)+len(new_nodes)
            if current is not None and not current.fits(features,vertices):
                parts.append(current.finish());del active[cell];new_nodes=set(refs);features=1+len(edges)+len(new_nodes);vertices=len(coords)+2*len(edges)+len(new_nodes)
            part=allocate(cell,features,vertices)
            for ref in sorted(new_nodes,key=numeric):emit_node(part,nodes[ref])
            fields=dict(row);fields['package_id']=package_id;tags=json.loads(row['tags_json'])
            desc=_feature_description('Way '+oid,[('Way ID',oid),('Number of source nodes',len(refs))],tags,[('Ordered node IDs',', '.join(refs)),('Package ID',package_id)])
            part.emit('way',_placemark(xml_id=_safe_xml_id('way',oid),name='way/'+oid,description=desc,geometry_xml=_line_xml(coords),fields=fields,style='way'),len(coords),oid)
            for index,edge in enumerate(edges):
                if edge['from_node_id']!=refs[index] or edge['to_node_id']!=refs[index+1]:raise ValueError('Source pair order mismatch')
                fields=dict(edge);fields['package_id']=package_id;sid=edge['segment_id']
                summary=[('Segment ID',sid),('From node',edge['from_node_id']),('To node',edge['to_node_id']),('Length along Earth\'s surface',f"{edge['length_geodesic_m']:,.2f} m")]
                if edge['zero_length']:summary.append(('Display','Zero length: inspect by ID or diagnostic case pin'))
                desc=_feature_description('Source segment',summary,json.loads(edge['tags_json']),[('Source way ID',oid),('Pair position (starts at 0)',edge['sequence']),('Projected length (EPSG:26913 check), m',edge['length_projected_m']),('Package ID',package_id)])
                part.emit('segment',_placemark(xml_id=_safe_xml_id('segment',sid),name=sid,description=desc,geometry_xml=_line_xml(coords[index:index+2]),fields=fields,style='line'),2,sid)
            work.commit()
        for row in source.execute('SELECT osm_id,lon,lat,tags_json,inside_core,inside_extract FROM source_nodes ORDER BY length(osm_id),osm_id'):
            if args.case_only and row['osm_id'] not in requested_nodes:continue
            if work.execute("SELECT 1 FROM membership WHERE kind='node' AND source_id=? LIMIT 1",(row['osm_id'],)).fetchone():continue
            part=allocate(tile(row['lon'],row['lat']),1,1);emit_node(part,dict(row))
        for cell in sorted(active):parts.append(active[cell].finish())
        work.commit()
        overview=Part(candidate,'source-network-inspection.kmz',package_id,work,MAX_PLACEMARKS,MAX_VERTICES)
        scope='partial case-only view; complete regional source subset remains in canonical JSONL, GeoPackage and companion evidence' if args.case_only else 'complete regional source subset across all listed KMZ files'
        info={'package_id':package_id,'dataset_kind':args.dataset_kind,'scope':scope,'source_sha256':metadata['source']['sha256'],'partition_method':'whole-way groups assigned by mean source-vertex anchor to a fixed grid; complete geometries retained; shared node copies declared in membership index'}
        overview.emit('information',_placemark(xml_id='package-info',name=package_id,description=_feature_description('Regional review set',[('Network files',len(parts)),('Review cases',len(cases))],{},list(info.items())),geometry_xml=_point_xml(*config.station_lonlat),fields=info),1)
        for key,label in (('core_bbox','Core'),('extract_bbox','Extract'),('expanded_comparison_bbox','Planned expanded comparison')):
            xml=_placemark(xml_id='coverage-'+key,name=label,description='Configured extent; complete ways may extend outside. Expanded comparison is planned metadata only.',geometry_xml=_polygon_xml(_bounds(metadata['coverage'][key])),fields={'coverage_kind':key,'bbox':metadata['coverage'][key]},style='coverage')
            if key=='expanded_comparison_bbox':xml=xml.replace('</name>','</name><visibility>0</visibility>',1)
            overview.emit('coverage',xml,5)
        for row in cases:
            names=set()
            for identifier in row['source_ids'].split('; '):
                if '/segment/' in identifier:kind,oid='segment',identifier
                else:
                    kind,oid=identifier.split('/',1)
                    if kind=='relation':continue
                names.update(item[0] for item in work.execute('SELECT file FROM membership WHERE kind=? AND source_id=?',(kind,oid)))
            if not names:raise ValueError('A review case has no locatable source object: '+row['case_id'])
            row['kmz_files']='; '.join(sorted(names));row['status']='not_run'
            lon,lat=float(row['longitude']),float(row['latitude'])
            desc=_feature_description(row['place'],[('Source IDs',row['source_ids']),('Open network files',row['kmz_files']),('What to check',row['expected_observation'])],{},[('Selection criterion',row['selection_criteria']),('Package ID',package_id)])
            overview.emit('cases',_placemark(xml_id=_safe_xml_id('case',row['case_id']),name=row['case_id']+' — '+row['place'],description=desc,geometry_xml=_point_xml(lon,lat),fields=row,style='case'),1)
            if any(word in row['place'].casefold() for word in ('zero length','repeated reference','duplicate','unresolved relation','degenerate')):
                overview.emit('diagnostic',_placemark(xml_id=_safe_xml_id('diagnostic',row['case_id']),name='Diagnostic — '+row['place'],description=desc,geometry_xml=_point_xml(lon,lat),fields=row,style='diagnostic'),1)
        parts.append(overview.finish())
        for part in parts:verify_part(candidate/part['file'],part,source,work)
        for query in ('SELECT * FROM membership EXCEPT SELECT * FROM parsed','SELECT * FROM parsed EXCEPT SELECT * FROM membership'):
            if work.execute(query).fetchone():raise ValueError('Parsed feature membership differs from declared membership')
        counts={kind:work.execute('SELECT COUNT(DISTINCT source_id) FROM membership WHERE kind=?',(kind,)).fetchone()[0] for kind in ('node','way','segment')}
        expected={'node':report['counts']['source_nodes'],'way':report['counts']['source_ways'],'segment':report['counts']['source_segments']}
        if not args.case_only and counts!=expected:raise ValueError('Unique source feature counts do not reconcile')
        if args.case_only and counts['way']!=len(requested_ways):raise ValueError('Requested source ways were not completely represented')
        omitted={kind:expected[kind]-counts[kind] for kind in expected}
        if any(value<0 for value in omitted.values()):raise ValueError('Rendered counts exceed parent counts')
        for kind in ('way','segment'):
            if work.execute('SELECT source_id FROM membership WHERE kind=? GROUP BY source_id HAVING COUNT(*)<>1',(kind,)).fetchone():raise ValueError('A way or segment was duplicated between network files')
        duplicate_nodes=work.execute("SELECT COUNT(*) FROM (SELECT source_id FROM membership WHERE kind='node' GROUP BY source_id HAVING COUNT(*)>1)").fetchone()[0]
        with (candidate/'feature-membership.jsonl').open('w',encoding='utf-8',newline='\n') as stream:
            for kind,oid,name,occurrences in work.execute('SELECT m.kind,m.source_id,m.file,(SELECT COUNT(*) FROM membership n WHERE n.kind=m.kind AND n.source_id=m.source_id) FROM membership m ORDER BY m.kind,length(m.source_id),m.source_id,m.file'):
                stream.write(json.dumps({'entity_type':kind,'source_id':oid,'kmz_file':name,'occurrence_count':occurrences,'duplicated_across_files':occurrences>1},sort_keys=True,separators=(',',':'))+'\n')
        if args.case_only:
            evidence_counts={};digest=hashlib.sha256()
            def evidence_line(stream,record):
                raw=(json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode('utf-8');stream.write(raw);digest.update(raw)
            with (candidate/'source-evidence.jsonl').open('wb') as stream:
                for filename,kind in (('nodes.jsonl','node'),('ways.jsonl','way'),('relations.jsonl','relation')):
                    count=0
                    with (extraction/filename).open(encoding='utf-8') as records:
                        for line in records:
                            record=json.loads(line);oid=record['osm_id']
                            if kind!='relation':
                                include=work.execute('SELECT 1 FROM membership WHERE kind=? AND source_id=? LIMIT 1',(kind,oid)).fetchone() is not None
                            else:
                                include=any(member['type'] in {'node','way'} and work.execute('SELECT 1 FROM membership WHERE kind=? AND source_id=? LIMIT 1',(member['type'],member['ref'])).fetchone() for member in record['members'])
                            if include:
                                evidence_line(stream,{'entity_type':kind,**record});count+=1
                                if kind=='relation':work.execute('INSERT INTO evidence_relations VALUES (?)',(oid,))
                    evidence_counts[kind]=count
                count=0
                for edge in work.execute("SELECT s.* FROM segments s WHERE EXISTS (SELECT 1 FROM membership m WHERE m.kind='segment' AND m.source_id=s.segment_id) ORDER BY length(s.way_id),s.way_id,s.sequence"):
                    row=dict(edge);nodes=node_rows(source,[row['from_node_id'],row['to_node_id']]);row['entity_type']='segment';row['coordinates_lon_lat']=[[nodes[ref]['lon'],nodes[ref]['lat']] for ref in (row['from_node_id'],row['to_node_id'])]
                    evidence_line(stream,row);count+=1
                evidence_counts['segment']=count
            if any(evidence_counts[kind]!=counts[kind] for kind in counts):raise ValueError('Selected evidence/rendered count mismatch')
            evidence_hash=digest.hexdigest()
        else:
            evidence_counts,evidence_hash=_write_evidence(extraction,gpkg,report['counts']['source_segments'],candidate/'source-evidence.jsonl')
            if any(evidence_counts[kind]!=expected[kind] for kind in expected) or evidence_counts['relation']!=report['counts']['source_relations']:raise ValueError('Evidence counts mismatch')
        if verify_evidence(candidate/'source-evidence.jsonl',source,work,evidence_counts)!=evidence_hash:raise ValueError('Evidence semantic hash mismatch')
        with gzip.GzipFile(filename=str(candidate/'omitted-features.jsonl.gz'),mode='wb',mtime=0) as stream:
            for kind,table,key in (('node','source_nodes','osm_id'),('way','source_ways','osm_id'),('segment','source_segments','segment_id')):
                actual=0
                for row in source.execute('SELECT '+key+' FROM '+table+' ORDER BY length('+key+'),'+key):
                    if work.execute('SELECT 1 FROM membership WHERE kind=? AND source_id=? LIMIT 1',(kind,row[0])).fetchone():continue
                    stream.write((json.dumps({'entity_type':kind,'source_id':row[0],'reason':'outside selected case closure; retained in full parent products'},sort_keys=True,separators=(',',':'))+'\n').encode('utf-8'));actual+=1
                if actual!=omitted[kind]:raise ValueError('Omission list/count mismatch')
            if args.case_only:
                actual=0
                for row in source.execute('SELECT osm_id FROM source_relations ORDER BY length(osm_id),osm_id'):
                    if work.execute('SELECT 1 FROM evidence_relations WHERE source_id=?',(row[0],)).fetchone():continue
                    stream.write((json.dumps({'entity_type':'relation','source_id':row[0],'reason':'not touching displayed case objects; retained in full parent canonical evidence'},sort_keys=True,separators=(',',':'))+'\n').encode('utf-8'));actual+=1
                if actual!=report['counts']['source_relations']-evidence_counts['relation']:raise ValueError('Omitted relation evidence count mismatch')
        with (candidate/'review-cases.csv').open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(cases[0]));writer.writeheader();writer.writerows(cases)
        shutil.copyfile(candidate/'review-cases.csv',candidate/'review-observations-template.csv')
        shutil.copyfile(args.cases/'case-source-evidence.jsonl',candidate/'case-source-evidence.jsonl')
        shutil.copyfile(args.acceptance,candidate/'source-acceptance.json')
        (candidate/'README.md').write_text('# Regional Google Earth review set\n\nPackage ID: `'+package_id+'`. Dataset kind: **'+args.dataset_kind+'**. Scope: '+scope+'. Individual network files are delivery views, not routing networks.\n\n1. Open `source-network-inspection.kmz` using Google Earth Local KML. It contains navigation cases and coverage outlines.\n2. In `review-cases.csv`, read the `kmz_files` column for your case and open those files from the same folder. Keep the overview open; open only the needed network parts to limit clutter.\n3. Inspect source IDs through the folder list. Shared source nodes may appear in multiple files with identical coordinates/tags; the membership index explicitly flags these copies. Included ways and segments were not split, clipped or simplified. Objects excluded from a partial view are listed individually in omitted-features.jsonl.gz.\n4. Record observations in a separate copy of the observation template. All regional manual checks remain not_run.\n\n`feature-membership.jsonl` maps every displayed source node, way and segment to its file(s). `source-evidence.jsonl` retains the displayed node/way/segment evidence and touching relation records for partial views (all records for a complete set). Relation resolved flags refer to the complete parent canonical subset, not to map-file membership. Full parent canonical JSONL and GeoPackage retain all source objects. Geometries are ground-clamped and do not establish walking eligibility or connectivity by appearance.\n\nSource: OpenStreetMap contributors, Geofabrik extract; ODbL 1.0 reference https://opendatacommons.org/licenses/odbl/1-0/. See source-acceptance.json for local provenance limitations. This is a local prototype review set; publication is not authorized.\n\nGrid anchors only assign whole ways to files. Long features may extend beyond their anchor cell. Diagnostic pins are selected reported examples; the full GeoPackage report retains diagnostic counts and examples. Missing case criteria are listed in the manifest and are not regional absence claims. No cloud import is required.\n',encoding='utf-8')
        with (candidate/'README.md').open('a',encoding='utf-8') as stream:
            stream.write('\nComplete parent canonical directory: `'+extraction.relative_to(config.repo_root).as_posix()+'`. Full GeoPackage: `'+gpkg.relative_to(config.repo_root).as_posix()+'`.\n')
        if sha256_file(gpkg)!=report['output']['sha256'] or sha256_file(parent_report)!=case_manifest['export_report_sha256']:raise ValueError('GeoPackage or report changed during delivery')
        _validate_extraction(config,extraction)
        if sha256_file(args.acceptance)!=acceptance_hash or sha256_file(case_manifest_path)!=case_manifest_hash:raise ValueError('Acceptance or case manifest changed during delivery')
        for name,record in case_manifest['files'].items():
            if sha256_file(args.cases/name)!=record['sha256']:raise ValueError('Case inputs changed during delivery')
        if sha256_file(Path(__file__))!=args.script_hash:raise ValueError('Delivery adapter changed while running')
        work.commit()
        payloads={path.name:{'bytes':path.stat().st_size,'sha256':sha256_file(path)} for path in candidate.iterdir() if path.is_file() and not path.name.startswith('.')}
        if sum(record['bytes'] for record in payloads.values())>MAX_PAYLOAD_BYTES:raise ValueError('Aggregate payload exceeds byte limit; nothing was omitted')
        manifest={'delivery_version':VERSION,'package_id':package_id,'dataset_kind':args.dataset_kind,'status':'complete','scope':scope,'partial':args.case_only,'requested_way_count':len(requested_ways),'requested_node_count':len(requested_nodes),'parent_pipeline_code_identity':identity['sha256'],'delivery_script_sha256':args.script_hash,'case_selector_sha256':case_manifest['review_script_sha256'],'configuration_sha256':sha256_file(config.config_path),'source':metadata['source'],'source_acceptance_sha256':sha256_file(args.acceptance),'extraction_directory':str(extraction.relative_to(config.repo_root)).replace('\\','/'),'extraction_metadata_sha256':sha256_file(extraction/'extraction.json'),'geopackage_path':str(gpkg.relative_to(config.repo_root)).replace('\\','/'),'geopackage_sha256':report['output']['sha256'],'export_report_sha256':sha256_file(parent_report),'unique_counts':{**counts,'relation':evidence_counts['relation']},'relation_resolved_flag_scope':'complete parent canonical subset, not this partial display','parent_canonical_files':metadata['files'],'source_evidence_semantic_sha256':evidence_hash,'coverage':metadata['coverage'],'partition_anchor_bounds':list(config.extract_bbox),'partition_method':info['partition_method'],'grid_cells_per_axis':args.grid,'parts':parts,'duplicated_node_ids':duplicate_nodes,'parent_unique_counts':{**expected,'relation':report['counts']['source_relations']},'source_evidence_counts':evidence_counts,'omitted_evidence_relation_count':report['counts']['source_relations']-evidence_counts['relation'],'omitted_geometry_counts':omitted,'source_ways_or_segments_omitted':omitted['way']+omitted['segment'],'source_nodes_omitted':omitted['node'],'manual_review_status':'not_run','case_count':len(cases),'missing_cases':case_manifest['missing_cases'],'limits':{'hard_placemarks_per_kmz':MAX_PLACEMARKS,'hard_vertices_per_kmz':MAX_VERTICES,'network_placemarks_per_kmz':args.network_cap,'network_vertices_per_kmz':args.vertex_cap,'aggregate_payload_bytes':MAX_PAYLOAD_BYTES},'checks':{'all_kmz_reopened':True,'unique_counts_reconciled':True,'exact_ids_tags_refs_coordinates_lengths':True,'membership_reconciled':True,'whole_way_groups_preserved':True,'limits_respected':True,'no_network_resources':True},'files':payloads}
        _atomic_json(candidate/'inspection-manifest.json',manifest)
        return manifest
    finally:
        source.close();work.close();db_path.unlink(missing_ok=True)
        if (candidate/'icons').exists():
            for path in (candidate/'icons').iterdir():path.unlink()
            (candidate/'icons').rmdir()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True);parser.add_argument('--export',dest='export_dir',type=Path,required=True);parser.add_argument('--cases',type=Path,required=True);parser.add_argument('--acceptance',type=Path,required=True)
    parser.add_argument('--case-only',action='store_true',help='Render only case IDs and their complete source-way/node closure; declare every omitted object')
    parser.add_argument('--dataset-kind',choices=('synthetic','regional'),required=True)
    parser.add_argument('--network-cap',type=int,default=9000);parser.add_argument('--vertex-cap',type=int,default=240000);parser.add_argument('--grid',type=int,default=4)
    parser.add_argument('--worker',action='store_true');parser.add_argument('--candidate',type=Path);parser.add_argument('--result',type=Path);parser.add_argument('--package-id');parser.add_argument('--script-hash')
    args=parser.parse_args()
    if not 1<=args.network_cap<=MAX_PLACEMARKS or not 2<=args.vertex_cap<=MAX_VERTICES or not 1<=args.grid<=32:raise ValueError('Invalid delivery limits/grid')
    if args.worker:
        try:
            manifest=build(args,args.candidate,args.package_id);_atomic_json(args.result,{'status':'complete','manifest_sha256':sha256_file(args.candidate/'inspection-manifest.json')});return 0
        except Exception as error:
            _atomic_json(args.result,{'status':'fail','error':str(error)});raise
    config=load_config(args.config);package_id=('synthetic-review-' if args.dataset_kind=='synthetic' else 'regional-review-')+datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    stage=config.repo_root/'data/staging/prototype'/package_id;final=config.output_root/package_id;candidate=stage/'candidate';stage.mkdir(parents=True,exist_ok=False)
    result=stage/'worker-result.json';script_hash=sha256_file(Path(__file__))
    command=[sys.executable,str(Path(__file__).resolve()),'--config',str(args.config.resolve()),'--export',str(args.export_dir.resolve()),'--cases',str(args.cases.resolve()),'--acceptance',str(args.acceptance.resolve()),'--dataset-kind',args.dataset_kind,'--network-cap',str(args.network_cap),'--vertex-cap',str(args.vertex_cap),'--grid',str(args.grid),'--worker','--candidate',str(candidate),'--result',str(result),'--package-id',package_id,'--script-hash',script_hash]
    if args.case_only:command.append('--case-only')
    from flm_pipeline.cli import _supervise
    supervised=None;promoted=False
    try:
        supervised=_supervise(command,config.repo_root,stage/'delivery-worker.log',config.limit_seconds,config.limit_rss_bytes)
        outcome=json.loads(result.read_text(encoding='utf-8')) if result.is_file() else {}
        if not isinstance(outcome,dict) or supervised['exit_code']!=0 or supervised['failure_reason'] or not supervised['child_cleanup_complete'] or outcome.get('status')!='complete':
            raise ValueError(str(outcome.get('error',supervised['failure_reason'])) if isinstance(outcome,dict) else 'Invalid worker result')
        manifest_path=candidate/'inspection-manifest.json'
        if sha256_file(manifest_path)!=outcome['manifest_sha256'] or sha256_file(Path(__file__))!=script_hash:raise ValueError('Validated delivery identity changed')
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        report={'delivery_version':VERSION,'status':'pass','dataset_kind':args.dataset_kind,'package_id':package_id,'manifest_sha256':sha256_file(manifest_path),'worker':supervised,'output_directory':final.relative_to(config.repo_root).as_posix(),'unique_counts':manifest['unique_counts'],'kmz_file_count':len(manifest['parts']),'partial':manifest['partial'],'omitted_geometry_counts':manifest['omitted_geometry_counts'],'manual_review_status':'not_run'}
        final.parent.mkdir(parents=True,exist_ok=True)
        if final.exists():raise FileExistsError('Refusing to replace delivery')
        _promote(candidate,final);promoted=True
        _atomic_json(final/'run-report.json',report)
        print(json.dumps(report,indent=2));return 0
    except Exception as error:
        rollback_error=None
        if promoted and final.exists():
            try:_promote(final,candidate)
            except OSError as failure:rollback_error=str(failure)
        failed={'delivery_version':VERSION,'status':'fail','dataset_kind':args.dataset_kind,'package_id':package_id,'worker':supervised,'error':str(error),'rollback_error':rollback_error}
        _atomic_json(stage/'run-report.json',failed);print(json.dumps(failed,indent=2));return 1



if __name__=='__main__':raise SystemExit(main())

from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET

import pytest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'pipeline/tests'))
from test_extractor import _write_pbf, _prepare_inputs
from flm_pipeline import cli
from flm_pipeline.extractor import sha256_file
from flm_pipeline.gpkg_export import export_extraction

TOOL=ROOT/'pipeline/tools/regional_inspection_delivery.py'
NS={'k':'http://www.opengis.net/kml/2.2'}

@pytest.fixture(scope='module')
def inputs():
    with tempfile.TemporaryDirectory(prefix='delivery-test-',dir=ROOT/'data/staging/prototype') as raw:
        root=Path(raw);pbf=root/'fixture.osm.pbf'
        _write_pbf(pbf,nodes=[(1,(0.5,1),{}),(2,(1,1),{}),(3,(1.5,1),{}),(4,(1,1),{}),(5,(1,1.5),{}),(8,(3,1),{}),(9,(0.25,0.25),{}),(9007199254740993,(0.25,1.75),{'name':'large-id'})],ways=[(10,[1,2,3,8],{'highway':'residential','custom:key':'','note':'café & <trail> ]]>','bridge':'yes'}),(11,[4,5],{'highway':'footway','tunnel':'yes'}),(14,[2,2,9],{'highway':'footway'})],relations=[(20,[('w',10,'included'),('w',11,'parent-resolved-but-not-displayed'),('n',999,'unresolved')],{'type':'route'}),(21,[('w',11,'outside-case')],{'type':'route'})])
        config,inventory,inventory_report=_prepare_inputs(root,pbf)
        code,extracted=cli.extract(config,inventory,inventory_report);assert code==0,extracted
        code,exported=export_extraction(config,ROOT/extracted['output_directory']);assert code==0,exported
        export_dir=(ROOT/exported['run_report']).parent
        report=json.loads((export_dir/'run-report.json').read_text())
        cases=root/'cases';cases.mkdir()
        rows=[{'case_id':'FIX-01','place':'Shared node with repeated reference','longitude':'1','latitude':'1','source_ids':'node/2','selection_criteria':'Hand-specified fixture node','expected_observation':'Source ways 10 and 14 share node 2; way 11 uses distinct coincident node 4.','status':'not_run'},{'case_id':'FIX-02','place':'Large ID','longitude':'0.25','latitude':'1.75','source_ids':'node/9007199254740993','selection_criteria':'Hand-specified standalone node','expected_observation':'ID stays exact text.','status':'not_run'}]
        for filename in ('review-cases.csv','review-observations-template.csv'):
            with (cases/filename).open('w',encoding='utf-8-sig',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        (cases/'case-source-evidence.jsonl').write_text('{}\n',encoding='utf-8')
        manifest={'geopackage_sha256':report['output']['sha256'],'export_report_sha256':sha256_file(export_dir/'run-report.json'),'review_script_sha256':sha256_file(Path(__file__)),'missing_cases':[],'files':{name:{'bytes':(cases/name).stat().st_size,'sha256':sha256_file(cases/name)} for name in ('review-cases.csv','review-observations-template.csv','case-source-evidence.jsonl')}}
        (cases/'review-dispatch-manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        acceptance=root/'acceptance.json';acceptance.write_text(json.dumps({'sha256':report['source']['sha256'],'scope':'synthetic fixture'}),encoding='utf-8')
        yield config,export_dir,cases,acceptance


def run(inputs,cap=10,acceptance=None):
    config,export_dir,cases,source_acceptance=inputs
    command=[sys.executable,str(TOOL),'--config',str(config),'--export',str(export_dir),'--cases',str(cases),'--acceptance',str(acceptance or source_acceptance),'--dataset-kind','synthetic','--case-only','--grid','1','--network-cap',str(cap),'--vertex-cap','14']
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,check=False)
    return result.returncode,json.loads(result.stdout)


def signature(folder):
    rows=[]
    for path in sorted(folder.glob('case-network-*.kmz')):
        with zipfile.ZipFile(path) as archive:root=ET.fromstring(archive.read('doc.kml'))
        for feature in root.findall('.//k:Placemark',NS):
            fields={item.get('name'):item.findtext('k:value',namespaces=NS) for item in feature.findall('k:ExtendedData/k:Data',NS) if item.get('name')!='package_id'}
            rows.append((path.name,feature.findtext('k:name',namespaces=NS),json.dumps(fields,sort_keys=True),tuple(node.text for node in feature.findall('.//k:coordinates',NS))))
    return sorted(rows)


def test_partial_delivery_preserves_closure_and_declares_exclusions(inputs):
    code,result=run(inputs);assert code==0,result
    folder=ROOT/result['output_directory'];manifest=json.loads((folder/'inspection-manifest.json').read_text())
    assert manifest['partial'] is True and 'partial' in manifest['scope']
    assert manifest['unique_counts']=={'node':6,'way':2,'segment':5,'relation':1}
    assert manifest['parent_unique_counts']=={'node':8,'way':3,'segment':6,'relation':2}
    assert manifest['omitted_geometry_counts']=={'node':2,'way':1,'segment':1}
    evidence=[json.loads(line) for line in (folder/'source-evidence.jsonl').read_text(encoding='utf-8').splitlines()]
    assert any(row.get('osm_id')=='9007199254740993' for row in evidence)
    way=next(row for row in evidence if row['entity_type']=='way' and row['osm_id']=='10')
    assert way['node_refs']==['1','2','3','8'] and way['tags']['custom:key']=='' and way['tags']['note']=='café & <trail> ]]>'
    relation=next(row for row in evidence if row['entity_type']=='relation')
    assert relation['members'][1]['ref']=='11' and relation['members'][1]['resolved'] is True
    assert relation['members'][2]['resolved'] is False
    with gzip.open(folder/'omitted-features.jsonl.gz','rt',encoding='utf-8') as stream:omitted=[json.loads(line) for line in stream]
    assert {(r['entity_type'],r['source_id']) for r in omitted}=={('node','4'),('node','5'),('way','11'),('segment','way/11/segment/0'),('relation','21')}
    members=[json.loads(line) for line in (folder/'feature-membership.jsonl').read_text().splitlines()]
    assert any(row['source_id']=='2' and row['duplicated_across_files'] for row in members)
    memberships={(r['entity_type'],r['source_id'],r['kmz_file']) for r in members}
    for row in members:
        if row['entity_type']=='way':
            refs={'10':['1','2','3','8'],'14':['2','2','9']}[row['source_id']]
            assert all(('node',ref,row['kmz_file']) in memberships for ref in refs)
    assert all(part['placemarks']<=10 and part['vertices']<=14 for part in manifest['parts'] if part['anchor_cell'] is not None)
    for name,record in manifest['files'].items():assert sha256_file(folder/name)==record['sha256']
    assert manifest['delivery_script_sha256']==sha256_file(TOOL)
    assert 'partial' in (folder/'README.md').read_text().lower()
    code,repeated=run(inputs);assert code==0,repeated
    other=ROOT/repeated['output_directory'];second=json.loads((other/'inspection-manifest.json').read_text())
    assert manifest['source_evidence_semantic_sha256']==second['source_evidence_semantic_sha256']
    assert signature(folder)==signature(other)
    assert sha256_file(folder/'omitted-features.jsonl.gz')==sha256_file(other/'omitted-features.jsonl.gz')


def test_whole_way_too_large_fails_without_promotion(inputs):
    code,result=run(inputs,cap=3)
    assert code!=0 and result['status']=='fail' and 'whole source-way' in result['error']
    config=inputs[0]
    from flm_pipeline.config import load_config
    assert not (load_config(config).output_root/result['package_id']).exists()


def test_wrong_acceptance_hash_rejected(inputs):
    wrong=inputs[3].with_name('wrong-acceptance.json');wrong.write_text(json.dumps({'sha256':'0'*64}),encoding='utf-8')
    code,result=run(inputs,acceptance=wrong)
    assert code!=0 and result['status']=='fail' and 'acceptance' in result['error']

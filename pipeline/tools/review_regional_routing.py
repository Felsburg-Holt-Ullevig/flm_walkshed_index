"""Independent frozen arc and GIS audit for Task 4.5; no production traversal imports."""
import hashlib, heapq, json, math, sqlite3, time
from pathlib import Path
from collections import defaultdict
from pyproj import Geod
ROOT=Path(__file__).resolve().parents[2]
def audit():
 start=time.perf_counter()
 h=json.loads((ROOT/'docs/planning/2026-11-02/active-regional-run.json').read_text(encoding='utf-8'))
 graph=ROOT/h['graph_directory']
 out=(ROOT/h['task_4_4_regional_report']).parent
 report=json.loads((out/'run-report.json').read_text())
 assert hashlib.sha256((out/'run-report.json').read_bytes()).hexdigest()==h['task_4_4_regional_report_sha256']
 for name,meta in report['output_files'].items(): assert hashlib.sha256((out/name).read_bytes()).hexdigest()==meta['sha256']
 adj=defaultdict(list); arc_count=0
 for line in (graph/'arcs.jsonl').open(encoding='utf-8'):
  a=json.loads(line); adj[a['from_node_id']].append((a['to_node_id'],a['base_seconds'])); arc_count+=1
 origin=report['primary_origin']['source_node_id']; distances={origin:0.0}; queue=[(0.0,origin)]
 while queue:
  cost,node=heapq.heappop(queue)
  if cost!=distances[node]: continue
  for target,weight in adj[node]:
   proposed=cost+weight
   if proposed<=600 and proposed<distances.get(target,math.inf):
    distances[target]=proposed; heapq.heappush(queue,(proposed,target))
 db=sqlite3.connect(f'file:{(out/"routing-inspection.gpkg").as_posix()}?mode=ro',uri=True)
 exported=dict(db.execute('select node_id,seconds from reached_nodes'))
 assert distances.keys()==exported.keys()
 max_error=max(abs(distances[n]-exported[n]) for n in distances); assert max_error<=1e-9
 actual=defaultdict(list)
 for row in db.execute('select candidate_id,from_offset_ft,to_offset_ft,seconds_at_from_offset,seconds_at_to_offset from reachable_edge_portions'):
  actual[row[0]].append(row[1:])
 expected={}; chosen={}; endpoint_error=0.0
 for line in (graph/'segments.jsonl').open(encoding='utf-8'):
  s=json.loads(line)
  if not s['routing_ready']: continue
  length=s['length_ft']; a=s['from_node_id']; b=s['to_node_id']; portions=[]
  if s['direction'] in ('both','forward') and a in distances: portions.append((0,min(length,(600-distances[a])/0.24384)))
  if s['direction'] in ('both','reverse') and b in distances: portions.append((max(0,length-(600-distances[b])/0.24384),length))
  merged=[]
  for lo,hi in sorted(portions):
   if hi<=lo: continue
   if merged and lo<=merged[-1][1]: merged[-1]=(merged[-1][0],max(hi,merged[-1][1]))
   else: merged.append((lo,hi))
  if not merged: continue
  cid=s['candidate_id']; expected[cid]=merged; chosen[cid]=s
  assert len(actual[cid])==len(merged)
  for observed,want in zip(sorted(actual[cid]),merged):
   assert max(abs(observed[i]-want[i]) for i in (0,1))<=1e-8
   for offset,stored in [(observed[0],observed[2]),(observed[1],observed[3])]:
    costs=[]
    if a in distances and s['direction'] in ('both','forward'): costs.append(distances[a]+offset*0.24384)
    if b in distances and s['direction'] in ('both','reverse'): costs.append(distances[b]+(length-offset)*0.24384)
    endpoint_error=max(endpoint_error,abs(min(costs)-stored))
 assert expected.keys()==actual.keys(); assert endpoint_error<=1e-9
 refs={}; wanted={s['way_id'] for s in chosen.values()}
 extraction=ROOT/h['extraction_directory']
 for line in (extraction/'ways.jsonl').open(encoding='utf-8'):
  way=json.loads(line)
  if way['osm_id'] in wanted: refs[way['osm_id']]=way
 key='node_refs' if 'node_refs' in next(iter(refs.values())) else 'node_ids'
 for s in chosen.values():
  nodes=refs[s['way_id']][key]; i=s['sequence']; assert nodes[i]==s['from_node_id'] and nodes[i+1]==s['to_node_id']
 import pyogrio
 geod=Geod(ellps='WGS84')
 edges=pyogrio.read_dataframe(out/'routing-inspection.gpkg',layer='reachable_edge_portions')
 geometry_error=max(abs(geod.geometry_length(row.geometry)/0.3048-row.length_ft) for row in edges.itertuples())
 assert geometry_error<1e-5
 points=pyogrio.read_dataframe(out/'routing-inspection.gpkg',layer='reached_nodes')
 points={row.node_id:row.geometry for row in points.itertuples()}
 source_points=0
 for line in (extraction/'nodes.jsonl').open(encoding='utf-8'):
  node=json.loads(line)
  if node['osm_id'] in points:
   point=points[node['osm_id']]
   assert abs(point.x-node['lon'])<1e-12 and abs(point.y-node['lat'])<1e-12
   source_points+=1
 assert source_points==len(points)
 result={'status':'pass','input_report_sha256':h['task_4_4_regional_report_sha256'],'arc_count':arc_count,'independent_reached_nodes':len(distances),'max_node_seconds_error':max_error,'reachable_candidate_count':len(expected),'interval_count':sum(map(len,expected.values())),'max_endpoint_seconds_error':endpoint_error,'source_ordered_pairs_verified':len(chosen),'source_ways_verified':len(refs),'unique_length_ft':math.fsum(hi-lo for intervals in expected.values() for lo,hi in intervals),'source_node_coordinates_verified':source_points,'max_exported_geometry_length_error_ft':geometry_error,'elapsed_seconds':time.perf_counter()-start,'visual_GIS_review':'not_run','coverage':'not_established'}
 target=ROOT/'docs/planning/2026-11-02/task-4.5-independent-checks.json'; target.write_text(json.dumps(result,indent=2)+'\n'); print(json.dumps(result,indent=2))
if __name__=='__main__': audit()

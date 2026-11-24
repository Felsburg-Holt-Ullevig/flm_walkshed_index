# Larimer compact export

`tools/compact_larimer_network.py` consumes the verified inclusive Larimer
GeoPackage and writes a separate `larimer_pedestrian_network_compact.gpkg`
with `pedestrian_edges` and `pedestrian_nodes` layers. The input is never
overwritten. `compact-build-report.json` records input/output counts, hashes,
length reconciliation, simplification rollbacks, and pruning evidence.

## Compaction rule

Edges are joined only through a shared source node whose remaining undirected
degree is exactly two and whose non-identity attributes match, including
`name`, `highway`, sidewalk fields, direction, and any `access` field present
in the input. Source node IDs, rather than coordinate coincidence, define
topology; therefore junctions, dead ends, barriers, and grade crossings are
preserved. A chain keeps its source orientation and one-way direction. The
output `length_ft` is the exact sum of source lengths, and
`source_segment_ids`/`source_way_ids` retain membership.

Geometry is simplified in EPSG:26913 with a 10 international-foot tolerance,
then returned to EPSG:4326. A simplification is rolled back when it creates an
intersection absent from the unsimplified source chain. The check uses both
the original edge spatial index and already accepted simplified chains, so a
pair of nearby parallel lines cannot introduce an unobserved crossing.

## Conservative reusable pruning

With an explicit `--boundary-bbox`, a connected component is pruned only when
its total source length is strictly less than 200 feet, every edge is an
unnamed `highway=service`, and the complete component lies within the boundary
inset by 200 feet. Omitting the boundary preserves every candidate component.
This leaves components near an export edge in place rather than assuming they
continue outside the exported area. Every merged or pruned source fragment is
written with its source ID, source length, action, and exact GeoJSON geometry
to `removed-fragments.jsonl`.

With `--osm-extraction` and `--osm-classification` from the inclusive build,
the compactor also uses the original OSM service subtype and source-node
connections. It removes unnamed isolated driveway groups whose only mapped
connections outside the group are to ways excluded for walking access.
For attached driveways, drive-through lanes, and parking aisles, it removes
terminal branches while keeping all links between street, sidewalk, path, and
other retained connections. Mapped entrances, stops, and crossings protect
their connecting branches. Named ways and ways with explicit walking-access
or sidewalk evidence are also protected. The 200-foot export-edge safeguard
applies to all these rules. The deletion-only `deleted-service-segments.geojson`
records the original lines and the rule responsible for removing each one.

Add `--retain-osm-tags` to store walking-relevant original way tags on the
exported edges. These tags become part of the merge comparison, so a change
in a tag value, including a missing value, keeps the neighboring edges
separate. The resulting GeoPackage still has only the edges and nodes layers.
The build report lists the exported fields and their original OSM keys.

## Rebuild the tagged GeoPackage

Use the [pipeline environment](README.md) and run the commands from the
repository root. Start with an inventory and [canonical extraction](extractor-implementation-brief.md)
from the November 1, 2026 OpenStreetMap Colorado snapshot. For this build,
the 2025 TIGER/Line Larimer County bounds were buffered for extraction to
`-106.2067714412 40.2492314508 -104.9317185588 41.0069925492`.
The smaller box in the compact command is the unbuffered county bounding box
used for pruning. The output covers a county-area rectangle with neighboring
ways retained.

```powershell
$extract = 'data/generated/path-to-completed-extraction'
$work = 'data/generated/prototype/larimer-example'
$policy = 'pipeline/config/larimer-inclusive-road-pilot.toml'
python -m flm_pipeline classify --extraction $extract --policy-config $policy --output-root "$work/classification"
# Use the classification directory reported by that command.
$classified = "$work/classification/classification-run-id"
python -m flm_pipeline graph --extraction $extract --classification $classified --policy-config $policy --output-root "$work/graph"
# Use the graph run-report path reported by that command.
$graphReport = "$work/graph/graph-run-id/run-report.json"
$evidence = "$work/export-evidence.json"
@{ graph_report = $graphReport; example = @{ candidate_id = 'way/5891995/segment/0' } } |
  ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 $evidence
python pipeline/tools/export_larimer_network.py --phase1-verification $evidence --destination "$work/inclusive"
python pipeline/tools/compact_larimer_network.py --inclusive "$work/inclusive/larimer_pedestrian_network.gpkg" --destination "$work/tagged" --boundary-bbox -106.195438 40.257784 -104.943052 40.998440 --osm-extraction $extract --osm-classification $classified --retain-osm-tags
```

Use the recorded county bounds for pruning. The example candidate is an
included segment checked during the original Larimer export. When changing
source snapshots, choose an included candidate from the new graph.

## Verified local result

The recommended GIS handoff is the standalone tagged build with 164,793
edges, 120,760 nodes, and 32 additional OSM tag columns. It occupies 92.6 MB.
Both layers reopened, all endpoints resolved, and the exported tag values
matched the original ways for every edge. The tagged and prior compact
builds removed the same 55,538 source segments. The Crestmore Place
street-to-sidewalk connection was retained. The earlier compact build
remains a size comparison, and the separate audit copy shows original line
pieces and full way-tag JSON.

The hosted ArcGIS round trip was set aside. Walkshed polygons have yet to be
recomputed against this export. Statewide methodology and data publication
are separate decisions.

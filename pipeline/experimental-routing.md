# Experimental reference traversal

Implemented November 4, 2026. Version: `experimental-reachability-1` (Python API,
not a browser release schema). Accepted reference/spec/configuration hashes are
unchanged. These are provisional general pedestrian references. Authoritative
browser calculations remain reserved for `src/domain/`.

## Computational API

`flm_pipeline.routing` has no GIS or file dependencies. `Segment` contains an
included source candidate ID, original start/end node IDs, international-foot
length and `both`, `forward` or `reverse` direction. IDs are strings. Parallel
candidates remain distinct. Zero-length or same-node segments cannot enter this
layer. Constructors reject malformed inputs.

`traverse(segments, origin, budget_seconds, seconds_per_foot, readiness)` uses
deterministic bounded Dijkstra and partial segment interval unions. The accepted
speed gives exactly `0.24384` seconds per foot. No tolerance increases a budget.
Costs remain unrounded. Invalid numerical inputs, duplicate IDs, unsupported
directions and invalid origins return `failed`. Adapter/constructor errors raise;
the future runner must catch them and prevent promotion.

`Origin` selects either a source node or a source candidate with along-segment
offset and separate access distance. Interior injection affects that candidate
only, with endpoint seeds permitted by its direction. Exact endpoint projections
enter the actual source node and its incident allowed arcs. Interior projections
never create junctions to crossing or coincident candidates. Paths can later
reenter the original endpoints. Access consumes budget at the same speed and
remains separate from network length.

Each segment receives reachable intervals from allowed endpoints and any virtual
origin. Both endpoints being reached does not imply its middle was reached.
Intervals merge only when touching or overlapping; every positive gap remains.
Reverse arcs count once per source segment. Distinct parallel candidates count
separately. `combined_intervals` unions by candidate ID across origins and rejects
unexecuted results. Its caller must establish shared graph/settings provenance.

## Geometry and snapping

`routing_geometry` separates PyProj operations from traversal. Planar input is
explicitly Cartesian international feet. Geographic input is WGS84 longitude/
latitude. Geodesic lengths divide meters by exactly 0.3048. Geometry and segment
length must agree. `interpolate` returns an original-source-oriented point at an
offset, including a clipped interval endpoint.

`snap_origin` scans every included candidate supplied by the graph adapter. It
uses no index or projected cutoff that could omit an allowed candidate. Unknown
and excluded candidates are absent. Defaults are maximum distance 100 feet and
ambiguity threshold 0.01 foot. Geographic projection minimizes distance to the
source pair's WGS84 shortest geodesic using a global interval search with
triangle-inequality lower bounds, subdividing surviving intervals to at most
0.001 foot along the segment. It does not assume a unimodal distance function.
More than 500,000 subdivisions raises an error. This exhaustive implementation
prioritizes correctness; regional edge-snap performance is unmeasured. Normal
PyProj precision applies.

The snap record retains status, every competing candidate/projection, selected
candidate, offset, coordinate, connector distance and the warning
`geometric_experiment_not_verified_walkable_access`. A connector proves neither
walkable access nor an entrance. Competing IDs are sorted. Four floating-point
ULPs account for subtraction roundoff at the tie threshold without increasing
the maximum distance or travel budget. Coalesce only exact projections onto the
same source-node ID. Unrelated coincident IDs remain ambiguous. Explicit selection
must name a nearest competing allowed candidate; an invalid choice raises.

## Result format and failures

`Result` contains computation status, origin status, policy readiness, coverage
readiness, blockers, reached-node seconds, candidate interval unions, unique
source length, connector feet/seconds, network-origin reachability and frontier
evidence. `intervals_ft` maps source candidate IDs to ordered `[low_ft, high_ft]`
pairs in original orientation. Serialized dataclass tuples become JSON arrays.
Node seconds include connector cost. `frontier` maps IDs to remaining seconds,
including zero. A future run report must attach units and provenance.

| Condition | Outcome |
|---|---|
| Outside declared usable domain | `out_of_coverage`; null costs/intervals |
| Empty graph or named source node absent | `no_network`; null costs/intervals |
| No included projection within limit | snap `off_network`; no traversal |
| Conflicting nearest source identities | snap `ambiguous_origin`; no traversal |
| Invalid input, failed hashes/schema | raised error or traversal `failed`; no promotion |
| Access cost exceeds budget | `budget_exhausted_before_network`; empty executed intervals, network point unreached |
| Access cost equals budget | network origin reached, zero positive network length |
| Unknown candidates/restriction blockers | `incomplete`; retain intervals and blockers |
| Frontier reached with remaining budget | coverage `incomplete_coverage`; retain evidence |
| Exact-budget frontier | retain zero remaining seconds; no extension |
| Coverage unestablished | `incomplete` even without policy blockers |
| Explicitly closed synthetic universe | `synthetic_complete` when otherwise ready |

Null intervals mean unexecuted/failed; empty intervals mean executed with no
positive network length. Separate readiness fields preserve concurrent warnings.
Policy blockers take precedence in computation status, while coverage can still
say `incomplete_coverage`. The `established` coverage option is reserved for a
separately accepted argument; the graph adapter never sets it.

## Frozen graph and expanded comparison

`routing_adapter.load_graph(directory)` requires a completed versioned report,
expected files, matching streamed hashes/byte counts, recorded checks and fresh
structural validation. Historical graphs can be read without regeneration merely
because routing code changed. The returned report preserves source, policy and
upstream implementation identities. A runner must pin that report's hash and
compare accepted source/policy identities. This does not rehash raw PBF bytes or
repeat manual GIS review.

Unknown candidates, unsupported restrictions and unresolved relation members
remain blockers. Every included endpoint on/beyond the extract bbox is a
conservative frontier candidate, including complete-way overhang. This does not
find every omission. A route inside the bbox can still be incomplete; missing
bbox evidence never clears coverage. The adapter returns `not_established`.

`compare_core(original, expanded)` requires matching source bytes, policy,
verified origin and common core bbox. The caller supplies independently clipped
core observations: `candidates` (ID to source/disposition/direction evidence),
`node_seconds`, and `intervals_ft`. Include all candidate dispositions, not only
reached candidates. Retain full source offsets after clipping. Node costs compare
within 1e-9 second, interval endpoints within 1e-8 foot. Membership and interval
counts are exact. Every difference retains both values and a category. Agreement
is supporting evidence with coverage still `not_established`. The Task 4.4
regional comparison reports only agreement for its clipped common-core
observations; it does not establish complete source selection or coverage.

## Task 4.4 regional runner

`pipeline/tools/run_regional_routing.py` implements the bounded regional run and
expanded-input preparation. It accepts the ignored local handoff at
`docs/planning/2026-11-02/active-regional-run.json`. It leaves the accepted source
configuration, original graph, policy, and reference manifest unchanged. Use the
accepted speed, 600-second budget, and source node `7581419196`; this point is not
a verified station entrance and has no access connector.

Reproduce the workflow from the repository root:

```powershell
& .\.venv\Scripts\python.exe pipeline\tools\run_regional_routing.py --handoff docs\planning\2026-11-02\active-regional-run.json --prepare-expanded
& .\.venv\Scripts\python.exe pipeline\tools\run_regional_routing.py --handoff docs\planning\2026-11-02\active-regional-run.json --expanded-graph data\generated\prototype\expanded-routing\routing-graph\20261104T145245Z-4cf602bd
```

The first command makes a separate expanded-bbox configuration and runs
inventory, extraction, policy classification, and graph construction into
distinct generated directories. The second command checks accepted hashes and
graph structure, traverses both graphs, clips both results to the common core,
compares source/cost/interval evidence, and creates a GeoPackage. The script
enforces the configured process timeout and 4 GiB sampled process-tree RSS cap.

The common core is clipped in WGS84 with bounded geodesic root sampling (at most
100 feet between samples and 100,000 samples per source segment). This is an
explicit approximation for comparison, not proof that way selection is
intersection-complete. The frontier check conservatively counts included graph
endpoints on or outside each extraction bbox; it cannot identify every omitted
way. Keep coverage `not_established` even when there are no reached frontier
nodes or no common-core differences.

The 1/10/50 workload starts with the accepted source node, then deterministically
selects additional source nodes by farthest-point sampling in the common core.
Only the first is the accepted diagnostic origin. The others are performance
samples, not stations or verified entrances. The optional edge-snap experiment
is disabled by the accepted settings and was not run. Actual GIS visual review
is a separate human task; the report includes coordinates and a checklist.

Every regional result retains incomplete status because unknown candidates,
unsupported restrictions, unresolved relation members, and source coverage
remain unresolved. Outputs are diagnostic evidence and do not authorize a
complete walkshed or analytical promotion. See the ignored local Task 4.4
closeout for measured artifacts and limits.


## User-defined origin direction (November 9, 2026)

[Decision 0011](../docs/decisions/0011-user-defined-origins-and-snapping.md) specifies future coordinate-origin behavior: nearest
walkable segment position or node within 500 feet, straight-line distance
selection, full walking budget after snapping, and flagged rejection when no
candidate is within range. Successful snaps need no user-facing flag. Verified
station entrances are not a prerequisite for custom points. Implementation is
pending; the historical source-node diagnostic and 100-foot charged-access
experiments retain their original identities and expectations.

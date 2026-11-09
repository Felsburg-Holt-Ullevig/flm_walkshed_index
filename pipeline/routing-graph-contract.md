# Experimental internal routing graph

Version: `experimental-routing-graph-1`. Implemented in Task 3.3. This is an offline inspection and preparation contract, pending Gate 3 review. It is independent of NetworkX and is not the Phase 5 browser release contract. No authoritative CDOT methodology or route completeness is established.

## Inputs and provenance

The builder consumes a completed `source-network-1` extraction, a completed `pedestrian-classification-1` directory, and the accepted `pedestrian-policy-0.3` configuration. It verifies extraction completion and canonical hashes, classification output hashes and checks, the exact current classification implementation manifest, and policy/configuration hashes. It replays each candidate from source way/node tags and compares it to the recorded classification before applying geometry checks. Historical extraction implementation provenance remains recorded; graph construction does not rerun extraction or rehash the statewide PBF. Input, policy, and implementation hashes are checked again before completion.

Changed implementation or tests require a fresh classification. Old classification directories remain historical evidence. Changes to source IDs, ordered references, accepted rules or source coordinates can change the graph. Stable output identity is promised only for identical inputs, rules, configuration and implementation.

## Files and ordering

JSONL uses the source contract's canonical sorted compact UTF-8 JSON, one LF per record, no nonfinite numbers. IDs are positive decimal strings, never floating point values. Coordinates are EPSG:4326 `[longitude, latitude]`, in degrees. Length fields use international feet and time fields use seconds.

| File | Record fields and meaning |
|---|---|
| `nodes.jsonl` | `node_id`, `lon`, `lat`. Only endpoints of included candidates; sorted by numeric source node ID. Distinct IDs at identical coordinates remain distinct. |
| `segments.jsonl` | All Task 3.2 candidate fields, plus `coordinates`, `length_ft`, and `base_seconds`. Keeps `candidate_id`, `way_id`, zero-based `sequence`, source-ordered `from_node_id`/`to_node_id`, way/node dispositions, `eligibility`, `direction`, `proposed_direction`, reasons, warnings, rule/scenario IDs and `same_endpoint_id`. `geometry_check=pass` means geometry checks executed, including documented zero-length exclusion. `routing_ready` indicates local arc eligibility, not complete analytical readiness. |
| `arcs.jsonl` | `edge_id`, `candidate_id`, `way_id`, `sequence`, `direction`, `from_node_id`, `to_node_id`, `coordinates`, `length_ft`, `base_seconds`. Only included candidates produce arcs. |
| `relations-audit.jsonl` | `relation_id`, `unsupported`, `reason_codes`, `unresolved_members`, original `tags` and `members`. Retains all source relation evidence without interpreting turns or supplying access. |
| `routing.gpkg` | GIS views described below; derived from JSONL and independently reopened. |
| `run-report.json` | Completion marker: version/status, run ID, counts, source/config/rule/implementation identities, file byte counts and hashes, lengths by disposition, relation diagnostics, coverage, verification, resource observations and limitations. Its own hash is recorded by the local handoff, not recursively inside itself. |

Segments follow numeric way ID then original zero-based reference-pair sequence. Candidate ID is `way/{way_id}/segment/{sequence}`. Directed edge ID appends `/forward` or `/reverse`; forward comes first when both exist. Reverse arcs swap endpoints and reverse coordinates. Segment geometry always retains source reference order. Equal endpoints across ways do not collapse edges. Repeated/parallel source segments retain distinct IDs. No simplification, XY merge, planar noding, connectors, or manual repairs occur.

## Geometry, costs and dispositions

Compute each source pair's WGS84 ellipsoidal geodesic length with PyProj Geod, then divide by exactly 0.3048 to obtain international feet. No projected length or US survey feet enter the graph. Cost is `length_ft * 3600 / (speed_mph * 5280)`, preserving the accepted exact speed from configuration. Reopened numerical checks use relative tolerance 1e-12 and absolute tolerance 1e-9 feet/seconds, whichever is larger.

Missing references, invalid/nonfinite coordinates, invalid lengths/costs, mismatched geometry, duplicate identities, or unsupported direction values fail construction. Same endpoint ID or exactly zero geodesic length excludes the candidate with `G_ZERO_LENGTH`, including a previously unknown candidate. Excluded and unknown candidates retain length evidence and have `base_seconds=null`; missing cost never becomes zero. Only included candidates produce forward/reverse arcs according to the accepted policy. Physical barriers suppress every incident candidate; unknown nodes quarantine incident candidates under that policy.

Duplicate coordinate-pair geometries are retained. The second and later occurrences receive `W_DUPLICATE_GEOMETRY`; the report counts those occurrences once per source candidate, regardless of direction. Coordinate-pair comparison is exact and direction independent. This is a diagnostic, not a claim about physical duplication. Length totals count each source segment once per disposition; directed arcs may repeat the same length.

Times are distance-derived base travel times. Crossing delay, slope, stair and turn delays are not modeled; stairs retain the accepted same-speed warning. Permission, safety, accessibility and route completeness cannot be inferred from a structural pass.

## Relations and completeness

Any retained relation with `restriction:foot` or `restriction:foot:conditional` is unsupported, even if its value is empty or an `except` tag is present. `type=restriction` is unsupported unless the exact semicolon-delimited token `foot` occurs in `except`. No trimming or case conversion applies. Unsupported relations receive `R_UNSUPPORTED`; they do not invent turn behavior or delete arbitrary arcs. Unresolved members are counted separately as coverage warnings.

A nonempty graph is `incomplete_unknown_policy` and analytical promotion is `blocked` when any candidate remains unknown or any retained restriction is unsupported. Otherwise it is `experimental_graph_complete`, with promotion still `pending_gate_3_and_coverage_validation`. A graph with no arcs is `empty` and promotion is `blocked_empty`, with underlying unknown/relation counts retained. No status constitutes a complete walkshed. Extraction bounds and complete-way overhangs retain the source contract's coverage limitations; expanded-extract validation belongs to Phase 4.

## Inspectable GeoPackage

All layers store EPSG:4326 coordinates. `routing_nodes` stores node ID and lon/lat as Points. `routing_arcs` stores directed edge/candidate/source IDs, endpoints, direction, sequence, length in feet and base seconds as LineStrings oriented in travel direction. `candidate_audit` includes every source candidate, source-ordered geometry, eligibility, direction, sequence, length, and compact JSON text reason/warning arrays. Zero-length audit lines remain evidence and are never routing arcs. Use `relations-audit.jsonl` and the pinned canonical source files to inspect full tags and relation membership.

The adapter writes in batches of 10,000 and independently reopens all records. It compares counts, CRS, every stored field, string IDs, and every coordinate against JSONL. Empty layers are explicit. The structural validator independently reopens JSONL and verifies unique nodes/candidates, endpoint resolution, node/arc geometry, geodesic length, cost, allowed directions, exact arc membership/order and absence of unused graph nodes. Candidate replay against source policy is a separate construction check.

## Execution and failure behavior

`graph` runs its worker under the existing process-tree supervisor with a 1,200-second deadline and 4-GiB sampled RSS limit. RSS is sampled once per second, not an exact peak. Build, JSONL validation, GeoPackage writing and reopening run inside that worker. Parent promotion and final report I/O are outside the measurement. The Python `build_graph` function is a staged implementation API for tests; it does not independently supervise or promote.

Each invocation writes to a unique ignored staging directory. The parent requires successful worker completion and resource checks before promoting a validated candidate directory. It verifies promoted file hashes and writes `run-report.json` last. A directory without that report is incomplete and must not be consumed. A failed worker leaves its logs and a failure report in staging. Existing runs and raw inputs are never overwritten. No automatic retry of analytical failures occurs. The existing bounded Windows sharing-lock retry is used only for directory promotion.

Task 3.4 reviews comparison scenarios, component structure, named source differences and Gate 3. Task 4 defines and verifies station traversal. Task 5 defines cross-language schemas and a browser loader.


Policy 0.3 permits exact kerb-tagged nodes for general pedestrian traversal while retaining all other access and completeness rules. The graph file format is unchanged. Historical 0.2 artifacts retain their recorded identities and are not relabeled.


Current policy metadata explicitly records `travel_profile=general_pedestrian` and `wheelchair_accessibility=not_evaluated`. These are scope labels; source accessibility attributes are not new routing constraints or scores.

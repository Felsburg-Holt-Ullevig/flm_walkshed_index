# Experimental network package contract

Version: `flm-package-1`; graph format `flm-directed-graph-1`.
Status: experimental contract accepted; Python packaging and TypeScript browser loading implemented. Gate 5A developer acceptance remains pending.
Gate 4 is accepted only for source-node diagnostic evidence and experimental package-contract development. No coverage, verified entrance, authoritative methodology, production use or redistribution approval follows.

## Authority and files

The `.schema.json` files in this directory are the single structural authority for Python preparation and TypeScript loading. They use [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12/json-schema-core). Resolve relative schema references from this directory with an offline registry; never fetch a schema named by an input file. `common` contains shared definitions. Do not maintain handwritten Python/TypeScript field lists as competing schemas. Generate TypeScript types from these files when introducing the loader; build/check generation reproducibly and reject stale generated files. Static types do not replace runtime validation.

| Schema | Instance | Role |
|---|---|---|
| manifest | manifest.json | Completion marker and immutable file bindings |
| nodes | nodes.json | Source IDs and longitude/latitude |
| segments | segments.json | Included source pairs, source-ordered geometry, length, cost, direction |
| arcs | arcs.json | Directed references to segments; no duplicate geometry or cost payload |
| inventory | inventory.json | Source identities, provenance gaps, licenses, exclusions and unknowns; carries a stable inventory_id, not a per-run release ID, so identical semantic inputs retain the same graph ID |
| result | exported reachable result | Request, versions, independent readiness states, reached costs and source intervals |

JSON is UTF-8 without BOM; no duplicate object keys, NaN, infinity, trailing data, or coercion. Reject integers beyond JavaScript's safe range except identifiers, which are always strings. Source IDs are positive decimal strings and must never pass through numeric conversion. No XY merge or geometric crossing creates a connection. Unknown fields and schema versions fail. Version 1 accepts a single unpartitioned graph, source-node origins and zero connector cost only. Edge origins, partition references, polygons, demographics, scores and session files require later deliberate contract extensions.

Every manifest also binds a local QA JSON report, derived routing GeoPackage and UTF-8 notices file. Their paths, sizes, byte hashes and record counts are descriptors, not routing payloads. QA must record stages, actual code/environment/config identities, command outcomes, supervision, reopen checks and manual/not-run evidence using the existing pipeline run-report conventions. GIS must reopen/reconcile against package nodes, segments and arcs. Nonspatial notices have zero records. Browser loading requires manifest/nodes/segments/arcs/inventory; it need not download the GIS artifact. Offline promotion must verify every artifact. There is no ZIP/browser archive ingestion in v1.

## Spatial and travel semantics

Coordinates are EPSG:4326 `[longitude, latitude]` degrees, never latitude first. Bboxes are `[west,south,east,north]`, finite, valid geographic ranges, nonwrapping and strictly ordered. Core bounds must be inside extract bounds. Whole selected ways may overhang both boxes; never trim routing to core, map viewport or rendering extent.

All travel lengths use international feet (exactly 0.3048 meter per foot); costs and budgets use seconds. The accepted experimental cost is exactly 0.24384 seconds per foot. Geographic conversion is an adapter concern, not an implicit unit in the graph. `wgs84_geodesic_international_ft` requires independent WGS84 ellipsoidal length verification with the graph contract's maximum of absolute 1e-9 feet/seconds or relative 1e-12. `synthetic_declared_ft` deliberately uses declared metric lengths with illustrative coordinates; it is permitted only when every source is synthetic, rule/scenario are synthetic, and coverage is synthetic closed. Never apply that escape to OSM data. Accessibility is not evaluated.

Only included positive-length, distinct-endpoint source pairs enter segments. `candidate_id` must equal `way/{way_id}/segment/{sequence}` with the original zero-based source-pair sequence; filtered sequences may have gaps. Geometry has exactly two positions matching the ordered endpoint nodes. Parallel ways/candidates remain separate. Raw excluded/unknown candidates and relations remain upstream audit evidence; inventory summaries and manifest blockers retain their omission from the consumable graph.

An arc ID must be `{candidate_id}/forward` or `/reverse`. A forward arc uses the segment's source-order endpoints and geometry; a reverse arc swaps endpoints and reverses geometry. Arc length/cost are looked up from the segment. `both` requires exactly one of each arc; `forward` or `reverse` requires exactly that one arc. Missing, repeated or extra arcs fail. Every endpoint and candidate must resolve within the same release/graph; unused nodes fail. No turns, delays, restriction repair or new pedestrian-policy interpretation occurs in packaging.

## Runtime content validation

Schema validation is necessary but insufficient. Both adapters must validate these cross-file rules before exposing a graph:

1. Verify the manifest version, graph format and exact application version allowlist. The allowlist is an explicit list of compatible `major.minor.patch` versions, not a semver range. Initial fixture uses 0.1.0; later application versions require a reviewed compatibility entry. Refuse unknown versions rather than approximate a migration.
2. Resolve each simple filename against the manifest directory. Require distinct filenames, same origin and directory, no redirects outside that directory, paths, queries, fragments, encoded path tricks, symlinks or traversal. For local Python files resolve real paths and reject escapes and symlinks. Never treat a manifest text field as a URL to fetch. Source/license URLs are metadata only.
3. Enforce declared and streamed size caps before decoding/allocating; require success HTTP status and valid JSON instead of an HTML fallback. Enforce actual bytes and SHA-256, even if Content-Length is absent or incorrect. Fetch the inventory and confirm its byte hash equals both its descriptor and `identity.source_inventory_sha256`.
4. Validate all payloads with the same checked-in schemas. Reconcile exact release ID, graph ID, counts, unique IDs, endpoint membership, geometry order, candidate/arc formulas, direction and positive lengths/costs. Integer counters are nonnegative and safe; array lengths equal declared counts. Reasons must reconcile excluded/unknown source totals; do not equate source ways, source candidates and directed arcs. Record their grain in the reason text.
5. Recompute semantic graph identity below. Preserve manifest diagnostics: nonzero unknown/restriction counts require matching nonempty blockers; unresolved members require a coverage limitation. OSM readiness is always `not_established` in v1, even with zero counts or no reached frontier. No version 1 package can claim analytical promotion. Synthetic-closed status must never be copied to regional data.
6. Validate result membership, release/graph/manifest hash bindings, input origin and status consistency before accepting imported results. An arbitrary structurally valid result is untrusted: to claim routing correctness, recompute and compare to the bound graph/request. Missing/invalid inputs return an explicit failure, never zero costs or a circular buffer.

## Limits and failure behavior

These are provisional engineering caps, not measured browser capacity or a performance promise. Reducing coverage to meet them is forbidden. Report `resource_limit` and review partitioning or limits explicitly.

| Item | Hard v1 limit |
|---|---|
| Manifest | 1 MiB decoded bytes |
| Each JSON payload/result | 256 MiB decoded bytes |
| All required browser JSON including manifest | 512 MiB decoded bytes |
| Offline release including GIS/notices/QA | 4 GiB |
| Nodes / included segments / directed arcs | 600,000 / 700,000 / 1,400,000 |
| Sources / coordinate positions per segment | 32 / exactly 2 |
| JSON nesting | 32 levels |
| One result request | One source-node origin, 0–3,600 seconds |
| Browser load deadline / traversal deadline | 120 seconds each; cancellation aborts fetching and computation |
| Offline package validation | 1,200 seconds; 4 GiB sampled process-tree RSS |

The Task 5.2 local regional package records actual JSON and total package sizes in its ignored closeout. This is not a browser capacity result. Browser memory and load time remain unmeasured. Enforce byte limits before promotion; a worker does not remove browser memory limits. Keep 1-second RSS sampling and distinguish sampled peak from exact peak. Parent promotion remains outside the package-worker measurement.

| Condition | Required failure code and behavior |
|---|---|
| Unknown schema/graph/app version | `unsupported_version`; stop before graph allocation |
| Missing file, non-success response, unreadable data | `missing_file` or `fetch_failed`; discard candidate graph |
| Malformed/duplicate-key JSON, invalid field/unit/CRS | `invalid_content`; include file/field, no silent coercion |
| Wrong hash or byte length | `integrity_mismatch`; no fallback release |
| Wrong release/graph ID, semantic identity or counts | `release_mismatch`; no mixed graph |
| Broken endpoint/arc/geometry/cost | `invalid_graph`; no partial usable graph |
| Size/time/memory cap or cancellation | `resource_limit` or `cancelled`; cleanup candidate state |
| Absent origin in valid graph | `no_network`; outputs null, not a complete zero walk |

Keep a previously loaded graph/current work intact when a new candidate fails. Store errors separately and identify the failed candidate. Do not attach an old result to new settings. A complete directory requires `manifest.json` written last after validation/promotion checks; a staging directory or the illustrative manifest example is not a release. Hashes detect accidental mixing/corruption, not publisher authenticity; publication/trust remains separately controlled.

## Deterministic comparison and identity

Byte SHA-256 proves exact file identity. GeoPackage binaries, run timestamps, release IDs, environment observations and JSON formatting can differ across equivalent regeneration; compare them separately from graph semantics.

`flm-graph-semantic-1` hashes an object containing `semantic_version`, manifest `identity`, `coverage`, `diagnostics`, and the complete `nodes`, `segments`, `arcs` arrays. Sort nodes by node_id, segments by candidate_id, arcs by edge_id in ASCII lexicographic order (not numeric). Sort all object keys lexicographically; array order otherwise matters. Blockers and limitations must be deduplicated and sorted by the packager. All strings in this semantic projection must be ASCII; provenance/attribution outside it can be Unicode. Inventory uses a stable `inventory_id`, independent of release/run IDs, and its exact byte SHA is bound into graph identity. Changing bound inventory bytes changes graph identity even if some metadata appear equivalent. Source hashes/config/rule/code identities remain exact inputs.

For unambiguous cross-language serialization, recursively replace null with `["null"]`, booleans with `["bool",value]`, strings with `["string",value]`, numbers with `["number",hex]` where hex is 16 lowercase hex digits of IEEE-754 big-endian binary64 (normalize signed zero to positive zero), arrays with `["array",[tagged items]]`, and objects with `["object",[[key,tagged value],...]]` in key order. Serialize this tagged tree to compact ASCII JSON with no whitespace, newline or slash escaping. Hash its bytes with SHA-256. `pipeline/tools/package_contract_semantics.py` is the reference; TypeScript must reproduce it using DataView float64 big-endian. It does not validate schemas or a package. Exclude graph_id itself, release_id, created_at, file descriptors and evidence to avoid recursion/run-specific identity.

For numerical comparison of separately measured graphs, do not use equal digest as a tolerance test: report exact source IDs/membership/directions/statuses first, then lengths/costs with graph tolerances. Synthetic result node costs use absolute 1e-9 seconds; interval endpoints and unique lengths use absolute 1e-8 feet, with exact interval counts/membership. Never inflate traversal budget by a comparison tolerance.

## Result semantics and synthetic acceptance fixture

`pipeline/fixtures/network-package-v1/` contains schema examples and a literal expected result. Task 5.2 also builds a complete synthetic release locally with real QA, GIS and notices, and writes an ignored `_expected-results/<release-id>.json` sidecar that binds the unchanged literal expectation to that run's actual manifest hash. The synthetic release and sidecar remain ignored and are recreated by command; they are not published artifacts. Keep the numeric expectations unchanged. No browser loader exists yet; current app remains a scaffold.

The proposed one-station test is the accepted F01 metric arithmetic with positive string IDs 1=A, 2=B, 3=C. AB is 100 feet in both directions; BC is 100 feet forward only, adding a directional check. At node 1 with 36.576 seconds (150 feet equivalent): node 1 costs 0 seconds, node 2 costs 24.384 seconds, node 3 is unreached; AB interval [0,100], BC [0,50], total unique source length 150 feet. Reverse arcs never add a second copy of AB. The WGS84 coordinates are illustrative. This does not reapprove or edit the frozen Phase 4 fixtures. New browser expectations await developer acceptance of this design; existing Phase 4 arithmetic remains accepted independently.

Required directional companion: origin node 3, budget 36.576 seconds reaches only node 3 with no positive interval, since BC has no reverse arc. Required zero-budget companion: origin 1 reaches node 1 only, total zero, status synthetic complete. Required missing-origin companion: node 999 produces no_network and null outputs. These are literal expectations, not outputs generated by the algorithm under test.

Result intervals are positive, disjoint, ascending source-order offsets within each segment's [0,length_ft], unioned per candidate; touching intervals merge, positive gaps remain. Sum their differences for unique source length; never count arcs or unrelated coincident geometry as unique source identity. Endpoint reached costs are shortest network costs, not a complete continuous interior cost profile. Results with failed/no_network have null outputs and nonnull error_code; successful synthetic/incomplete results have outputs and null error_code. Empty valid outputs are distinct from null. Regional outputs are always incomplete with not-established coverage and not-verified entrance. Blockers/readiness must agree with the bound manifest. Synthetic complete requires synthetic closed/ready, no blockers, and synthetic entrance label. Reached-node costs must be within budget, with exact membership established by traversal, not tolerance.

## Implementation status

Schemas on disk remain authority. Review schema/expectation diffs; never regenerate expectations solely to clear failed tests. The production Python packager uses a hash-locked Draft 2020-12 validator and validates the schemas offline against their metaschema, in addition to cross-file identity, topology, cost, GIS and checksum checks. Python and schema dependencies, versions, hashes and licenses are recorded in the locked environment documents. Task 5.3 selects a compatible browser validator and schema-derived type generation with license and bundle-size evidence. If inventory or payload bytes change, recompute dependent descriptor hashes, semantic graph identity and result binding in dependency order, with all numerical expectations preserved and reviewed.

See [implementation briefs](../../../pipeline/package-implementation-brief.md). Task 5.2 packaging, local orchestration and synthetic CI are implemented. Runtime loading and actual synthetic browser traversal are implemented; see [local browser review](../../../pipeline/browser-network-review.md). Gate 5A acceptance remains pending.

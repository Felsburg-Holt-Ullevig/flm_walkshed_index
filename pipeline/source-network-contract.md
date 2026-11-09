# Regional source-network contract

Version: `source-network-1`. Status: prototype implementation specification, November 2, 2026; extraction and GeoPackage export are implemented and synthetically verified under tasks 2.2 and 2.3. Gate 1 is accepted for contract development with the readiness review's limitations. Source hashes remain unpinned, so no real regional source or inspection GeoPackage has been produced. This specifies source preservation, not an approved pedestrian model or a browser routing format.

## Authority and representation

The canonical regional subset consists of UTF-8, newline-delimited JSON files: `nodes.jsonl`, `ways.jsonl`, and `relations.jsonl`, accompanied by `extraction.json`. Each line is one object. No PBF writer is required. GeoPackage is a derived inspection product. A future browser boundary requires its own machine-readable schema and runtime validator; these files must not be loaded directly by the application.

Reject unknown contract versions. Readers validate fields and types at runtime. Required fields below may not be omitted or null. Extra fields require a contract revision. OSM IDs and references are positive decimal strings matching `[1-9][0-9]*`, with no leading zeros; never convert them to JavaScript numbers. Entity identity is `(entity type, osm_id)`. IDs from different entity types may coincide. Sequence indexes are zero-based integers.

| File | Required fields |
|---|---|
| nodes.jsonl | `osm_id` string; `lon`, `lat` finite numbers; `tags` string-to-string object |
| ways.jsonl | `osm_id` string; `node_refs` ordered array of ID strings; `tags` string-to-string object |
| relations.jsonl | `osm_id` string; `members` ordered array of member objects; `tags` string-to-string object |
| relation member | `type` exactly `node`, `way`, or `relation`; `ref` ID string; `role` string, including empty string; `resolved` boolean |

Copy values while reader objects are live. Retain every raw tag without normalization, case folding, trimming, interpretation, or dropping unknown keys. Empty strings are distinct from absent keys. Reject duplicate tag keys rather than silently overwriting. Preserve ordered/repeated node references and relation members. Do not retain contributor names/user IDs, changesets, or edit metadata in this subset; provenance is the source-file hash, not an edit-history export.

Required retained information includes highway values (even unknown values), `access`, `foot`, `access:*`, `foot:*`, `oneway`, `oneway:*`, `sidewalk` and all `sidewalk:*` keys, `footway`, `crossing` and `crossing:*`, `barrier`, `bridge`, `tunnel`, `layer`, `level`, `junction`, `service`, `surface`, `smoothness`, `incline`, `steps`, and conditional restrictions. These examples do not form an allowlist. Node tag maps are equally important: barriers, gates, crossings, access restrictions, and entrances must survive without interpretation. No sidewalk geometry, permission, direction, or crossing connection is inferred here.

## Inclusion and coverage

Use configured extraction bounds in longitude/latitude, inclusive on all four sides. Reject antimeridian-crossing bboxes in version 1. The core, initial extract, and expanded comparison bounds remain distinct metadata; core bounds do not filter the extract.

1. Find source nodes inside the extraction bbox with finite valid coordinates (longitude [-180,180], latitude [-90,90]).
2. Select every way with a `highway` key, including an empty value, that references at least one inside node. Do not apply pedestrian/car exclusions.
3. Retain every reference of each selected way, in source order, and resolve every referenced node even outside the bbox. Retain those nodes with all tags. Also retain every tagged inside node, including standalone barriers/crossings and nodes unrelated to a selected way. Untagged inside nodes unused by selected ways need not be emitted.
4. Retain each relation having a direct node member in retained nodes or a direct way member in selected ways. Do not expand the node/way set because of a relation. Do not recursively select relations through relation members. Copy all members/tags of each retained relation; mark membership resolution against the final emitted entity sets, including relations. An unresolved relation member is reported, not automatically fatal.

Record selection ID `highway-node-in-bbox-complete-way-1`. Complete-way means all source references and their coordinates survive, including repeated closing references and outside vertices. It does not mean spatial-intersection completeness: a way crossing the bbox with no node inside can be absent. Nor does it mean complete routes, relation completeness, or that the raw statewide source is complete. Unsupported relation-only connectivity, restrictions, multipolygons and route interpretation remain explicit limitations. A later method requiring any such relation semantics must stop for a contract review.

Invalid coordinates encountered anywhere in the node stream fail this prototype extraction conservatively; the report identifies the node and phase. A missing reference required by a selected way always fails. Do not emit a partial accepted network, invent coordinates, clip complete ways, snap nodes, or add boundary vertices. Explicitly report no selected ways as `empty`, retaining any standalone tagged nodes and their actual counts; it is not an accepted routing network.

Connectivity is determined by shared source node IDs in ordered way references. Distinct node IDs at identical coordinates stay distinct. Geometry intersections without a shared source node do not become junctions. Bridge/tunnel/layer tags remain evidence for later review; they neither create nor remove source connections at this stage. Repairs require a separately reviewed, versioned transformation with original identities preserved.

## Derived GeoPackage inspection contract

Task 2.3 implements `source-network.gpkg`. All spatial layers declare EPSG:4326, x=longitude/y=latitude. No geometry simplification. GPKG integer feature IDs are storage internals, never source identity. JSON columns below are UTF-8 JSON text, never Python repr strings. Null is not substituted for an empty map/array.

| Layer/table | Geometry | Fields beyond internal feature ID |
|---|---|---|
| source_nodes | Point | `osm_id` TEXT unique, `lon`, `lat` REAL, `tags_json` TEXT, `inside_core`, `inside_extract` integer 0/1 |
| source_ways | LineString | `osm_id` TEXT unique, `node_refs_json`, `tags_json` TEXT, `node_count` INTEGER |
| source_segments | LineString | `segment_id` TEXT unique, `way_id`, `from_node_id`, `to_node_id` TEXT; `sequence` INTEGER; `tags_json` TEXT; `length_geodesic_m`, `length_projected_m` REAL; `zero_length` integer 0/1 |
| source_relations | nonspatial | `osm_id` TEXT unique, `members_json`, `tags_json` TEXT |
| coverage | Polygon | `coverage_kind` TEXT unique (`core`, `extract`, `expanded_comparison`), `selection_id` TEXT |

Each segment is exactly references i and i+1 of a way; `segment_id` is `way/<way_id>/segment/<i>`. Direction follows source reference order, not allowed walking direction. Copy way tags onto segments; endpoint restrictions remain on nodes. Retain zero-length segments and repeated node references with diagnostics. Duplicate geometries are reported and retained. A way with fewer than two references fails extraction; a closed way with repeated first/last ID is allowed. Geometrically degenerate lines are retained for inspection with diagnostics, never silently treated as traversable edges.

Geodesic lengths use WGS84 ellipsoidal distance between endpoints in meters (`pyproj.Geod(ellps="WGS84")`). Projected diagnostic lengths use EPSG:26913 and must be labeled as such in metadata. Way geometry is the complete coordinate sequence; no way length field is required. Coordinate round-trip tolerance is 1e-9 degrees per ordinate; geodesic recomputation tolerance is max(1e-6 m, 1e-9 times length). These are serialization checks, not methodological accuracy claims. GeoPackage exports do not change canonical records or their semantic hashes.

Task 2.3 implements the `export` command for an extraction directory. It requires the same current configuration and pipeline code identity, the extraction's matching provenance/report, and a currently matching pinned OSM source hash. It writes a new run under ignored generated output and uses `run-report.json` as the export completion record. The exporter validates and reopens all five layers, enforces unique source/segment IDs, checks endpoint resolution and ordered geometries, reconciles counts, and rechecks source/config/code/input hashes before promotion. A final GeoPackage without its matching completed report is not accepted output.

Export diagnostics retain all source features. Repeated way references count each occurrence after the first within that way. A zero-length segment has zero WGS84 geodesic length. Duplicate geometry diagnostics compare exact coordinate sequences and treat their reverse as equivalent, reporting duplicate groups and extra feature counts separately for `source_ways` and `source_segments`; near-overlaps are not duplicates. Degenerate but nonempty line geometries, including zero-length segments, are retained and reported. These are prototype QA definitions and do not establish traversal eligibility.

## Provenance, reconciliation, and acceptance

`extraction.json` must contain `contract_version`, `selection_id`, `region_id`, `run_id`, UTC creation time, code revision/dirty state and code identity hash, configuration SHA-256, accepted source inventory SHA-256, source ID/path/bytes/SHA-256, core/extract/expanded bboxes, storage and inspection CRS, length method, reader/environment versions, file paths/byte hashes/semantic hashes, counts, diagnostics and limitations. Record source vintage claims separately from observed metadata, with evidence reference or null; never derive a verified year from a source role. Copy unresolved provenance and license limitations from the accepted inventory.

Counts distinguish full scanned entities, inside nodes, selected ways, emitted nodes/relations, complete way-reference total, segments, unresolved relation members by type, repeated references, zero-length segments and duplicate geometries. Never equate node-reference count with unique-node count. At task 2.2, segment/length/duplicate-geometry diagnostics not yet computed by the task 2.3 exporter are null with `not_run` status, never fabricated as zero. Task 2.3 supplies these checks in its own linked export report before accepting inspection output. Record actual coordinate extent separately from configured coverage: complete-way vertices may lie outside it. `expanded_comparison` is a configured future comparison, not evidence that expanded data was extracted.

Canonical files sort entities by numeric ID (using arbitrary-precision integers); members/references retain source order. Serialize objects with sorted keys, UTF-8 (`ensure_ascii=False`), no whitespace separators, no NaN/infinity, and one LF per record. Semantic hashes are SHA-256 over these canonical bytes; exclude run-specific metadata. The report records the canonicalization identifier `python-json-sorted-compact-1` and Python version. File/container hashes remain separate from semantic hashes. Repeated identical source/config/code runs must yield identical canonical entity bytes. The code identity hash covers a sorted manifest of repository-relative paths and SHA-256 content hashes for all pipeline source files, pyproject, lock files, and this contract, including untracked files; record that manifest beside the report. A code change invalidates reuse even if outputs happen to match.

Fail acceptance on duplicate entity IDs, malformed IDs/tags/references, invalid coordinates, selected ways with fewer than two references, missing required way nodes, nonfinite computed lengths, coordinate/reference disagreement, failed source hash verification, failed resource supervision, or incomplete writes. Diagnostics identify entity type/ID, reference sequence when applicable, reason, count, and a hashed external diagnostic file when too large for the report. Unsupported relation members are counted individually; `resolved` means present in the subset, not semantically supported. All emitted required references must resolve. Validate counts and byte/semantic hashes after reopening output before promotion.

See [extractor brief](extractor-implementation-brief.md), [synthetic cases](fixtures/source-network-cases.md), [readiness review](readiness-review.md), and [repository data boundary](../docs/data-contract.md). This contract does not approve source publication, routing, or analytical assumptions.

## Canonical reopen resource limits

Canonical validation streams one record at a time, uses a temporary disk-backed SQLite ID index with a 16 MiB page cache target, and resolves way/relation references in a second streaming pass. Each JSONL record, including its newline, is limited to 16 MiB before decoding; a larger record fails explicitly. This operational limit does not permit truncating or skipping features. PBF integer IDs are converted only at the reader boundary; canonical entity and reference IDs must already be positive decimal strings. Extract/export time and process-tree sampled RSS limits remain configured separately. Whole extraction selection sets and individual decoded records still consume memory; synthetic checks establish no statewide capacity.

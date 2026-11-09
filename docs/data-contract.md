# Data contract status and boundaries

Status: offline source and internal graph contracts are implemented experimentally. The developer accepted the [version 1 experimental package schemas](../contracts/network-package/v1/README.md), synthetic expectations and provisional limits. Task 5.2 implements offline packaging, full Python schema/cross-file validation, local promotion and synthetic CI. Task 5.3 implements synthetic browser loading and source-node reachability; Gate 5A is accepted. Regional analytical promotion remains blocked.

## Separate products

- **Display:** tiles and styles for drawing the map.
- **Routing:** connected nodes/edges, traversal costs, pedestrian eligibility, and complete boundary links.
- **Indicators:** analytical geography, metric inputs, aggregation definitions, and reference distributions.

PMTiles is a candidate display/preparation product; ordinary cartographic tiles are not assumed to contain a valid routing graph or sufficiently precise analytical geometry. The experimental browser loader consumes network packages; display tiles and indicator delivery remain separate.

## Required contract content

- **Metric definition fields:** stable ID, definition, source field, unit, data year, numerator and denominator, missing and suppressed-value policy, spatial aggregation rule, score direction, method version.
- **Release manifest fields:** release ID, schema and graph-format versions, coverage, CRS and units, source vintages, URLs and hashes, processing revision and parameters, output URLs and checksums, license and attribution references, compatible application versions, and a source inventory including skipped or rejected records with reasons.
- **Schemas:** one machine-readable schema for each cross-language boundary (JSON Schema for manifests and session files), with binary graph formats documented separately. Do not maintain two handwritten field lists.
- **Results record:** application commit, method version, data release IDs, normalization reference, analysis settings, station inputs, and session schema version.
- **Partitioned routing data:** stable boundary node and edge identity; the search continues across partitions as needed. The map viewport is never an analytical boundary.

Use immutable release paths and a small validated manifest. Publish a complete validated package before promoting its pointer, and retain the previous compatible release. Do not mix graph and indicator versions accidentally.

Define compatibility and migration behavior before introducing stored files. Runtime validation is required even where TypeScript types exist.

The first implementation should use a small reproducible fixture with provenance. Preparation tests and app-loader tests must exercise the same sample product. Refer to [methodology](methodology.md) and [validation](validation.md) before defining a schema.

## Offline source-network prototype

The [source-network-1 contract](../pipeline/source-network-contract.md) is the authority for the prototype raw regional subset and derived GeoPackage inspection layers. It preserves string source IDs, full raw tags and ordered way references; source connectivity is never inferred from geometric crossings. Its node-in-bbox selection retains complete selected highway ways but does not establish complete routes or intersection-complete coverage. Relations are retained with explicit unresolved-member diagnostics and no interpretation.

The [extractor brief](../pipeline/extractor-implementation-brief.md) and [synthetic cases](../pipeline/fixtures/source-network-cases.md) define extraction behavior and its acceptance evidence. The `extract` command writes canonical JSONL only after checking a pinned OSM hash, a matching complete inventory/run report, and current code identity. The `export` command validates that extraction provenance, writes the contract's five GeoPackage layers, and reopens them to verify IDs, fields, CRS, counts, ordered geometry, and segment lengths. Its linked report records duplicate geometries, repeated references, zero-length segments, and output hashes. This offline-only boundary is not a browser graph/release format or approved pedestrian policy. The shared discovery example remains unpinned; local accepted runs use separately supplied source pins and verified prerequisite reports.


## Experimental internal graph

The [experimental-routing-graph-1 contract](../pipeline/routing-graph-contract.md) defines offline JSONL nodes, directed arcs, all-candidate audit records, relation evidence and derived routing GeoPackage layers. Source node IDs and parallel segments remain distinct; graph lengths use international feet and base costs use seconds under accepted experimental policy 0.3. The builder validates source/classification provenance, replays policy, reopens every GIS record and blocks analytical promotion for unknown candidates or unsupported walking restrictions. This internal representation is independent of NetworkX and does not define the later browser release schema. Gate 3 is accepted for documented diagnostic limitations; station access and coverage remain unresolved.

## Experimental cross-language release design

Gate 3 is accepted for policy 0.3 diagnostic limitations. Gate 4 is accepted for limited source-node evidence and experimental package-contract development; earlier pending statements describe historical stages. Coverage and verified station entrances remain unresolved.

The [package contract](../contracts/network-package/v1/README.md) provides a single JSON Schema authority for manifest, nodes, source segments, directed arc references, source inventory and reachable results. The offline `prepare-release` command rechecks the pinned OSM bytes and accepted frozen provenance, produces GIS/QA/notices and graph JSON, runs full schema and cross-file validation, then atomically promotes a new immutable package under ignored local data storage. `validate-package` rechecks a completed package. CI builds and validates two real synthetic packages under the locked Python environment, with no statewide downloads. Each synthetic build also writes an ignored expected-result sidecar bound to the generated release ID, graph ID and manifest hash while preserving literal expected values. The [implementation brief](../pipeline/package-implementation-brief.md) separates offline packaging from the future runtime adapter/domain/browser proof. The regional package remains source-node diagnostic evidence: coverage is not established, entrance verification and manual package GIS review are not run, and analytical promotion is blocked.

The browser runtime consumes the experimental v1 network package through `src/adapters/network-package.ts`, with schema-derived types, byte/hash/semantic checks and pure-domain conversion. Results bind to exact release/graph/manifest identities. The [local browser review](../pipeline/browser-network-review.md) records synthetic use and limitations; Gate 5A is accepted. Regional browser capacity remains unmeasured.

## Separate Census sample adapter

Task 5.5 implements a separate local Census ingestion path under `pipeline/src/flm_pipeline/`. It validates the accepted experiment/version and exact local source hashes, fetches only the configured 2024 ACS block-group fields through a key-safe HTTP/cache adapter, checks official variable metadata, reads the allowed 2020 block and 2024 block-group geometries, and requires a complete one-to-one ACS-to-2024-geography join. It writes separate ignored GeoPackages and compact JSONL evidence. It does not add Census fields to the closed network v1 manifest, join 2020 block counts to ACS, perform allocation, or create browser requests. Synthetic tests cover ingestion contracts and GIS round trips. The developer accepted the experiment and local files; both authenticated county queries and all 576 one-to-one block-group joins passed. All population pairs are valid; requested household/no-vehicle quartets are null throughout.


## Local allocation measurement boundary

The [allocation experiment contract](../contracts/allocation-experiment/v1/README.md)
is separate from network-package v1. Its JSON Schema validates source-release and
polygon identities, incomplete coverage, unique station IDs, string unit IDs,
full/intersection areas in square feet, representative-point membership and
nullable additive counts. The Python adapter validates geometry/CRS and retains
source quartet/land-water evidence; the Node adapter validates the same schema
before calling pure TypeScript weighting/aggregation. Missing fields, duplicate
units, zero-area source polygons and unsupported weights fail. Derived uncertainty
is not quantified. Unioned geometry must precede combined unique measurements.
No Census fields or polygon URLs are added to the current browser manifest.


## Local prototype readiness review (November 9, 2026)

The local experiment supports cached Census ingestion, experimental 25/50-foot
corridors and area/point allocation through pure TypeScript arithmetic. A separate
locked-environment reproduction matched all four GIS layers exactly in CRS,
geometry and attributes, and all allocation results. The earlier developer review
passed nine inspection items, including limited Cherry Creek/railroad observations.
The browser remains a synthetic source-node harness; it does not display Census
allocations or establish regional capacity. Frozen routing stages were reused;
a complete fresh source-to-release rebuild was not demonstrated in this pass.

The inventory lineage was checked: the inventory run report and downstream
extraction agree with the inventory file hash. A local handoff had mislabeled the
report hash as the inventory hash; the labels were corrected without changing
raw sources or generated artifacts. Gate 5B was accepted November 9, 2026 for the reproducible local experimental network and Census demonstration. Unknown
network candidates, unsupported restrictions, unresolved relation members,
unverified entrance, unestablished coverage, corridor spillover/gaps, missing
household quartets and unquantified allocated uncertainty remain limitations.
Task 5.7 recorded 473 Python, 16 TypeScript and eight Chromium tests passing,
alongside schema/lint/build and package validation. The readiness review independently
checked artifact hashes and exact GIS/allocation parity; it did not rerun all suites.
No authoritative scores, production readiness or distribution approval follows.

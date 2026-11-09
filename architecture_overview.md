# Architecture overview

Updated: November 9, 2026. Status: browser foundation plus offline source inspection, synthetic-verified extraction/GeoPackage export, supervised synthetic KMZ review packages, experimental pedestrian classification and graph assembly, browser package loading/reachability, and synthetic-verified Census ingestion wiring. Gate 2 is accepted for its documented prototype scope. Pedestrian policy 0.3 now incorporates the accepted kerb refinement for a general pedestrian walkshed; prior 0.2 evidence is historical. Task 5.1's package contract, fixture and provisional limits are accepted; Task 5.2 builds validated ignored local releases. Task 5.3 computes source-node reachability in a browser worker; Gate 5A is accepted for the synthetic local workflow. Task 5.5 completed authenticated local Census ingestion after method/source acceptance: 576 block groups joined with zero mismatches, and both vintage-specific GeoPackages reopened successfully. Population is available; all requested household/no-vehicle fields were null and remain unavailable. Regional analytical promotion remains pending.

## Implemented structure

This is one code repository containing a React + TypeScript + Vite web scaffold and an isolated Python package for offline data preparation. The app renders an experimental network-review harness. It fetches a user-selected package through a validated adapter and computes source-node reachability and partial source intervals in a dedicated worker. The local review server exposes only a small synthetic package. The browser does not compute polygons, population or scores. A separate local experimental GIS workflow now builds corridor comparisons and passes geometry measurements to pure TypeScript allocation functions. The Python package validates its environment/configuration, samples local OSM and Census files, inventories local sources, extracts an inventory-linked source subset, exports canonical records to an inspectable GeoPackage, produces supervised KML/KMZ review packages with companion source evidence, and classifies canonical ways and referenced nodes under the accepted experimental pedestrian policy. The evaluator is pure Python; its source adapter streams audit layers and reconciled summaries without using geometry. A separate graph adapter consumes the classification and canonical sources to build and verify directed arcs and GIS views. Task 5.5 adds a strict Census API/cache adapter, quartet normalization, county geometry validation, one-to-one ACS join checks and separate local Census outputs. Extraction, GeoPackage export, KMZ export, pedestrian classification, graph assembly and Census ingestion wiring have synthetic test coverage. The accepted local OSM hash is pinned in an ignored run configuration. A fresh regional inventory, extraction and GeoPackage export have completed; all 23 delivered regional cases passed by developer report; Gate 2 is accepted with documented limitations. Census/catalog hashes are authorized and pinned in an ignored local configuration.

```text
index.html -> src/main.tsx -> src/ui/App.tsx
                              + styles.css

src/domain/                  pure source-node shortest paths, source interval union, allocation totals and paired rates
src/adapters/                bounded package loading, shared schema validation, identity checks and worker coordination
pipeline/src/flm_pipeline/   source inspection, GIS smoke, source inventory, extraction/export, KMZ inspection, pedestrian classification/audit, and directed graph assembly
pipeline/tools/package_network.py   offline schema/content/GIS validation, synthetic package generation, and supervised local frozen-graph packaging
pipeline/tests/              Python config/runtime/GIS/inventory/extraction/export/supervisor/pedestrian-policy/graph tests
data/                        small-fixture/catalog policy documented; datasets pending
```

`AGENTS.md` is the shared agent policy. `CLAUDE.md` imports it. `DEVELOPER.md` is the human workflow guide; `docs/requirements.md` lists requirements by ID; `docs/validation.md` is the shared verification matrix. Detailed local planning reports are excluded from Git pending publication review.

Public change descriptions and comments use neutral technical language focused on outcomes, rationale, verification, and limitations. The shared policy and PR checklist define that writing standard.

## Toolchain and build

- Node and pnpm versions are pinned in `.node-version` and `package.json`; `pnpm-lock.yaml` records the dependency graph. [DEVELOPER.md](DEVELOPER.md) holds setup commands.
- React, TypeScript (native compiler), Vite, the official React plugin, and Biome (lint and format) form the initial toolchain; `package.json` is authoritative for exact versions.
- TypeScript is strict, with unchecked-index and exact-optional-property checks. It emits no sibling JavaScript files.
- TypeScript checks run under three configurations: browser app (`tsconfig.json`), build tooling (`tsconfig.node.json`), and domain modules without DOM or Node APIs (`tsconfig.domain.json`).
- `pnpm build` typechecks and generates static output in `dist/`. The build uses relative asset paths (`base: './'`), suitable for root or subdirectory hosting; `BASE_PATH` overrides it for a host requiring an absolute base. The relative base must be checked on the eventual host.
- The page footer shows the short commit identifier of the build.
- Local development and build previews bind to loopback on ports 5173 and 4173.
- GitHub CI installs from the frozen lockfile, lints, and runs the production build. Deployment to the Pages preview runs only after verification succeeds and publishes the verified build. Actions are pinned to verified commit revisions.
- Offline preparation uses a separate `pipeline/` Python package and a hash-locked Windows x86-64 / CPython 3.12.14 environment. Its `doctor`, bounded `smoke`, full `inventory`, pinned `extract`, `export`, `earth-export`, `classify`, and `graph` commands validate local setup, GIS round-trips, source hashes, archive integrity, Census identifiers, OSM counts, source-network references, inspection layers, and experimental pedestrian classifications. Earth export preserves IDs/tags/coordinates/references, applies explicit size limits, reopens and reconciles KML, and promotes only validated packages under process-tree timeout/RSS supervision. The graph command builds and validates an experimental directed multigraph. The Task 4.4 runner traverses accepted frozen graphs and writes diagnostic reachability evidence. Task 5.2's `pipeline/tools/package_network.py` validates the accepted raw OSM hash and frozen upstream reports, builds JSON/GIS/QA/attribution packages, applies the shared schemas plus cross-file checks, and atomically promotes new ignored release IDs. The package is a source-node diagnostic with coverage unestablished; no browser feature or complete-coverage guarantee is implied. Large raw and generated GIS files remain ignored.

## Boundaries for subsequent work

The [environment/source readiness review](pipeline/readiness-review.md) records Gate 1 acceptance for contract development with documented limitations. Discovery inventory is not accepted extraction input until source identities are reviewed and pinned. GitHub CI preserves frontend checks and now runs locked Python tests plus two synthetic package build/validation runs; it does not download regional data. Frontend Vitest/Playwright policy remains separate.

The offline [source-network contract](pipeline/source-network-contract.md) defines canonical raw JSONL records, complete-way selection, relation limitations, and derived GeoPackage inspection layers. The [extractor brief](pipeline/extractor-implementation-brief.md) and `extract` command implement the source subset with inventory linkage, SQLite-backed indexes, reopened-output validation, and atomic promotion. The `export` command checks extraction provenance and hashes, writes the five contract layers, verifies reopened geometries/fields/counts, and records duplicate, repeated-reference, and zero-length diagnostics inside a supervised worker. Its parent promotes a validated directory atomically and writes the completion report last. Worker preflight, construction and verification use configured timeout and sampled process-tree RSS limits; parent promotion/report I/O is outside that measurement. Synthetic fixtures cover the extraction-to-GeoPackage workflow. The accepted local OSM input has completed these prerequisites under the recorded frozen code identity. This inspection product is separate from a future browser routing format.

The [GIS review procedure](pipeline/gis-review.md) defines source-object inspection and finding dispositions. A synthetic regression verifies source-shared junctions and disconnected geometric crossings/coincident IDs through export. Task 2.4r removes attached-way location caching, streams canonical reopen validation through a disk-backed ID index, enforces canonical string ID types, and supervises GeoPackage construction/verification in a worker. The [readiness review](pipeline/readiness-review.md) records checks and remaining resource limitations. One regional run now has measured resource evidence in the readiness review; the 23 delivered regional cases passed by developer report and Gate 2 is accepted with documented limitations.

The [Google Earth inspection specification](pipeline/google-earth-inspection-spec.md) defines a derived local KML/KMZ view, topology/diagnostic synthetic package profiles, companion source evidence, and a synthetic-first manual trial. The [user guide](pipeline/google-earth-user-guide.md) assigns human setup/review steps. The exporter and synthetic package generation are implemented; the user has reported passing topology selection, coincident-node, junction, bridge/tunnel, and boundary checks; diagnostic checks also pass by user report; descriptions now place review fields before technical details; the developer approved the revised display. Canonical JSONL and GeoPackage retain their existing roles, and the browser application is unchanged. The core exporter rejects packages exceeding its trial caps. A separate versioned [case-only delivery adapter](pipeline/regional-case-delivery-spec.md) now creates explicitly partial regional views with whole-way preservation, file membership, omission evidence and independently reopened output checks. Complete canonical and GeoPackage products remain separate. It adds no runtime dependency.

Authoritative walking costs, aggregation, normalization, and scoring belong in pure domain modules independent of React and GIS service payloads. Adapters validate external values and translate them into explicit typed inputs. UI code collects settings and renders outcomes.

Add an application coordination layer and worker directory when the first analysis job requires them. Jobs will need identifiable inputs/versions, progress, cancellation, stale/failed states, and protection from an older result overwriting a newer request. This behavior is not implemented in the foundation.

Data preparation should remain an offline workflow. The current pipeline inspects sources and extracts a regional source subset; routing connectivity, display tiles, and analytical indicator data remain separate products connected through a future versioned manifest. Large inputs/archives belong in approved external storage; only small cleared fixtures and metadata belong in normal Git.

## Runtime analysis options

| Option | Description |
|---|---|
| A | Routing, aggregation, and scoring in the browser. This is the first candidate. |
| B | Browser application plus an existing approved routing or analysis service. |
| C | Browser application plus a custom backend. |

Move from A to B or C only through a decision record backed by measured evidence that A cannot meet agreed correctness or performance thresholds. Try partitioning, indexing, workers, and caching first.

## Where user data travels

Local file parsing stays in the browser. Geocoding and geometry-based service queries send locations to the external service. Do not describe the workflow as local-only when network calls carry analytical inputs.

## Provisional direction and open decisions

| Topic | Current position |
|---|---|
| Repository topology | One repository initially; preparation can split later through a stable contract |
| Runtime analysis | Browser processing is the first feasibility candidate; no engine is selected |
| Map | MapLibre is a prototype candidate; no map dependency is installed yet |
| PMTiles | Planned display/preparation deliverable; routing representation remains unproven |
| Indicator access | Static indexed packages and approved feature services remain options |
| Session storage | Versioned local exchange/autosave design remains open |
| Methodology | No reference model exists; the method is specified in `docs/methodology.md` and approved by humans before it is authoritative |
| Hosting | A GitHub Pages workflow is configured for a public scaffold preview; CDOT-managed production hosting and staging remain pending |
| Accessibility/reporting | Acceptance criteria and a validated PDF path remain pending |
| Licensing/branding | Client/code/data/third-party distribution decisions remain pending |

The next useful technical slice is one station and a small approved geographic sample, with independently reviewed reachability/aggregation evidence. Do not label scaffold checks as analytical validation.

Update this file when implemented boundaries, toolchain, data flow, or deployment change. Use short [decision records](docs/decisions/README.md) for material accepted choices and keep task status in the issue/PR workflow.

## Current prototype status

The offline network and Census demonstration was accepted for experimental development on November 9, 2026. Locked-environment repetition reused frozen routing stages, repeated cached Census ingestion and spatial allocation, and matched GIS geometry, attributes and allocation results. Regional network coverage remains unestablished because unknown candidates, unsupported restrictions and unresolved relation members remain. Household/no-vehicle fields are unavailable; allocation uncertainty is not quantified. No authoritative FLM score is implemented.

The browser loads a versioned synthetic package through validated adapters and computes source-node reachability in a cancellable worker. Regional browser capacity, coordinate-origin interaction, sessions, map display products and production deployment remain open. The local GIS experiment produces corridor polygons and Census comparisons separately from the browser package.

[Decision 0011](docs/decisions/0011-user-defined-origins-and-snapping.md) specifies future user-defined origins: the closest walkable segment position or node within 500 feet, no connector-time deduction, northernmost snap point for exact distance ties, and flagged rejection when no candidate is within range. Successful snaps need no flag. This behavior is specified but not implemented in the browser harness. Historical 100-foot charged-access reference cases retain their accepted expectations.

Use the [prototype overview](docs/prototype-overview.md), [independent review guide](docs/independent-review.md), [pipeline commands](pipeline/README.md), [network contract](contracts/network-package/v1/README.md) and [allocation contract](contracts/allocation-experiment/v1/README.md) as current entry points. Local review packets and regional artifacts are excluded from Git; a public clone supports synthetic reproduction and needs separately supplied approved inputs for regional processing.


## CI runtime availability

The Windows CI job pins CPython 3.12.10 because actions/setup-python cannot
provide the local 3.12.14 build on the hosted Windows runner. Runtime validation
accepts exactly Windows x86-64 CPython 3.12.10 or 3.12.14. Existing CPython 3.12
wheel versions and SHA-256 locks remain unchanged; CI verifies their installation
and synthetic behavior on 3.12.10. Historical local results retain their recorded
3.12.14 environment identity. Other patch versions remain unsupported by doctor.

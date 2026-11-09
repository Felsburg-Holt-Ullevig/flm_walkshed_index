# Offline data preparation

The [readiness review](readiness-review.md) records task 1.4 findings and the limitations accepted for Gate 1 and Gate 2. The developer accepted Gate 2 for the inspected regional source package on November 3, 2026. Task 2.2 implements regional extraction; the accepted local OSM source has a fresh inventory, extraction and GeoPackage export. Its hash is held in ignored run configuration; the shared discovery example remains unpinned.

Offline preparation runs as a Python package under `pipeline/src/flm_pipeline/`. It provides strict TOML configuration checks, an environment doctor, a bounded source/GeoPackage smoke run, a full local source inventory, inventory-linked regional extraction, a GeoPackage exporter for GIS inspection, an experimental pedestrian policy classifier with audit outputs, a directed graph builder, and a bounded experimental regional traversal runner. The traversal results remain incomplete diagnostics; they are not approved complete walksheds.

The locked environment targets Windows x86-64 and CPython 3.12.14. Use [`bootstrap.ps1`](bootstrap.ps1) with an explicit base Python executable. [`environment-win-py312.md`](environment-win-py312.md) records the observed versions, lock procedure, licenses, and commands. The lock is separate from the browser's pnpm lockfile.

The [local preparation design](prototype-design.md) records the experiment settings and later task contracts. The example config uses the accepted local sample bounds, with source hashes left unpinned for discovery. It creates ignored reports in `data/generated/prototype/` and temporary files in `data/staging/prototype/`.

Preserve provenance, CRS/units, source vintages, processing versions, coverage, output hashes, and rejected/skipped-record reasons. Validate a candidate package before promoting its published manifest. Keep large raw/staging/generated files in approved external storage or the ignored local data paths. See [data contract](../docs/data-contract.md) and [validation](../docs/validation.md).

From the repository root, the local commands are:

```powershell
& .\.venv\Scripts\python.exe -m flm_pipeline doctor --config pipeline/config/denver-source.example.toml
& .\.venv\Scripts\python.exe -m flm_pipeline smoke --config pipeline/config/denver-source.example.toml
& .\.venv\Scripts\python.exe -m flm_pipeline inventory --config pipeline/config/denver-source.example.toml
& .\.venv\Scripts\python.exe -m flm_pipeline extract --config pipeline/config/denver-source.example.toml --source-inventory data/generated/prototype/RUN_ID/source-inventory.json --inventory-report data/generated/prototype/RUN_ID/run-report.json
& .\.venv\Scripts\python.exe -m flm_pipeline export --config pipeline/config/denver-source.example.toml --extraction data/generated/prototype/EXTRACTION_RUN_ID
& .\.venv\Scripts\python.exe -m flm_pipeline earth-export --config pipeline/config/denver-source.example.toml --extraction data/generated/prototype/EXTRACTION_RUN_ID --gpkg-export data/generated/prototype/EXPORT_RUN_ID --dataset-kind synthetic --review-profile topology
& .\.venv\Scripts\python.exe -m flm_pipeline classify --extraction data/generated/prototype/EXTRACTION_RUN_ID --policy-config pipeline/config/pedestrian-policy.example.toml
& .\.venv\Scripts\python.exe -m pytest pipeline/tests
```

For the second synthetic review packet, run the same `earth-export` command with `--review-profile diagnostic`. Use the GeoPackage **export directory** containing `source-network.gpkg` and its `run-report.json` as `--gpkg-export`; do not pass the report file itself. The command prints the inspection folder, KMZ, manifest and report paths. Keep the folder unchanged for review.

The Task 2.4b integration tests create and retain their two small synthetic PBF/config/inventory inputs under `data/staging/prototype/earth-trials/topology/` and `data/staging/prototype/earth-trials/diagnostic/`. These inventory files are assembled synthetic-fixture evidence, not real statewide inventories. Running the test suite regenerates extraction, GeoPackage, and inspection-package outputs under the ignored `data/generated/prototype/` directory. To replay an individual stage, use the config and inventory/report in the matching fixture directory, then pass the generated extraction/export IDs returned by each command. Do not use these fixture inputs for a regional run.

The smoke command samples the PBF's node, way, and relation streams and a few features from each Census archive. It writes and reopens a temporary GeoPackage. This verifies local reader and GIS I/O wiring; it does not validate routing coverage.

The inventory command streams SHA-256 hashes, checks every ZIP member CRC, verifies required shapefile sidecars, iterates Census features in bounded chunks while reading identifier and count fields, and scans all OSM entities under the configured time and sampled-RSS limits. It writes `source-inventory.json` and `run-report.json` under an ignored `data/generated/prototype/<run-id>/` directory. Discovery hashes are reported but never copied into the TOML configuration. Review source identity and provenance before manually pinning them. The variables catalog report describes metadata fields only; it does not claim ACS observations were retrieved or the dataset vintage was verified.

The extract command requires a configured OSM SHA-256, a complete inventory and its run report, matching hashes and counts, and the same current pipeline code identity. It scans the source with PyOsmium, uses a disk-backed SQLite index, writes `nodes.jsonl`, `ways.jsonl`, `relations.jsonl`, and `extraction.json`, reopens and validates canonical outputs, then promotes the unique candidate directory atomically. Pass the exact inventory and report paths returned by a fresh `inventory` command. Any code, config, inventory, or OSM source change invalidates that evidence. Preflight rejections create no run; worker or promotion failures remain in ignored `data/staging/prototype/` with a failed report. A complete selection with no highway ways reports `empty`; it does not represent a routing network.

The `export` command requires the matching configuration and a successful extraction whose OSM SHA-256 is pinned and current. It streams canonical records through a disk-backed node index and writes `source_nodes`, `source_ways`, `source_segments`, nonspatial `source_relations`, and `coverage` to `source-network.gpkg`. Spatial layers use EPSG:4326; each segment follows a consecutive ordered way-reference pair and carries WGS84 ellipsoidal and EPSG:26913 diagnostic lengths. Duplicate coordinate sequences, repeated node references, zero-length segments, and degenerate geometries are retained and reported. Missing references, invalid IDs/coordinates, nonfinite lengths, count mismatches, or failed round-trip checks prevent promotion. The final `run-report.json` is the completion record; a GeoPackage without a matching passing or explicit `empty` report is incomplete.

The shared discovery example has no pinned hashes; the accepted regional hash remains in ignored local run configuration. Do not copy it into shared configuration without separate source and publication review. Census and catalog inputs do not select network records. Extraction output is an offline source subset; export creates GIS inspection layers only and does not interpret pedestrian access or build a graph.

## Experimental regional routing diagnostic

Task 4.4 adds the local `pipeline/tools/run_regional_routing.py` command. Its ignored handoff and closeout are under `docs/planning/2026-11-02/`; the output contains a GeoPackage, a JSON run report, and common-core difference tables. To prepare an expanded extract and graph, then compare it with the accepted original graph, use the two commands below with the run IDs recorded in the active handoff:

```powershell
& .\.venv\Scripts\python.exe pipeline\tools\run_regional_routing.py --handoff docs\planning\2026-11-02\active-regional-run.json --prepare-expanded
& .\.venv\Scripts\python.exe pipeline\tools\run_regional_routing.py --handoff docs\planning\2026-11-02\active-regional-run.json --expanded-graph data\generated\prototype\expanded-routing\routing-graph\GRAPH_RUN_ID
```

The runner verifies accepted hashes, supervises work with a timeout and sampled 4 GiB process-tree RSS limit, and reopens its GIS layers for reconciliation. It reports 1/10/50 source-node performance cases. Only the first source node is the accepted diagnostic origin; additional nodes are not station locations. Common-core agreement is supporting evidence, not proof of complete data coverage. Unknown policy candidates, unsupported restrictions, unresolved relation members, and unestablished coverage keep all regional results incomplete. See [experimental routing](experimental-routing.md) for the run contract and limitations; see the ignored Task 4.4 closeout for the executed run and human GIS inspection instructions.

## Regional network contract

Task 2.1 defines [source-network-1](source-network-contract.md), the [extractor implementation brief](extractor-implementation-brief.md), and [synthetic fixture expectations](fixtures/source-network-cases.md). Task 2.2 implements extraction and failure coverage on synthetic PBF input. Task 2.3 implements the synthetic-verified GeoPackage export. A regional run still requires the brief's source-pinning and fresh-inventory prerequisites.

The [GIS review procedure](gis-review.md) specifies ArcGIS Pro layer setup, source-ID checks, count reconciliation, inspection records, and finding dispositions. The [Google Earth inspection specification](google-earth-inspection-spec.md) and [user guide](google-earth-user-guide.md) define a local KML/KMZ path. Task 2.4b implements a supervised `earth-export` command, topology and diagnostic synthetic profiles, companion evidence/review files, hashes, limits and independent KML reopening. It adds no runtime dependency. The automated suite verifies source IDs, tags, ordered refs, coordinates, lengths, ZIP resources, deterministic semantic output, stale-input rejection, limits, timeout behavior and failed promotion. The developer accepted the Task 2.4c synthetic Google Earth browser trial and revised description usability. Task 2.4r resolves the source-reader cache, canonical validation storage/ID types and GeoPackage supervision findings. The bounded regional package was reviewed by the developer and Gate 2 is accepted with documented limitations. The [readiness review](readiness-review.md) records measured evidence and remaining limits.

## Resource-control repair

PBF extraction callbacks run without attached way-node location caching; required node coordinates are resolved explicitly in the existing SQLite passes. Canonical reopening uses a temporary disk-backed ID index with a 16 MiB SQLite page-cache target and one decoded record at a time. A canonical JSONL line over 16 MiB fails explicitly before JSON decoding. These limits do not establish whole-extraction memory capacity: selection sets and individual records remain subject to configured worker RSS limits.

GeoPackage `export` now supervises worker startup, source/input preflight, construction and reopened verification under configured elapsed-time and sampled process-tree RSS limits. A nonzero exit, timeout, RSS failure, incomplete child cleanup or invalid result prevents promotion. The parent atomically renames the candidate directory and writes its completion report last; that short promotion/report I/O is outside worker resource measurement. Success reports include sampling interval, sampled peak, duration and configured limits. Staging retains worker diagnostics. The command syntax is unchanged. Source hashes in the regional example remain unpinned.


## Case-only regional review delivery

The accepted local OSM snapshot has completed a fresh inventory, regional extraction and GeoPackage export. The shared example remains unpinned; use the accepted local configuration for reproducing that run. A separate [case-only delivery adapter](regional-case-delivery-spec.md) supports bounded, explicitly partial KMZ views without changing complete canonical or GeoPackage products. The readiness review records measured counts/resources and remaining gaps. All 23 delivered regional cases passed by developer report; Gate 2 is accepted with documented limitations.

## Accepted experimental pedestrian policy and audit

[Policy 0.2](pedestrian-policy.md) specifies experimental access, direction, barriers, sidewalk evidence and base travel costs. The `classify` command consumes the [accepted example configuration](config/pedestrian-policy.example.toml), verifies the completed canonical extraction hashes, and writes way, referenced-node, source-segment-candidate, and conditional-tag JSONL layers. It also writes reconciled JSON and CSV counts by highway, reason, and sidewalk evidence. Outputs go to a unique directory under `data/generated/prototype/pedestrian-classification/`; temporary processing uses `data/staging/prototype/`. Unknown candidates block analytical promotion. Geometry checks, graph assembly, and relation interpretation remain for later tasks.

Example:

```powershell
& .\.venv\Scripts\python.exe -m flm_pipeline classify --extraction data/generated/prototype/EXTRACTION_RUN_ID --policy-config pipeline/config/pedestrian-policy.example.toml
```

The classification layers have no geometry. They retain source IDs and ordered references; unchanged raw tags remain in the input JSONL files identified by the report hashes. Join the classification tables to matching source-network GeoPackage layers by OSM ID. The report records that geometry validation and graph construction are `not_run`; these outputs are policy audit evidence, not a routing graph or walkshed.


## Experimental directed graph

The [internal graph contract](routing-graph-contract.md) defines Task 3.3 outputs and failure behavior. The `graph` command verifies a current classification, replays policy decisions from canonical source tags, computes geodesic feet/base seconds, builds parallel directed arcs using source node IDs, writes all candidate dispositions, checks relation restrictions, and independently reopens the graph and routing GeoPackage. It adds no dependencies. Classification directory means the folder containing `run-report.json`, not the report itself.

1. Run `classify` on the accepted extraction after any pipeline code/test/graph-contract change. Keep its returned classification directory.
2. Build the graph with that directory:

```powershell
& .\.venv\Scripts\python.exe -m flm_pipeline graph --extraction data/generated/prototype/EXTRACTION_RUN_ID --classification data/generated/prototype/pedestrian-classification/CLASSIFICATION_RUN_ID --policy-config pipeline/config/pedestrian-policy.example.toml
```

3. Open the returned `run_report` path. Check its status, counts, hashes and `analytical_promotion`. `incomplete_unknown_policy` is a completed diagnostic graph with unresolved walking policy; it cannot support a complete walkshed. `empty` is also explicit. Gate 3 and coverage validation remain required even when structural checks pass.
4. Inspect `routing.gpkg`: `routing_nodes` contains source IDs; `routing_arcs` contains travel direction, feet and base seconds; `candidate_audit` contains included, excluded and unknown source segments. Full raw tags remain in the hash-identified canonical extraction. Read `relations-audit.jsonl` for restriction evidence. Google Earth cannot directly open this GeoPackage; creating a graph KMZ is outside Task 3.3.
5. Retain each generated directory unchanged. A directory without `run-report.json` is incomplete. Failures remain under `data/staging/prototype/routing-graph-RUN_ID/` with a worker log and failure report. Do not reuse a failed candidate or edit generated files to clear a failure; rerun into a new directory after resolving its cause.

The worker is supervised at 1,200 seconds and 4 GiB sampled process-tree RSS. JSONL validation and batched GIS writing/reopening occur inside the worker; final parent promotion/report I/O is outside measurement. Tests use synthetic sources and cover topology, costs, directions, barriers, unknowns, zero lengths, large string IDs, input/output corruption, deterministic JSONL and failed-worker promotion. The existing Windows sharing-lock retry also applies to classification directory promotion. Task 3.4 reviews scenarios, source differences and component structure; station traversal remains Phase 4.


## Graph scenario review

The [graph policy review procedure](graph-policy-review.md) documents the independent `pipeline/tools/review_graph.py` adapter and its test command. It compares a frozen accepted graph with the pinned reference classification using the same source IDs and feet-based geodesic lengths, reports weak/strong components and named source cases, and screens disconnected endpoints without creating links. The adapter records its own code/test hashes and preserves the upstream graph identity. Its reference node/arc outputs are comparison evidence only. The local Gate 3 packet records regional findings and the developer's acceptance with documented diagnostic limitations; complete regional analytical promotion remains blocked.


## Current policy revision: general pedestrian kerb handling

The current evaluator and strict configuration use `pedestrian-policy-0.3` / `public-walk-experiment-0.3`. Exact `barrier=kerb` no longer makes a node unknown by itself. Other access, locked-node, conditional, structure and relation rules remain. Wheelchair-specific routing/documentation is outside the primary analytical scope; available raw attributes are retained without new acquisition or dedicated calculations. The [scope decision](../docs/decisions/0010-general-pedestrian-walkshed-and-kerb-policy.md) and current [policy](pedestrian-policy.md) define this revision. Byte-preserved 0.2 policy/configuration snapshots and earlier outputs remain historical evidence; the current loader rejects the old configuration version. Reclassify and rebuild before reviewing under the new implementation identity. Gate 3 and complete regional analytical promotion remain separate decisions.


## Routing reference specification

Gate 3 is accepted for policy 0.3 with diagnostic limitations. The developer accepted the [routing references](routing-reference-spec.md), [literal metric fixture data](fixtures/routing-references-v1.json), and [benchmark settings](config/routing-benchmarks.v1.toml) for experimental testing. The [acceptance manifest](fixtures/routing-reference-acceptance-v1.json) pins their reviewed bytes and rejects changed or draft inputs in tests. [Source fixtures](fixtures/routing-source-cases-v1.json) now pass through the actual PBF reader, extractor, classifier, graph builder, and structural/GeoPackage validators. This adds no routing traversal or snapping command. Complete regional analysis remains blocked by policy and coverage limitations.


## Experimental reference routing

The [routing implementation contract](experimental-routing.md) documents the pure traversal API, included-only snapping, geodesic interpolation, frozen-graph validation, incomplete statuses and common-core comparison interface. Task 4.4's supervised regional runner has completed source-node diagnostic traversal, common-core comparison and GIS export; its acceptance limits and review status are in the ignored Task 4.4 closeout. Routing remains an offline experiment; the browser adapter and loading/computation proof are Task 5.3.

## Experimental package preparation (Task 5.2)

The accepted Task 5.1 contract is now implemented for offline packaging. Use a hash-locked Windows Python environment from the repository root. The additional `requirements-package-win-py312.lock.txt` installs the production Draft 2020-12 JSON Schema validator; [`environment-win-py312.md`](environment-win-py312.md) and [`licenses-win-py312.md`](licenses-win-py312.md) record exact versions, hashes and licenses.

Build and check the real synthetic F01 package first. Use a new release ID each time because completed IDs are immutable:

```powershell
& .\.venv\Scripts\python.exe pipeline/tools/package_network.py build-synthetic --release-id synthetic-f01-review-01
& .\.venv\Scripts\python.exe pipeline/tools/package_network.py validate-package --manifest data/generated/prototype/network-packages/synthetic-f01-review-01/manifest.json
```

The build also writes `_expected-results/synthetic-f01-review-01.json` beside the package directories. It copies the literal fixture expectation without changing its numbers, then binds it to the generated release ID, graph ID and exact manifest SHA-256. It is an expected-result sidecar, not a computed route or a file in the package manifest.

Then prepare the accepted local regional package with another new ID:

```powershell
& .\.venv\Scripts\python.exe pipeline/tools/package_network.py prepare-release --release-id denver-policy03-20261104-review-01
& .\.venv\Scripts\python.exe pipeline/tools/package_network.py validate-package --manifest data/generated/prototype/network-packages/denver-policy03-20261104-review-01/manifest.json
```

The regional command uses the accepted local handoff by default. It rehashes the pinned raw OSM PBF, checks the inventory and frozen graph/classification/policy/routing-reference/regional-report identities and output hashes, creates graph JSON and QA/GIS/notices, validates schemas, cross-file geometry and direction, costs, semantic identity, file hashes and GIS layers, then atomically promotes the new release under `data/generated/prototype/network-packages/<release-id>/`. The raw PBF and upstream artifacts are read-only and are not copied into the package. The successful promotion creates a completion record in its ignored supervision directory. Existing release IDs are rejected; do not edit a completed directory.

CI runs the Python suites and builds two synthetic packages from fixture records under the locked environment. CI does not access the local OSM/Census files or download regional data. To check the full local Python suites, run `& .\.venv\Scripts\python.exe -m pytest pipeline/tests pipeline/tools/tests -q`.

If a run fails, inspect `failure.json` and `worker.log` under `data/staging/prototype/network-package-supervision/<run-id>/`. Candidate/intermediate files remain under ignored `data/staging/prototype/network-package-candidates/` and `data/staging/prototype/network-packages/`; there is no resume-in-place operation. Confirm the failure cause, then rerun with a new release ID. Keep raw inputs and successful release folders untouched. For storage cleanup, remove only a specific failed run directory after its diagnostics have been recorded; resolve and check that directory is inside the exact package staging root before using recursive deletion. Do not use wildcards or delete under `data/raw/`, `data/generated/prototype/`, or an accepted upstream run.

This package is a local experimental diagnostic, not an approved data publication. Its coverage readiness is `not_established`; unknown candidates, unsupported restrictions and unresolved relation members remain; station entrance verification and package-specific manual GIS review are `not_run`; analytical promotion is blocked. The output records the OSM attribution/license reference and the developer-supplied Geofabrik download page/date. The source header timestamp is recorded as data vintage, not download time. Public redistribution/client delivery is not cleared. Synthetic browser loading and traversal are implemented; regional browser capacity remains unmeasured.

## Local browser review

Task 5.3 adds the validated package loader, pure TypeScript source-node traversal, worker, and browser harness. Follow [browser review instructions](browser-network-review.md) to build, serve, and inspect the literal 150-foot case. No regional data are exposed by the review server. Gate 5A was accepted for the synthetic workflow; the Census experiment was subsequently implemented.

## Census/spatial design boundary

Gate 5A is accepted for the synthetic local browser workflow. Task 5.4 supplies the proposed [variable specification](census-variable-spec.md), [ingestion brief](census-ingestion-brief.md) and [spatial experiments](spatial-allocation-spec.md). Task 5.5 adds the `census-sample` command, strict key-free cache, full county geometry reader, join validator and separate local outputs. The safe [example config](config/census-sample.example.toml) is intentionally non-runnable. A real run requires explicit experiment acceptance, authorization of the three exact local Census/catalog hashes, and a locally configured `CENSUS_API_KEY`; none is inferred from Gate 5A. No observation request or promoted sample was made during the implementation step. See the ingestion brief for the setup procedure and closeout status.


## Local polygon and allocation experiment

Follow the [execution and review guide](spatial-experiment-guide.md) for the
accepted 25/50-foot corridor, area/representative-point and overlap comparisons.
Run `python pipeline/tools/run_spatial_experiment.py --handoff <local-handoff>`
from the repository root with the locked Python and Node environments installed.
No Census API key or live request is needed. The command consumes exact frozen
routing/Census identities, validates/reopens GIS outputs, executes pure TypeScript
arithmetic and promotes a new ignored local run. It exports a GeoPackage, CSV,
measurement JSON and calculation/report JSON. Invalid inputs fail without repair
or a completion manifest. These are experimental outputs, not browser package
extensions or scores. Household/no-vehicle data remain missing in the accepted
sample. Lincoln examples are synthetic areas with no route claim.


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

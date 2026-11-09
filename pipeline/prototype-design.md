# Local preparation environment and extraction experiment

Date: November 2, 2026. Status: the project lead accepted the discovery-only task 1.2 environment and smoke check; task 1.3 now inventories configured local sources. Pedestrian policy 0.2 is accepted for experimental evaluation and implemented in Task 3.2; no authoritative analytical method is approved.

## Environment specification

Target Windows x86-64 with CPython 3.12.14. Task 1.2 created the ignored repository-root `.venv/` from an explicitly configured Python executable; the bundled runtime was not modified. Keep raw inputs read-only. If synchronization locks prevent environment creation, stop and report the path/error; relocation requires a separate checkout decision.

Use Python's venv and pip for offline preparation dependencies; use pnpm exclusively for JavaScript dependencies. Task 1.2 created `pipeline/requirements.in`, a Windows/Python-specific `pipeline/requirements-win-py312.lock.txt`, a separate pip bootstrap lock, and a wheel-lock/license inventory utility. The 22-package dependency lock and pip 26.2.2 bootstrap both install with `--require-hashes --only-binary=:all:`; a second temporary environment was recreated from the verified wheels. See `pipeline/environment-win-py312.md` for observed versions, native components, and commands. A lock for another platform requires separate verification. Do not silently compile native packages or relax pins.

Required packages: `osmium` (PyOsmium, PBF identities and tags), `geopandas` (GIS tables), `shapely` (geometry), `pyproj` (CRS and geodesic lengths), `pyogrio` (GeoPackage I/O), `pytest` (Python tests), and `psutil` (sampled process memory). NetworkX is deferred until graph work. Pyrosm, Fiona, Conda, Docker, WSL, and Osmium CLI are not initial requirements. Report licenses for selected versions and transitive native components. These are offline dependencies and add no browser bundle bytes.

Primary reader experiment: use PyOsmium to retain original ordered way-node references, tags, and nodes. Only evaluate Pyrosm in a separate optional environment if the primary reader fails a documented requirement or a measured convenience-extraction comparison is requested. A prefiltered walking-network API is not the source of pedestrian policy. Osmium CLI remains an optional alternative after an explicit tool decision.

## Proposed experimental settings

These settings were accepted for task 1.2 source inspection only. They establish no walking speed, access policy, score, or population allocation.

| Setting | Proposed value |
|---|---|
| Region ID | denver-union-source-v1 |
| Study core bbox | [-105.04, 39.72, -104.97, 39.79], longitude/latitude order |
| Initial extraction bbox | [-105.08, 39.68, -104.93, 39.83] |
| Later expanded comparison bbox | [-105.12, 39.64, -104.89, 39.87] |
| Candidate station | [-105.0006, 39.7530], illustrative Union Station vicinity; access point must be verified before routing |
| Storage CRS | EPSG:4326, x=longitude and y=latitude |
| Inspection/area CRS | EPSG:26913; verify source transformations and area suitability before allocation |
| Length definition | WGS84 ellipsoidal geodesic meters along each consecutive coordinate pair, using PyProj Geod; projected lengths are diagnostic only |
| Resource limits | 20 minutes per initial scan stage; 4 GiB sampled process RSS; developer may revise after measurement |

Sample RSS every second and report the maximum as sampled peak, not exact peak. A supervisor must terminate a stage exceeding its deadline or memory budget, preserve logs, and mark the run failed. A timeout means the experiment needs review; it does not justify silently reducing source coverage. Disk-backed node lookup should be considered before a statewide in-memory node dictionary. Standard-library SQLite is available without another package.

## Source and extraction semantics

Task 1.2 reads the PBF header and a bounded sample of each available entity type; it does not perform the full regional extraction. Record scanned counts and early termination explicitly. Task 1.3 inventories the full source and geographies. Task 2.1 finalizes extraction contracts before implementation.

Proposed regional selection: identify nodes within the extraction bbox, select ways referencing those nodes, then retain every referenced node for each selected way. Report ways that geometrically cross the bbox without a node inside as a limitation of this selection; do not advertise intersection-complete coverage. Preserve all highway values and raw tags on selected highway ways; preserve relevant tagged nodes and ordered node references. Keep source node IDs as strings. Coordinate coincidence never merges distinct source nodes.

Preserve relation IDs, tags, and members for relations touching selected objects, reporting unresolved member references. Do not claim relation completeness, evaluate turn restrictions, or infer access from incomplete relations. Barrier/access and pedestrian-direction semantics remain for Phase 3. Missing/invalid locations or unresolved required way-node references fail the stage and produce a diagnostic record; do not substitute coordinates or zero lengths.

The extraction margin is experimental. Neither a complete-way subset nor this margin proves route completeness. Later traversal must check frontier/coverage and compare expanded extracts.

## Candidate configuration and output contracts

Task 1.2 implements strict runtime validation with unknown fields rejected. Configuration paths resolve relative to repository root; output destinations within raw input storage and source/output path collisions are rejected. Machine-specific paths and API keys belong in ignored local configuration/environment.

Configuration version `prototype-config-1` contains: `config_version`, `region_id`, `sources` (source ID, path, expected SHA-256 or null during initial inventory), `core_bbox`, `extract_bbox`, `expanded_bbox`, `station_lonlat`, `storage_crs`, `inspection_crs`, `length_method`, `limits` (seconds, RSS bytes), and `output_root`. Bboxes require finite values, valid coordinate ranges, proper ordering and nesting. Null hashes permit discovery inventory only; preparation requires a pinned inventory. No example hash may be treated as a real source hash.

Inventory version `source-inventory-1` contains source ID, relative path, bytes, SHA-256, expected/observed hash match, source URL with evidence, claimed vintage, observed header vintage, download time when known, retrieval/provenance status, license reference, CRS, fields, actual/header feature counts, identifier checks, archive integrity, warnings, and validation status. Use null for unknown provenance. Separate observations from claims. Do not infer download time from local modification time or PBF vintage from the filename alone.

Run report version `prototype-run-1` contains run ID, UTC timestamps, code revision and dirty state, configuration hash, source inventory hash, Python/platform/package versions, stage commands, status, exit codes, durations, sampled peak RSS, input/output counts, output hashes, rejected/unresolved IDs and reasons, check outcomes, limitations, and temporary/final destinations. Secrets must never appear in reports. Large diagnostics may be separate files referenced by hash.

Task 1.2 provides a safe TOML example under `pipeline/config/` using these values and relative source paths. An empty `expected_sha256` string represents an unpinned hash because TOML has no null value. The implementation uses standard-library tomllib and json for TOML input and JSON reports. Reports go under ignored `data/generated/prototype/<run-id>/`; temporary data goes under `data/staging/prototype/<run-id>/`. It refuses to reuse an existing run directory and does not write to raw files.

## Task 1.2 delivered implementation

Implement `pipeline/src/flm_pipeline/` as an installable package with `python -m flm_pipeline` entry point; keep GIS I/O modules separate from configuration/report validation. Use `pipeline/pyproject.toml` for package metadata and pytest configuration. No authoritative browser calculations are introduced.

From the repository root, use `.venv/Scripts/python.exe` in PowerShell:

```text
& .\.venv\Scripts\python.exe -m flm_pipeline doctor --config pipeline/config/denver-source.example.toml
& .\.venv\Scripts\python.exe -m flm_pipeline smoke --config pipeline/config/denver-source.example.toml
& .\.venv\Scripts\python.exe -m pytest pipeline/tests
```

`doctor` validates environment/platform, configuration, source paths and output separation; it returns nonzero for invalid/missing inputs. `smoke` reads the real PBF header and bounded node/way/relation samples; reads five features from each Census archive; writes/reopens GeoPackage node/line/polygon layers; verifies string IDs, CRS, counts and geometry; checks sampled way tags and ordered node references; and emits a run report. The node and line GeoPackage layers are interoperability fixtures; the polygon comes from a sampled Census feature. A successful import alone does not pass smoke acceptance.

The PowerShell bootstrap accepts an explicit base Python path. Wheel-resolution/install commands, hashes, package licenses, and observed versions are recorded in the environment documentation and lock files. The second temporary environment passed doctor, smoke, and pytest using the same verified wheel set. Ten synthetic tests cover strict/invalid configuration, missing files, unsupported Python, lock pins, and GIS round-trip behavior. Task 1.3 adds synthetic inventory tests for duplicate and malformed IDs, missing shapefile members, ZIP CRC corruption, hash mismatch reporting, and catalog structure. Preserve existing Vitest/Playwright policy for browser code; pytest is for Python preparation only.

Stop on unavailable compatible wheels, source parsing failures, unsupported header details, failed round trips, or resource limits. Return evidence for review rather than changing libraries or environment versions. No full extraction, Census API requests, graph rules, or routing in this task.

## Task 1.3 implementation brief

Add target interface `python -m flm_pipeline inventory --config <path>`. Stream SHA-256 in bounded chunks. Verify ZIP CRCs and required SHP/SHX/DBF/PRJ members; read actual feature counts, CRS, required fields, null/duplicate IDs and fixed GEOID widths. Census blocks require GEOID20/POP20/HOUSING20; block groups require GEOID. Report source count plausibility and retain IDs as strings. Numeric count validity excludes nonfinite/negative values; do not repair source values.

Record PBF header metadata and scan entity availability/counts with reference/tag diagnostics and the same resource supervisor. Explicitly distinguish a bounded sample from complete validation. Inventory the variables catalog's structure and selected field presence without claiming that ACS observations were retrieved or its dataset vintage verified. Preserve unknown provenance for developer follow-up. Emit a discovery inventory first, then use its accepted hashes as pinned inputs. Changing an expected hash must require explicit review.

Use synthetic corruption/missing-member/duplicate-ID/hash-mismatch fixtures. Keep real statewide sources out of CI. Reconcile actual Census reads with previously observed DBF header counts (140,345 blocks and 4,058 block groups), reporting disagreement rather than changing expectations to pass.

## Acceptance and ownership

The project lead accepted the environment and experimental settings for the task 1.2 discovery smoke. The methodology/data owner must approve GIS assumptions before they become authoritative. Task 1.4 reviews actual wheel compatibility, source evidence, licensing, performance, and testing scope; `architecture_overview.md` now records the implemented package boundary.

## Task 1.3 delivered implementation

`python -m flm_pipeline inventory --config pipeline/config/denver-source.example.toml` runs as a supervised child process with the configured deadline and sampled process-tree RSS cap. It streams SHA-256 in 1 MiB chunks, checks ZIP CRCs, verifies SHP/SHX/DBF/PRJ members, iterates Census features in bounded chunks while reading identifier and count fields, validates identifier widths/duplicates/nulls and nonnegative finite count fields, and streams the full OSM entity set for counts, tags, and reference totals. It reports both actual and reader-reported Census counts against the earlier DBF observations of 140,345 blocks and 4,058 block groups. OSM references are counted but not resolved.

The example configuration now includes `variables_catalog` as an optional source entry; source hashes remain unpinned. The inventory and run report are written under ignored `data/generated/prototype/<run-id>/`. Candidate hashes are never written back to TOML. Census filename years are reported as claims; source URLs, retrieval dates, and license evidence remain null unless present in source metadata. The catalog scan records structure and selected metadata-field presence; it does not claim ACS observations or a verified catalog vintage.

The local full inventory completed with `pass_with_warnings` in 595.406 seconds and a sampled peak process-tree RSS of 126,001,152 bytes. It counted 53,710,053 OSM nodes, 4,394,383 ways, and 28,111 relations. Both Census layers' actual feature counts matched reader-reported counts and prior local DBF observations: 140,345 blocks and 4,058 block groups. Both archives passed CRC checks and contained the required sidecars. Census CRS was EPSG:4269; the 15-character block GEOIDs and 12-character block-group GEOIDs had no nulls, duplicates, width errors, or format errors. `POP20` and `HOUSING20` had no null, nonfinite, negative, or nonnumeric values. Census attributes were read for every feature, but feature geometry validity and spatial coverage were not checked. All selected catalog probes were present among its 28,475 entries. The `pass_with_warnings` status reflects incomplete source provenance; hashes remain unpinned for human review.

The discovery local report is `data/generated/prototype/20261102T231251Z-1273d781/source-inventory.json`, with its run record at `data/generated/prototype/20261102T231251Z-1273d781/run-report.json`. The Python suite passes 18 tests, including synthetic ZIP corruption, missing-member, duplicate/malformed-ID, numeric-value, and expected-hash-mismatch cases.

Task 1.1 is a design deliverable. Task 1.2 verified package installation and bounded source/GIS I/O on Windows CPython 3.12.14. Task 1.3 inventories the current local inputs; source identity, retrieval provenance, licensing, regional extraction behavior, and statewide extraction performance remain for review. Proposed future improvements include Linux lock/CI verification and a separate extraction-reader comparison; neither is an initial installation requirement.

References: [PyOsmium](https://docs.osmcode.org/pyosmium/latest/), [Pyrosm installation](https://pyrosm.readthedocs.io/en/latest/installation.html), [Osmium extraction semantics](https://docs.osmcode.org/osmium/latest/osmium-extract.html). Recheck compatibility during resolution.

## Regional contract status

Gate 1 was accepted on November 2, 2026 for contract development with documented limitations. [source-network-1](source-network-contract.md) now specifies the task 2.1 extraction semantics and supersedes the proposed selection/output details above where more precise. See the [implementation brief](extractor-implementation-brief.md) for task boundaries and preconditions. Source hashes remain unpinned. No extraction or pedestrian method is implemented or approved by this contract.


## Task 3.3 graph boundary

The [internal graph contract](routing-graph-contract.md) and `graph` command implement experimental directed multigraph assembly and structural validation after classification. JSONL retains source identities, parallel arcs, ordered geometry, international feet and base seconds independently of NetworkX. The existing locked GIS stack supplies geodesic lengths and batched GeoPackage I/O; no graph dependency is needed for assembly. Unknown candidates and unsupported walking restrictions block analytical promotion. Source selection and coverage limitations remain. Scenario comparison and Gate 3 belong to Task 3.4; traversal and browser schemas remain later tasks.

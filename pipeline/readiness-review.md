# Environment and source readiness review

Date: November 2, 2026. Task 1.4. Disposition: review complete; Gate 1 accepted by the developer on November 2, 2026 for contract development with the documented limitations. This review does not approve source hashes, methodology, or redistribution.

## Evidence and results

The Windows x86-64 / CPython 3.12.14 package environment, hash locks, bootstrap, runtime checks, installed license-file metadata, source inventory, and Python code/tests were reviewed. `pip check` passed. The current suite passed 19 tests, including a new worker-failure regression. Earlier temporary-environment recreation passed the nine tests then present; it did not run the current suite.

The prior full inventory completed in 595.406 seconds with sampled peak process-tree RSS 126,001,152 bytes. It counted 53,710,053 nodes, 4,394,383 ways, and 28,111 relations. Census counts 140,345 and 4,058 matched reader counts and prior observations; CRC and required attribute checks passed. This is streaming inventory performance, not extraction or graph capacity evidence. Hardware portability and cold-cache behavior remain unmeasured.

The saved inventory under `data/generated/prototype/20261102T231251Z-1273d781/` was edited after the scan to compact catalog fields and clarify geometry scope, with a recalculated checksum and recorded transformations. It is discovery evidence, not untouched output of the final code. Preserve it and regenerate an unedited inventory from frozen code before accepting extraction inputs.

## Findings

| Finding | Disposition |
|---|---|
| A readable passing worker result could produce parent success despite a nonzero worker exit. | Fixed. A synthetic worker returning exit 7 and passing JSON now produces failed CLI and report status. |
| All expected source hashes remain empty; archive retrieval URLs, receipts and license evidence are incomplete. | Developer must review candidate identities and supply provenance or explicitly accept the local-source limitations. Pin accepted hashes before extraction. Header replication timestamp and update URL are not download evidence. |
| Census claimed years are hardcoded by source role. Replacing an input can leave a misleading claim. | Current values are provisional for the example files only. Put claims and their evidence into the reviewed source metadata contract before generalization. |
| Wheel license metadata and binary filenames are incomplete native-license evidence. | Pyogrio bundles GEOS, SpatiaLite, curl/OpenSSL and other dependencies; PyProj/PyOsmium also bundle native components. Exact libosmium version is unverified. Map exact components to supplied notices before redistribution; no distribution clearance is inferred. |
| The license table says psutil has no separate license file. | Installed metadata identifies `psutil-7.2.2.dist-info/LICENSE`. Colorama also includes LICENSE.txt despite unspecified metadata. Improve inventory collection before using the table as a complete notice packet. |
| ZIP CRC verification lacks explicit decompressed-byte and member-count caps. | Restrict the current experiment to inventoried local files; add declared and streamed archive limits before arbitrary archive ingestion. Time/RSS limits do not establish byte limits. |
| OSM references were initially counted but unresolved; invalid node locations were diagnostic rather than fatal. Census geometry is not inspected. | Task 2.2 now fails synthetic extraction for invalid locations and missing required way-node references. Discovery success still does not establish topology or geometry validity. |
| End-to-end pinned-hash rejection and supervisor timeout/RSS/child cleanup lacked regression coverage. | Task 2.2 adds synthetic CLI rejection tests and process-tree supervisor tests. |

## Reader and extraction contract review

PyOsmium remains the regional source reader. Smoke copies raw tag maps, ordered way-node references, relation members, and string IDs while source objects are live. Task 2.2 implements extraction with SQLite-backed indexes, complete-way reference resolution, inventory reconciliation, canonical JSONL, and staged promotion. Synthetic coverage does not establish regional performance or source completeness.

Task 2.1 must retain raw tags including highway, access/foot, direction, sidewalk sides, footway/crossing, barrier, bridge/tunnel/layer, plus source identities and ordered references. Coincident coordinates must not merge distinct IDs; geometric crossings alone must not create connections. Node-inside-bbox selection can miss crossing ways without an interior node. Complete ways and the experimental margin do not prove route completeness. Relations need explicit retention and unresolved-member rules.

## Testing scope and verification

Pytest is confined to the offline Python package. Decision 0006 continues to govern frontend Vitest/Playwright. GitHub CI currently runs frontend checks only; a pinned Windows Python test job is required before CI can establish pipeline verification. Statewide sources remain excluded from CI. App-loader compatibility and routing benchmarks cannot yet be checked because those implementations do not exist.

During this review: `python -m pip check` passed; `python -m pytest pipeline/tests` passed 19 tests. A fresh statewide inventory, second environment rebuild, and frontend checks were not run. Existing scan evidence was assessed rather than repeated.

## Gate 1 disposition and next task

The developer accepted Gate 1 for contract development with the documented limitations on November 2, 2026. This permits task 2.1 using the existing environment and reader. Hashes remain unpinned; source identity acceptance, extraction execution, methodology approval and redistribution are outside that acceptance.

Before a real task 2.2 regional run: accept source identities/provenance limitations, pin the OSM hash, regenerate an unedited complete inventory from the current code/configuration, and review remaining performance and native-license limitations. The example hashes remain empty and the prior edited inventory remains discovery evidence. The extractor refuses to run without a matching pinned hash, inventory, run report, config hash, and code identity.

## Task 2.2 implementation status

The extractor command and focused synthetic tests are implemented under the source-network-1 contract. Synthetic checks cover complete ways, outside-boundary vertices, raw tags, separate coincident IDs, inclusive bounds, relation flags, empty selection, missing references, duplicate IDs, malformed input, unpinned/mismatched hashes, deterministic canonical files, failed promotion, invalid-coordinate diagnostics, and supervisor timeout/RSS/child cleanup. These checks exercise synthetic PBF data only. No real regional subset or real-source performance measurement was produced because the OSM hash is unpinned and the previous discovery inventory was edited after generation.

The full offline test command, `.venv/Scripts/python.exe -m pytest pipeline/tests -q`, passed 35 tests. Two repeat runs on the same synthetic source/config/code were saved under `data/generated/prototype/20261103T000620Z-112945b7/` and `data/generated/prototype/20261103T000625Z-5e387fc9/`. Each scanned 14 nodes, 7 ways, and 3 relations; emitted 11 nodes, 6 ways, and 2 relations; retained 17 way references; and resolved all required way nodes. Both runs reported one unresolved node relation member and one unresolved way relation member, retained as diagnostics. The canonical JSONL hashes matched across both runs: nodes `74e735fbd9bc122b6d5f1872b3604347c0788c652ba38fd3208940abede71b49`, ways `dffc6d0dcb60eb1b75877eabcd539ef78e16ae56a3b378704feb1bd824ddc22d`, relations `464b1f6c1cb6764018433e26af5fc36e24855b5398c129e918641e817631c60d`. Total worker durations were 4.187 and 5.328 seconds; sampled process-tree RSS peaks were 95,121,408 and 103,997,440 bytes at a one-second interval. These measurements describe the tiny synthetic fixture only. The linked reports record synthetic source SHA-256 `1df5bfb24b4dec1cc196bddd4124923f0e1e75f200aca234246bdbb68e6e0bd6`, config SHA-256 `03bfe06274b41d4f592e343a8ab649ba4a4e1c9c801efd93346e2cb7562c3c3e`, inventory SHA-256 `8ec4f78c76e07d5899afb8ea1b64c092c1867670866f541f3a521e66ee7c0cee`, and code identity `fda647036b5e62a3513be07cb8ae731a55476a7ae45318b8f3c48da7e0b52b7a`.

## Task 2.3 implementation status

The `export` command writes the five source-network GeoPackage layers from a validated extraction. It checks source/config/code/input identities; resolves each ordered reference against the node index; preserves way geometry, segment direction, coincident-but-distinct node IDs, tags, and relation member evidence; computes WGS84 geodesic and EPSG:26913 diagnostic lengths; and reopens all layers to verify fields, geometries, CRS, counts, uniqueness, and lengths. Repeated references, zero-length segments, duplicate coordinate sequences, and degenerate lines are retained and reported. An extraction with no selected ways produces an explicit `empty` export.

The full offline test command, `.venv/Scripts/python.exe -m pytest pipeline/tests -q`, passed 38 tests. Three new end-to-end cases cover a populated GeoPackage, an empty selection, and mutated canonical input rejection. Two export runs from the same synthetic extraction produced identical semantic hashes for all five layers. A populated example is saved locally at `data/generated/prototype/20261103T002916Z-c8973de5/source-network.gpkg`, with its report beside it. The linked report records 5 nodes, 4 ways, 7 segments, 1 relation, 3 coverage polygons, and 11 ordered node references. It reports one repeated node reference, three zero-length segments, two duplicate source-way features, and four duplicate segment features. The output is 188,416 bytes; its synthetic source SHA-256 is `8569fbe125c268692948dc270934ef7cd97415e35c764cf33fbc887a47415c3e`, code identity is `0d2d9c4cf0a65cc23d1932fccd3cb681e8daa449bb121abcfb8f1324082252bc`, and GeoPackage SHA-256 is `ba7c23d0b9418de99890eac54727f5b9540c22153e9c875ac4243e8b8aa2e765`. The semantic layer hashes, not the GeoPackage container hash, matched between repeat runs.

These results use synthetic data only. OSM source hashes remain unpinned; no real regional export or ArcGIS Pro review was performed. Gate 2 remains open pending real inspectable data and human map review.

## Regional source review status

Task 2.4 completed the available code/synthetic review and prepared the [GIS inspection procedure](gis-review.md). The real regional review is blocked by the existing source-acceptance/pinning and fresh-inventory prerequisites. Manual ArcGIS Pro and real map/source-object checks are **not run**. Gate 2 remains open; no source omission, real false link, or pedestrian permission has been established by this review.

The full offline suite passed **39 tests in 71.71 seconds** with normal workspace access. A new extraction-to-export fixture independently specifies seven endpoint pairs and five undirected source-reference components. It confirms that same-coordinate nodes 2 and 4 remain disconnected, actual shared node 2 remains shared, geometric crossings do not introduce junctions, and bridge/tunnel/barrier tags and outside-boundary vertices survive. Source-reference connectivity is not pedestrian routing. The inspectable synthetic output is `data/generated/prototype/20261103T013544Z-412cf0a7/source-network.gpkg`, linked to extraction `20261103T013539Z-925a06e7`. It has 12 nodes, five ways, seven segments, zero relations, and three coverage polygons. GeoPackage SHA-256 is `9e9125571997e4b126e6f2a76401c22fde52b53b0b7e605c22b727033e3ff9e6`; code identity is `c912eaefdd127fff3b4dd443e1969971f87eb72b9698f29a04f9a7353a257964`. Test source/config/inventory scratch inputs are disposable; fixture inventories are assembled test evidence, not full real inventory runs.

Open technical findings require disposition before regional acceptance:

| Finding | Disposition |
|---|---|
| Every extraction pass requests `locations=True`, enabling PyOsmium's default `flex_mem` location cache alongside SQLite. | Review removal of unnecessary attached-way-location caching, rerun preservation/failure checks, and measure the real supervised scan. SQLite alone does not establish bounded memory. |
| Canonical reopen validation retains all regional records/ID sets; export runs outside the resource supervisor. | Bound validation and supervise export, or obtain an explicit measured exception. No regional resource claim is accepted from synthetic tests. |
| The extraction canonical validator coerces numeric entity IDs to text for validation. | Enforce canonical string types with a negative regression. The writer currently emits strings and the exporter rejects non-string IDs; no malformed GeoPackage was demonstrated. |

An initial sandboxed focused test failed before assertions because the synthetic PBF could not be opened and scratch cleanup was denied. The full suite passed after rerunning with normal workspace access. No frontend or CI checks were run in this review. The local planning packet records named Denver search areas, exact fixture evidence, and defect dispositions. Complete actual source-object/map inspection and obtain developer Gate 2 acceptance before task 3.1.

## Task 2.4b status â€” November 3, 2026

The `earth-export` adapter now produces separately labeled synthetic `topology` and `diagnostic` profiles. It reopens the KMZ, verifies KML structure and local assets, reconciles exact node/way/segment IDs, raw tags, ordered references, lengths and coordinates against companion source evidence, checks file hashes and limits, and promotes the package only after a supervised worker succeeds. Failed timeout and promotion checks leave no promoted package. The output directory contains a manifest, KMZ, JSONL evidence, case CSV, blank observation CSV, README and final run report. Synthetic packages are ignored local outputs.

Regional export still requires accepted/pinned source identity, a fresh inventory, and successful extraction/GeoPackage export. The initial caps are 10,000 placemarks, 250,000 geometry vertices and 512 MiB aggregate payload, with up to 500 diagnostic markers. An over-limit package currently fails intact; deterministic partitions have not been implemented. The regional review profile also contains placeholder source IDs until Task 2.4d populates cases from a pinned source. The subsequent Task 2.4c user observations below establish passing synthetic selection and diagnostic checks in Google Earth browser; description usability remains an open finding. This is not Gate 2 acceptance. The existing source-reader location-cache, canonical validator storage, and GeoPackage export supervision findings remain open for Task 2.4r.

The complete offline test command, `.venv/Scripts/python.exe -m pytest pipeline/tests -q`, passed **41 tests in 102.53 seconds**. The regenerated topology packet is `data/generated/prototype/20261103T174445Z-5677649b/` with 12 nodes, five ways, seven segments, and seven expected ordered source pairs. The diagnostic packet is `data/generated/prototype/20261103T174457Z-d06c4c95/` with 11 nodes, six ways, 11 segments, two relations, and 12 diagnostic markers including zero-length, duplicate, repeated-reference, unresolved-relation, degenerate-geometry, and boundary-overhang examples. Both reports link persistent synthetic PBF/config/inventory evidence under `data/staging/prototype/earth-trials/`, and both record current code identity `c737da59eca7e442231fdeb06b99d83659a32afc2e6db2a1d2cd078f0fbab4aa`. The source hashes identify only those test PBFs. No regional source hash was pinned or used.


## Task 2.4c user topology observations

The user reports five passing checks: selectable/copyable endpoints 1 and 2 on way/10/segment/0; separate selection of coincident nodes 2 and 4; endpoints 2 and 9 on way/14/segment/0; preserved bridge/layer tags on way 11 and tunnel/layer tags on way 13; and node 8 with its segment retained outside the coverage outline. Node, segment and diagnostic folder toggles work. These are user observations, not independently repeated UI checks. The user subsequently confirmed Google Earth browser use and topology package identity 20261103T174445Z-5677649b. Exact browser/version, diagnostic packet identity, local-file mode, screenshots and load time remain unrecorded.

After clarification, the user reports that the zero-length segment imported as an inspectable point (pass) and overlapping duplicates behaved as expected (pass). The earlier unclear instruction is resolved. Description legibility has an open usability finding: descriptions are unnecessarily verbose and cryptic although basic functionality appears present. Simplify the human-facing summary to feature ID, endpoint IDs, plain-language tags and labeled lengths, keeping technical provenance available separately. No exporter or packet was changed in response to this observation. Task 2.4c and Gate 2 remain open.

Functional synthetic viewer checks are complete based on user observations. Task 2.4c remains open for disposition of the description readability finding and final viewer usability acceptance; missing environment details remain explicit evidence limitations. Regional source execution prerequisites and Gate 2 are unchanged.


## Task 2.4c description revision

Feature descriptions now show IDs, ordered endpoints, a labeled surface length and key source tags before a secondary technical section. Nodes show connected-segment counts; ways show node counts. Raw tags, exact reference/coordinate/length fields and package identities remain available in the technical section, ExtendedData and companion evidence. BalloonStyle explicitly uses the description. The revised Google Earth display awaits user review; historical functional passes apply to the earlier packets.

Verification: full offline run reported 40 passed and one new readability assertion failure in 104.71 seconds. That assertion failed to decode an escaped apostrophe; it was corrected. The two KMZ integration tests then passed in 26.35 seconds, covering preservation, HTML display ordering, repeat output, limits and failure behavior. An earlier sandboxed run failed on filesystem access; the normal-access runs are the implementation evidence. No regional run or source pinning occurred.

Current code identity: `f9756dd00db666a3ebba1ea860f844324208dd73137ac2ec2c2c2c51e6fc7303`. Revised packets:

- diagnostic: `data/generated/prototype/20261103T184302Z-5147696e`; KMZ SHA-256 `957ca13724078953a364c468192429b3a46ef0fea2416f2acbdb8cab0bf5c974`.
- topology: `data/generated/prototype/20261103T184252Z-55c7d071`; KMZ SHA-256 `07d065b6fb4b8295a526b8a51f85c86b0ddc6cbecbe558e56da107ca27806eaf`.

## Task 2.4c acceptance

The developer approved the revised descriptions and authorized Task 2.4r. This closes synthetic viewer usability for the reviewed topology and diagnostic packets (20261103T184252Z-55c7d071 and 20261103T184302Z-5147696e). Google Earth browser was reported; exact browser/version, diagnostic identity confirmation, screenshots and load measurements remain evidence limitations. This is synthetic viewer acceptance, not regional Gate 2 acceptance. Subsequent code changes invalidate processing identities for new runs but do not erase this historical viewer evidence.


## Task 2.4r repair disposition

Status: complete. The developer approved Task 2.4c revised description usability before this repair task. Regional Gate 2 remains open.

| Finding | Repair and verification |
|---|---|
| R2-02 | Fixed: production extraction passes use `locations=False`. Installed PyOsmium implementation was inspected: these handlers now avoid `NodeLocationsForWays`/`flex_mem`. Explicit required-node resolution remains unchanged. Source identity, complete-way overhang, crossings and missing-reference tests pass. |
| R2-03 | Fixed for the identified controls: canonical reopening streams records through a temporary SQLite ID index, including forward relation references, and rechecks input hashes before returning. It targets a 16 MiB SQLite page cache and rejects records larger than 16 MiB before decoding. GeoPackage worker startup, source/input preflight, construction and reopened verification run under configured timeout and sampled process-tree RSS limits. Nonzero exit, timeout, RSS failure, incomplete child cleanup, malformed worker JSON/report and failed promotion/completion cannot produce a successful published report. The parent atomically renames the validated directory and writes the completion report last. |
| R2-04 | Fixed: canonical entity IDs and both way/relation references must already be positive decimal strings. Numeric, boolean, null and float values reject. Integer-to-string conversion is explicit at the PBF reader boundary; ID 9007199254740993 remains exact. |

Verification: `.venv/Scripts/python.exe -m pytest pipeline/tests -q` passed **76 tests in 157.64 seconds**. Coverage includes preservation and failure paths, real supervisor timeout/child cleanup, real export startup rejection under a 1,024-byte RSS budget, and failed final-report rollback. A 2,000 versus 20,000 node validation regression passes with traced Python peak allocation below 4 MiB and growth below 2 MiB; tracemalloc excludes SQLite/native allocations, so this is not total process RSS evidence.

The independent command `.venv/Scripts/python.exe docs/planning/2026-11-02/review-source-network.py` passed ten saved-output checks and numeric-ID rejection. New evidence is `docs/planning/2026-11-02/source-network-repair-evidence.json`; the original review evidence is preserved. The audited GeoPackage is `data/generated/prototype/20261103T190020Z-b24b0dbd/source-network.gpkg`, SHA-256 `39f7209329f0c2cb87e18dc56a22f06dae272f5e206d2a4d14d75efc74e54d80`. It retains 12 nodes, five ways, seven exact ordered pairs and five source-reference components. Its worker took 4.187 seconds with sampled peak RSS 118,362,112 bytes, a one-second sample interval, configured timeout 1,200 seconds and RSS budget 4 GiB. These are tiny synthetic measurements only.

Verified code identity: `b2fcde79ad16fcfeb72898c76bdbb44c587e3ee11ae676ea1ef4488849513c5a`. Changes invalidate prior inventory/extraction/export identities for new processing. Historical viewer approval remains evidence for its reviewed packets. No raw regional files were changed, no regional hash was pinned, and no real inventory/extraction/export was performed.

Remaining limits: extraction still retains selection ID sets; memory per decoded record and SQLite/native overhead remain. SQLite disk usage scales with entity count. One-second RSS samples do not capture every transient peak. Parent promotion/report I/O is outside the worker deadline/RSS scope. Statewide performance, disk capacity, actual regional coverage and map review remain unmeasured. Over-limit KMZ partition generation is still a Task 2.4d dependency if required.

Next entry point: obtain explicit acceptance of the exact local OSM bytes and documented provenance/license limitations, with authorization to pin that hash. Preserve the edited discovery inventory. Pin only accepted source identities, freeze code/configuration, and generate a fresh unedited inventory before Task 2.4d extraction/export. Never adopt a discovery hash automatically. Gate 2 still requires real regional review and explicit developer acceptance; Phase 3 is not authorized by these repairs.


## OSM retrieval statement supplied by developer

The developer reports downloading the local Colorado OSM file from https://download.geofabrik.de/north-america/us/colorado.html on November 2, 2026. This supplies user-reported origin and retrieval date; exact time and a saved receipt were not supplied. Whether the file was edited, filtered or updated after download remains unconfirmed. Geofabrik's Colorado page identifies OpenStreetMap contributors and ODbL 1.0; the current page is not a receipt for the historical download.

Current local candidate: `data/raw/colorado-261101.osm.pbf`, 386,878,398 bytes, SHA-256 `6f1e9811fa0f323b240a679e7a9c0caa56f57cbf493e8e70bbb86eb37327af45`. This hash identifies current local bytes, not proof of matching historical server bytes. Source acceptance and authorization to pin remain pending; no TOML hashes were changed.


## Task 2.4d source authorization and run entry

The developer authorized pinning the previously presented OSM SHA-256 and proceeding with local inventory, extraction and exports after supplying the Geofabrik download origin/date and reporting an approximately 9pm later update on the source site. The local bytes were rehashed and still match `6f1e9811fa0f323b240a679e7a9c0caa56f57cbf493e8e70bbb86eb37327af45`. The PBF header snapshot timestamp is `2026-11-01T21:21:36Z`; a remote website update does not automatically change local bytes. Local modification history is not independently established; the authorization applies to these identified current local bytes. Unknown retrieval-time/receipt details remain explicit.

The accepted hash is pinned only in the ignored local run config `data/staging/prototype/regional-handoff-20261103T191727Z/accepted-source.toml`; the shared discovery example remains unchanged. The exact acceptance record is `data/staging/prototype/regional-handoff-20261103T191727Z/source-acceptance.json`. The historical edited discovery inventory is preserved. A new inventory is running under the frozen current pipeline and accepted config. The authorization covers local prototype processing, not publication, methodology approval or Gate 2.


## Completed regional prototype run (November 3, 2026)

This supersedes earlier pending-run statements for the accepted local OSM snapshot only. Source SHA-256: `6f1e9811fa0f323b240a679e7a9c0caa56f57cbf493e8e70bbb86eb37327af45`. Pinning remains confined to the ignored accepted run configuration; the shared discovery example and Census/catalog hashes remain unpinned.

Fresh inventory completed in 396.609 seconds with sampled peak RSS 226,123,776 bytes. Extraction completed in 971.781 seconds with sampled peak RSS 532,623,360 bytes. GeoPackage export completed in 366.437 seconds with sampled peak RSS 169,570,304 bytes. These are one local run, not a statewide capacity guarantee. Counts: 480,519 nodes, 81,323 ways, 347,819 segments, 1,389 relations; unresolved required way-node references: zero. Retained diagnostics include 1,423 repeated references and 152 duplicate features. Unresolved relation members remain explicit; zero-length segments: zero.

The full view exceeds the core 10,000-placemark cap. The developer selected smaller case-only packets explicitly marked partial. The separate [delivery adapter](regional-case-delivery-spec.md) produced 23 cases, 397 nodes, 22 ways, 379 segments and 21 touching relation records, in an overview plus one network KMZ. Its worker completed in 32.109 seconds with sampled peak RSS 166,432,768 bytes. Membership, omissions, parent identities, acceptance and payload hashes are recorded. Reopened KML/evidence checks passed, and full/partial counts reconcile. All manual regional checks remain `not_run`.

Selection gaps: no Millennium way-name match, no disjoint-reference crossing against the selected bridge example, and no zero-length diagnostic example. These do not establish regional absence beyond the reported zero-length count.

Verification: the unchanged core suite previously passed 76 tests; the separate delivery suite passed 3 tests on the final rerun in 61.44 seconds. Local selector fixture checks passed 8 topology checks and 6 diagnostic checks. Frontend commands were not run because no application, TypeScript, JSON configuration or CSS was changed by this delivery work. Regional Google Earth inspection has not run. Gate 2 remains open; Phase 3 and publication are not authorized. Exact local handoff paths and hashes are in the ignored `docs/planning/2026-11-02/active-regional-run.json`.


## Regional manual review result (November 3, 2026)

The developer reports all 23 delivered regional cases passed for package `regional-review-20261103T195734Z-9b740944`. This supersedes earlier pending manual-case statements for the delivered cases only. Statuses are recorded separately from immutable generated evidence. No case-specific notes, screenshots, browser version, final import mode or imagery dates were supplied. Missing regional examples and partial scope remain limitations. All delivery payload hashes were rechecked successfully when recording the result. The local Gate 2 packet is `docs/planning/2026-11-02/regional-gate-2-review.md`. Explicit Gate 2 acceptance remains pending; Phase 3 has not started.

## Gate 2 acceptance and policy entry (November 3, 2026)

The developer explicitly accepted Gate 2 and authorized Task 3.1. Acceptance covers the identified 23-case partial review with the recorded limitations; it does not establish routing completeness or pedestrian methodology. The [provisional policy](pedestrian-policy.md) is drafted for separate experimental acceptance. Implementation remains dependent on that decision. Generated evidence is unchanged.

## Experimental policy acceptance (November 3, 2026)

The developer accepted the four policy choices with imperial units required. Policy 0.2 specifies feet, miles and mph, preserving the agreed speed through explicit conversion. Historical source/inspection units remain unchanged. Task 3.1 is complete; evaluator implementation remains next.


## Task 3.3 experimental graph evidence (November 3, 2026)

The supervised graph builder completed a regional diagnostic product: 244,051 nodes and 607,088 directed arcs; all 347,819 source candidates reconcile (303,544 include; 24,170 exclude; 20,105 unknown). Every GIS record was reopened against JSONL. Relation auditing retains 1,389 relations and flags 1,050 unsupported restrictions; 47,490 unresolved members remain coverage warnings. Unknown candidates and unsupported restrictions block analytical promotion. Supervised duration was 380.687 seconds with 204,873,728 bytes sampled peak process-tree RSS under the 1,200-second/4-GiB limits. These are one local run, not statewide capacity evidence. The complete Python suite passed 282 tests in 261.10 seconds. The refreshed classification payload hashes match the historical Task 3.2 output. No new dependency, routing calculation, Gate 3 acceptance or publication occurred. The [internal graph contract](routing-graph-contract.md) records identity, geometry, costs and completion behavior.


## Task 3.4 comparison evidence (November 3, 2026)

The independent read-only review adapter completed on the frozen graph. Accepted/reference classifications contain 303,544/336,183 included source segments and 675/219 weak components. The extra reference segments are 12,534 accepted-policy exclusions and 20,105 unknowns, totaling 267.57 source-segment miles. Source review identified conservative kerb, level and unrelated-mode conditional treatment, plus 1,050 generic restriction blockers. There are 4,114 kerb-tagged nodes among 5,462 unknown referenced nodes. Close endpoint candidates remain unjoined; no new source repair or policy was accepted. All 28 focused review tests passed, including the pinned-JavaScript comparison and a synthetic full review round trip. Final resource observations were 82.75 seconds and 628,436,992 bytes sampled peak process-tree RSS. Immutable payload hashes and upstream identity match; the reference graph was independently reopened. Fresh manual GIS, complete regional traversal and Gate 3 acceptance remain pending. The [review procedure](graph-policy-review.md) records reproduction and interpretation limits.


## Accepted kerb revision evidence (November 3, 2026)

Policy 0.3 implements the accepted general pedestrian scope and permits exact kerb tags without a wheelchair-based filter. Available raw attributes are retained without extra data acquisition or dedicated calculations. All 346 offline/core/tool tests passed. Regional regeneration recovered 8,460 source segments / 39.77 miles; 4,114 changed node dispositions were verified as kerbs. All 81,323 way classifications and 607,088 prior arcs retain their prior meaning/geometry/costs. Graph size is 248,272 nodes / 624,008 arcs; weak/strong components are 395 rather than 675. Graph supervision measured 457.64 seconds and 205,299,712 bytes sampled peak RSS. Unknown candidates remain 11,645 and unsupported restrictions remain 1,050; complete regional promotion is blocked and Gate 3 is pending. Policy/configuration 0.2 snapshots and old outputs remain historical evidence.

# Shared validation policy

This is the verification policy for all agents. Tool-specific instruction files must not weaken or duplicate it.

## Checks available now

- `pnpm lint` runs Biome formatting and lint checks, including recommended accessibility rules and a rule preventing `src/domain/` from importing React, UI, adapters, application, or worker modules.
- `pnpm typecheck` runs TypeScript under three configurations (browser app, build tooling, and domain modules) without emitting files.
- `pnpm build` performs the same typecheck and creates the static build.
- CI's `Verify foundation` job installs the frozen dependency graph and runs `pnpm lint` and `pnpm build`.

There is no unit, golden, or browser test suite yet. The static scaffold has no calculation, loader, or persistence behavior. Do not label an empty suite as passing or claim scaffold checks validate GIS results. Manual desktop/narrow and keyboard review is required for UI changes until and alongside useful browser coverage.

## Test tooling

The isolated offline Python package uses pytest for configuration, source validation, GIS I/O, source-network GeoPackage round-trips, and worker/report failure tests. Run `.venv/Scripts/python.exe -m pytest pipeline/tests` locally on the supported Windows environment. Keep statewide files out of CI; use synthetic fixtures. This scoped addition does not replace the frontend policy below. The current GitHub workflow runs the locked Python suites and synthetic package checks.

Vitest for unit and integration tests and Playwright for browser tests are added in the first PR that introduces behavior to test (see [decision 0006](decisions/0006-test-tooling-introduced-with-the-first-testable-behavior.md)). Pure analytical tests and pinned deterministic integration fixtures run in ordinary CI. Live external-service checks run separately from the required CI checks and report service availability separately from application regressions.

## Verification by change

| Change | Required evidence |
|---|---|
| Documentation | Proofreading, source accuracy, relative links, policy/architecture consistency |
| TypeScript/configuration | Lint; typecheck; production build for app/config/dependency changes |
| UI/map | Typecheck/build, actual desktop/narrow visual inspection, keyboard behavior, relevant browser regressions as introduced |
| Calculations | Focused independent/unit fixtures, reviewed numerical differences, method version and approved baseline |
| Data/pipeline/schema | Source inventory, package validation, pipeline tests, real app-loader compatibility, benchmark comparison |
| Offline KML/KMZ inspection | Synthetic pipeline tests; independent XML/evidence/hash/count checks; actual Google Earth UI loading, folder toggles and selection recorded separately as manual evidence |
| Storage/session/worker | Contract tests and real browser round-trip/reload/failure or job-ordering tests |
| Deployment | Exact built artifact, base/subdirectory paths, host/data access, output checks, release identity and rollback |

Add meaningful tests with the first nontrivial behavior, using repository scripts verified for the chosen tools.

## Analytical benchmark governance

Golden expectations preserve an accepted output; they do not independently establish that the method is correct. An authoritative fixture needs approved method/source versions, inputs/settings, independently reviewed reference outputs, tolerances, reviewer, and approval date.

On failure, explain whether the cause is a regression, approved method/data change, environment variability, or invalid reference. Agents may propose a baseline change but may not approve it themselves. Preserve prior expectations and obtain the designated methodology/data owner's approval before replacing them.

### Reference benchmarks without a reference model

No reference model exists (see [methodology](methodology.md)), so references come from:

- Hand-calculated tiny networks.
- An independent reproduction of sample walksheds with a desktop GIS or a separate Python workflow. It is built separately from the application code and covers urban, suburban-with-barriers, rural, and near-data-boundary origins.
- Expert review of the resulting maps.

For each benchmark, record inputs, tool and version, settings, outputs, tolerances, reviewer, and approval date.

### Property checks

Include these once routing exists:

- A larger time budget never reduces reachability under a fixed network and cost model.
- Station order does not change ID-associated results.
- A duplicate station does not increase unique-coverage totals.
- A partitioned network and the unpartitioned network give the same reachable set within tolerance.
- A cancelled or outdated job never replaces a newer result or appears as a zero score.

### Geometry comparison

- Compare reachable edges and costs separately from polygons and downstream metrics.
- Compare polygons by validity, area, symmetric difference, and coverage of critical points.
- Never use screenshots, total area alone, or vertex order as the primary test.

Candidate GIS cases include disconnected networks, bridges versus at-grade crossings, out-of-coverage origins, partition boundaries, partial edges, holes/barriers, overlap, suppressed/missing values, ties, and zero denominators.

### Test real implementations

Exercise the real data loader and the real worker, not only in-memory stand-ins. Check that worker and direct calculations agree for identical inputs.

## Browsers and accessibility

- Test on the agreed browser list, with real Microsoft Edge where relevant.
- The conformance target is in requirement R-09 (WCAG 2.1 AA minimum, 2.2 AA target; see [requirements](requirements.md)).
- Check keyboard-only operation, focus visibility, status announcements, contrast, and noncolor cues.
- Review PDF output for tags, reading order, and table structure.
- Keep accessible result tables and keyboard alternatives in scope when map interaction is implemented.
- Automated checks alone do not establish conformance.

## Input robustness

- Bound file size and decompressed archive size.
- Reject or report duplicate IDs and unsupported geometry.
- Handle coordinate-system declarations explicitly.
- Neutralize spreadsheet-formula-like values in CSV exports.
- A failed import leaves current work unchanged.

## Performance evidence

- Measure 1 and 10 stations, with 50 as a stress case.
- Record hardware, browser, cold or warm cache, downloaded bytes, peak memory, and time to results.
- A CI timing on one runner is not a capacity claim.

## Data source acceptance

Before a data source is adopted beyond a prototype, record its license, attribution requirements, and any share-alike obligations that affect published data releases (for example, the ODbL for OpenStreetMap-derived data).

## Human acceptance and closeout

Report exact commands and outcomes as pass, fail, or not run. For visual changes, report viewport widths and what was inspected. Preserve relevant failures and limitations rather than treating an unavailable check as success.

Before client acceptance, agree supported browsers, dataset/input limits, performance thresholds, accessibility version/level, and the PDF review process.

A release needs the source commit, artifact and data identities, check results, known limitations, and an approved staging/production/rollback process. The foundation workflow publishes only the development preview, not a release.


## Experimental graph assembly checks

Task 3.3 adds synthetic pytest checks for shared source junctions, disconnected coincident IDs and grade crossings, parallel arcs, pedestrian direction, barrier/unknown suppression, zero-length exclusions, exact imperial cost examples, large string IDs, restriction exemptions, deterministic JSONL, stale/forged classifications, corrupt graph/GIS rejection, empty graphs and failed-worker promotion. The `graph` command supervises construction and reopens every routing GeoPackage record, checking CRS, attributes, coordinates and counts against JSONL. Its run report records sampled process-tree memory and timing separately from parent promotion. Structural evidence does not establish complete routes; station traversal, component review, expanded coverage and browser compatibility remain later checks.


## Frozen graph policy review

Run `.venv/Scripts/python.exe -m pytest pipeline/tools/tests/test_graph_review.py -q` for the independently versioned review adapter. It tests reference rule examples, weak versus strong connectivity, parallel edges, coincident IDs, deterministic component membership, diagnostic gap screening, corrupt-input rejection and a real classification/graph/review fixture round trip. With the local pinned reference cache, it also checks 100 tag combinations against the original JavaScript functions; absent cache is an explicit skip. The regional review verifies immutable input/output hashes and reopens graph structure. Upstream GeoPackage/manual GIS evidence remains separately identified. Review completion does not accept Gate 3, modify policy, or establish a new authoritative benchmark.


Policy 0.3 adds explicit kerb tests for general pedestrian traversal across curb subtypes and available wheelchair tags, continued access/locked/conditional precedence, exact spelling, shared-junction connectivity and old-config rejection. The accepted revision was checked by a direct old/new artifact audit: changed nodes must be source kerbs, other way classifications remain identical, only unknown candidates become included, and all prior arcs retain endpoints/geometry/length/cost. Preserve original 0.2 artifacts and their identities; revised counts are a separately accepted experimental rule outcome, not a replacement authoritative benchmark.


## Accepted experimental routing references

The developer accepted the hand-calculated metric cases, tolerances, 10-minute diagnostic budget, source-node test origin, and separate 100-foot edge-origin experiment in the [routing reference specification](../pipeline/routing-reference-spec.md). The [acceptance manifest](../pipeline/fixtures/routing-reference-acceptance-v1.json) records the exact reviewed specification, fixture, and settings hashes; the test loader rejects changed or draft bytes. Task 4.2 runs literal source records through the real PBF reader, extractor, classifier, graph builder, and validators. It checks source-ID adjacency independently and demonstrates that false-junction and forbidden-edge mutations fail the fixture assertions. These remain experimental references. No traversal tests, authoritative methodology, station-access claim, or complete regional coverage claim is established by Task 4.2.


## Experimental traversal checks

The focused routing suites exercise all accepted literal metric results through traversal, exact node membership, directed intervals, disconnected and coincident IDs, partial gaps, charged access, zero/exhausted budgets, strict inside/outside costs, monotonicity, input-order invariance and duplicate-origin union. They also check planar/geographic projections, dateline interpolation, snap limits, source-node coalescing, ambiguity and invalid selection, boundary/policy statuses, corrupt frozen inputs and common-core differences. The real PBF fixture continues through the graph adapter and traversal with independent closed-form equatorial lengths.

Task 4.4 completed the accepted regional diagnostic and expanded extraction. `.venv/Scripts/python.exe -m pytest pipeline/tests pipeline/tools/tests -q` passed 387 tests in 214.91 seconds. The supervised regional run exited successfully in 321.891 seconds with sampled process-tree peak RSS 1,266,471,936 bytes (4 GiB limit); all report checks passed. Both graphs were clipped and compared in the common core with zero recorded differences. The 1/10/50 source-node timing cases ran. This is measured local Python performance, not browser performance or a 1/10/50 station benchmark. Results remain incomplete because of unknown policy candidates, unsupported restrictions, unresolved relation members, and unestablished coverage. The optional edge-snap case and manual GIS visual review were not run; the report supplies a checklist for that review. Browser compatibility is not tested by these tasks. See [routing implementation](../pipeline/experimental-routing.md) and the ignored Task 4.4 closeout.

## Experimental package contract and packager checks

Task 5.2 adds `pipeline/tools/package_network.py`, a full Draft 2020-12 JSON Schema validator, cross-file graph/GIS/provenance checks, deterministic semantic identity, immutable local promotion, and a real synthetic release builder. `python -m pytest pipeline/tools/tests/test_package_network.py -q` exercises schema metaschema checks, semantic identity/order invariance, duplicate/nonfinite JSON rejection, closed schemas, repeat synthetic builds, manifest-bound expected-result sidecars, and connectivity/direction/cost corruption even after file hashes are refreshed. The existing `pipeline/tests/test_package_contract.py` suite continues to cover the literal fixture expectations. CI installs the pinned Windows Python locks, runs both Python suites, builds two synthetic releases, checks equal semantic graph IDs and validates both. No statewide data download occurs in CI.

The authorized local `prepare-release` workflow rehashes the pinned raw OSM source, checks frozen inventory/graph/regional reports and output artifacts, constructs the package, validates schema/content/GIS/hashes under the 1,200-second and 4-GiB sampled-RSS limits, then atomically promotes a new ignored release ID. Run `python pipeline/tools/package_network.py validate-package --manifest <release>/manifest.json` to independently validate it again. The local package closeout records exact commands, paths, hashes, sizes and outcomes. The current regional product remains diagnostic; this task does not prove browser load/traversal, complete network coverage or station entrance access. Those are Gate 5A work.

Task 5.2 local verification: `.venv/Scripts/python.exe -m pytest pipeline/tests pipeline/tools/tests -q` passed 409 tests in 461.95 seconds; `pip check` and package-tool `py_compile` passed. The final regional package validated and promoted in 1,096.562 seconds with 715,796,480 bytes of sampled process-tree peak RSS, within the accepted caps. The synthetic package and its manifest-bound literal expectation also validated. The first full-suite attempt encountered sandbox temporary-directory permission errors; the rerun with scratch-directory access completed successfully. GitHub Actions CI and frontend lint/build were not run locally. No browser validation occurred in Task 5.2.

## Task 5.3 browser evidence

The [local browser review](../pipeline/browser-network-review.md) defines reproduction and human acceptance steps. Vitest covers literal directional/zero/missing-origin cases, four frozen Python references (F01â€“F04), schema negatives and semantic-hash parity. Python and TypeScript share a structural negative corpus. Playwright fetches the actual generated package in Chromium at root/subdirectory URLs, verifies manifest-bound outputs, rejects corrupt/missing/mixed/unsupported candidates, preserves the active graph, checks cancellation, narrow layout and keyboard focus. Desktop and narrow screenshots were inspected locally. Gate 5A acceptance, regional browser/memory performance, other browser engines and deployment remain pending. Frozen reference JSON has a targeted formatter exemption to preserve accepted bytes; lint rules still apply.

Gate 5A update (November 5, 2026): the developer confirmed the 150-foot result and all requested companion checks and accepted the synthetic local browser workflow. Historical pending statements above describe the earlier review state. Regional/browser memory capacity and coverage remain unestablished.

## Task 5.5 Census ingestion checks

`pipeline/tests/test_census_normalize.py`, `test_census_http.py`, and `test_census_sample.py` exercise the proposal-gated quartets, key-safe HTTP/cache behavior, retry and response failures, explicit cache refresh identity, exact ACS headers and GEOIDs, synthetic source ZIP geometry reads, complete joins, and reopened GeoPackage attributes/geometries. Run them with `.venv/Scripts/python.exe -m pytest pipeline/tests/test_census_normalize.py pipeline/tests/test_census_http.py pipeline/tests/test_census_sample.py -q`. The safe example config must fail before network access while experiment acceptance and source pins are blank. These tests are deterministic and do not contact Census. Task 5.5 acceptance still needs an authenticated live ACS query and a complete join/reopened output from the approved local sources; until then, record those checks as not run and do not claim a Census demonstration.


## Polygon and allocation experimental checks

Run `python -m pytest pipeline/tests/test_spatial_experiment.py -q` for independent
P01/P02 rectangle symmetric differences, P03 conceptual barrier spillover,
full-area denominators, overlapping union, rural sensitivity, holes/multipart,
boundary inclusion, invalid/duplicate source units, explicit CRS/axis order,
mixed-polygon GeoPackage reopening and actual Python-to-TypeScript execution.
Run `pnpm test` for pure-domain hand-calculated counts/rates, zero/missing
handling, invalid input and union bookkeeping. No expected values are derived
from the implementation to clear failures. The cross-language test needs the
repository's installed locked Node dependencies as well as Python.

The [local runner](../pipeline/spatial-experiment-guide.md) verifies frozen input
hashes, geometry validity, component/hole counts, width symmetric difference and
containment, reached-line midpoints, independent high-accuracy count summation,
reopened outputs and no source mutation. It reports actual run resources under
the existing supervision limits. Rectangle equality uses 1e-6 square foot;
arithmetic uses 1e-9 absolute / 1e-12 relative count tolerances for engineering
reconciliation only. Conceptual barrier tests do not replace regional named
barrier visual inspection. Browser polygon integration, complete coverage,
allocated uncertainty and authoritative methodology remain unverified.

Census status update: accepted-source authenticated ingestion and reopened county
joins passed for 576 block groups. All B08201 requested quartets were missing and
remain unavailable. Earlier pending live-ingestion statements are historical.


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

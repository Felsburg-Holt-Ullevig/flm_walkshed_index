# Shared validation policy

This is the verification policy for all agents. Tool-specific instruction files must not weaken or duplicate it.

## Checks available now

- `pnpm lint` runs Biome formatting and lint checks, including recommended accessibility rules and a rule preventing `src/domain/` from importing React, UI, adapters, application, or worker modules.
- `pnpm typecheck` runs TypeScript under three configurations (browser app, build tooling, and domain modules) without emitting files.
- `pnpm build` performs the same typecheck and creates the static build.
- CI's `Verify foundation` job installs the frozen dependency graph and runs `pnpm lint` and `pnpm build`.

There is no unit, golden, or browser test suite yet. The static scaffold has no calculation, loader, or persistence behavior. Do not label an empty suite as passing or claim scaffold checks validate GIS results. Manual desktop/narrow and keyboard review is required for UI changes until and alongside useful browser coverage.

## Test tooling

Vitest for unit and integration tests and Playwright for browser tests are added in the first PR that introduces behavior to test (see [decision 0006](decisions/0006-test-tooling-introduced-with-the-first-testable-behavior.md)). Pure analytical tests and pinned deterministic integration fixtures run in ordinary CI. Live external-service checks run separately from the required CI checks and report service availability separately from application regressions.

## Verification by change

| Change | Required evidence |
|---|---|
| Documentation | Proofreading, source accuracy, relative links, policy/architecture consistency |
| TypeScript/configuration | Lint; typecheck; production build for app/config/dependency changes |
| UI/map | Typecheck/build, actual desktop/narrow visual inspection, keyboard behavior, relevant browser regressions as introduced |
| Calculations | Focused independent/unit fixtures, reviewed numerical differences, method version and approved baseline |
| Data/pipeline/schema | Source inventory, package validation, pipeline tests, real app-loader compatibility, benchmark comparison |
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

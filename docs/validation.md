# Shared validation policy

This is the verification policy for all agents. Tool-specific instruction files must not weaken or duplicate it.

## Checks available now

`pnpm lint` runs Biome formatting and lint checks, including recommended accessibility rules and a rule preventing `src/domain/` from importing React, UI, adapters, application, or worker modules. `pnpm typecheck` checks `src/` and `vite.config.ts` without emitting files. `pnpm build` performs the same typecheck and creates the static build. CI's `Verify foundation` job installs the frozen dependency graph and runs `pnpm build`.

The static scaffold has no calculation, loader, or persistence behavior and no unit/golden/browser test suite. Do not label an empty suite as passing or claim scaffold checks validate GIS results. Manual desktop/narrow and keyboard review is required for UI changes until and alongside useful browser coverage.

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

Add meaningful tests with the first nontrivial behavior, using repository scripts verified for the chosen tools. Pure analytical tests and pinned deterministic integration fixtures should run in ordinary CI. Keep live external-service checks distinguishable from application regressions.

## Analytical benchmark governance

Golden expectations preserve an accepted output; they do not independently establish that the method is correct. An authoritative fixture needs approved method/source versions, inputs/settings, independently reviewed reference outputs, tolerances, reviewer, and approval date.

On failure, explain whether the cause is a regression, approved method/data change, environment variability, or invalid reference. Agents may propose a baseline change but may not approve it themselves. Preserve prior expectations and obtain the designated methodology/data owner's approval before replacing them.

Candidate GIS cases include disconnected networks, bridges versus at-grade crossings, out-of-coverage origins, partition boundaries, partial edges, holes/barriers, overlap, suppressed/missing values, ties, and zero denominators. Compare network reachability and costs separately from polygon quality and downstream metrics; matching screenshots or total area alone is insufficient.

## Human acceptance and closeout

Report exact commands and outcomes as pass, fail, or not run. For visual changes, report viewport widths and what was inspected. Preserve relevant failures and limitations rather than treating an unavailable check as success.

Before client acceptance, agree supported browsers, dataset/input limits, performance thresholds, accessibility version/level, and the PDF review process. Automated checks alone do not establish conformance. Keep accessible result tables/keyboard alternatives in scope when map interaction is implemented.

A release needs the source commit, artifact and data identities, check results, known limitations, and an approved staging/production/rollback process. The foundation workflow does not publish a release.

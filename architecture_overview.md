# Architecture overview

Updated: October 29, 2026. Status: version 1 repository foundation.

## Implemented structure

This is one code repository containing a React + TypeScript + Vite web scaffold and a documented location for future offline preparation. The app currently renders a static development introduction. It makes no GIS/API requests and performs no analysis, storage, or exports.

```text
index.html -> src/main.tsx -> src/ui/App.tsx
                              + styles.css

src/domain/    boundary documented; calculations pending
src/adapters/  boundary documented; external integrations pending
pipeline/      offline preparation boundary documented; implementation pending
data/          small-fixture/catalog policy documented; datasets pending
```

`AGENTS.md` is the shared agent policy. `CLAUDE.md` imports it. `DEVELOPER.md` is the human workflow guide; `docs/validation.md` is the shared verification matrix. Detailed local planning reports are excluded from Git pending publication review.

## Toolchain and build

- Node 24.19.0 and pnpm 11.25.0 are pinned. `pnpm-lock.yaml` records the dependency graph.
- React 19, TypeScript 7, Vite 8, and the official React plugin form the initial toolchain; `package.json` is authoritative for exact versions.
- TypeScript is strict, with unchecked-index and exact-optional-property checks. It emits no sibling JavaScript files.
- `pnpm build` typechecks and generates static output in `dist/`. The relative asset base is intended for root or subdirectory hosting and must be checked on the eventual host.
- Local development and build previews bind to loopback on ports 5173 and 4173.
- GitHub CI installs from the frozen lockfile and runs the production build. Actions are pinned to verified commit revisions. CI does not deploy the website.

## Boundaries for subsequent work

Authoritative walking costs, aggregation, normalization, and scoring belong in pure domain modules independent of React and GIS service payloads. Adapters validate external values and translate them into explicit typed inputs. UI code collects settings and renders outcomes.

Add an application coordination layer and worker directory when the first analysis job requires them. Jobs will need identifiable inputs/versions, progress, cancellation, stale/failed states, and protection from an older result overwriting a newer request. This behavior is not implemented in the foundation.

Data preparation should remain an offline workflow. Display tiles, routing connectivity, and analytical indicator data are separate products connected through a versioned manifest. Large inputs/archives belong in approved external storage; only small cleared fixtures and metadata belong in normal Git.

## Provisional direction and open decisions

| Topic | Current position |
|---|---|
| Repository topology | One repository initially; preparation can split later through a stable contract |
| Runtime analysis | Browser processing is the first feasibility candidate; no engine is selected |
| Map | MapLibre is a prototype candidate; no map dependency is installed yet |
| PMTiles | Planned display/preparation deliverable; routing representation remains unproven |
| Indicator access | Static indexed packages and approved feature services remain options |
| Session storage | Versioned local exchange/autosave design remains open |
| Methodology | Original spreadsheet/model and human-approved definitions are required |
| Hosting | CDOT-managed final host and staging process remain pending |
| Accessibility/reporting | Acceptance criteria and a validated PDF path remain pending |
| Licensing/branding | Client/code/data/third-party distribution decisions remain pending |

The next useful technical slice is one station and a small approved geographic sample, with independently reviewed reachability/aggregation evidence. Do not label scaffold checks as analytical validation.

Update this file when implemented boundaries, toolchain, data flow, or deployment change. Use short decision records for material accepted choices and keep task status in the issue/PR workflow.

# FLM Walkshed Index

A web application in development for evaluating first/last mile walking access around transit stops and stations in Colorado.

The intended workflow is to create or upload station locations, generate network walksheds, examine individual metrics and index scores, and export results. This repository currently contains the development foundation and a static introduction page. GIS data, analysis, scoring, session storage, and reporting are future work.

## Maintainer entry points

- [Developer guide](DEVELOPER.md): working locally, reviewing agent changes, CI, and releases.
- [Architecture overview](architecture_overview.md): implemented boundaries and open technical decisions.
- [Shared agent instructions](AGENTS.md): policy used by Codex and Claude Code.
- [Validation policy](docs/validation.md): checks and analytical acceptance.
- [Methodology status](docs/methodology.md): decisions required before calculations are implemented.
- [Data contract status](docs/data-contract.md): preparation/runtime boundaries and versioning requirements.
- [Preparation pipeline](pipeline/README.md): where offline data work will live.

## Development

Use Node **24.19.0** and pnpm **11.25.0**. The exact package manager and dependency versions are recorded in `package.json` and `pnpm-lock.yaml`.

| Command | Purpose |
|---|---|
| `pnpm install --frozen-lockfile` | Install the committed dependency versions |
| `pnpm dev` | Run the local development page at `http://127.0.0.1:5173/` |
| `pnpm typecheck` | Check TypeScript without generating JavaScript files |
| `pnpm build` | Typecheck and generate the static site in `dist/` |
| `pnpm preview` | Inspect that build locally at `http://127.0.0.1:4173/` |

The preview server is for local review. Production hosting and a public application URL have not been configured. CDOT's hosting, methodology, accessibility, data publication, branding, and final distribution requirements remain subject to coordination.

## Data and distribution

Large GIS inputs and output archives belong in approved external storage, with small reviewed fixtures and metadata in Git. Keep client/background documents, credentials, and personal session files outside public source history. This repository does not yet establish a code license or grant rights to CDOT branding or third-party data.

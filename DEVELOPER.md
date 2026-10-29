# Developer and reviewer guide

## What exists today

The repository has a minimal React/TypeScript/Vite application, shared contribution guidance, lint, typecheck, and build checks, and a CI workflow that deploys a development preview. It does not yet load GIS data or perform calculations. The [architecture overview](architecture_overview.md) describes the boundary between implemented structure and planned capabilities, and [requirements](docs/requirements.md) lists what the finished application must do.

The source repository is [Felsburg-Holt-Ullevig/flm_walkshed_index](https://github.com/Felsburg-Holt-Ullevig/flm_walkshed_index). `main` is the integration branch. Changes are reviewed on feature branches before merging. A GitHub source page or a green check is not a deployed website.

## Setup

Required versions: Node 24.19.0 and pnpm 11.25.0. Installation fails on any other Node version by design (`engineStrict`).

**Windows**

1. Clone the repository **outside OneDrive** (for example `C:\dev\flm_walkshed_index`); synchronized folders can lock or corrupt `node_modules`.
2. Install Node 24.19.0 with the Windows installer from `https://nodejs.org/dist/v24.19.0/` (file `node-v24.19.0-x64.msi`).
3. In a new terminal, run `npm install -g pnpm@11.25.0`.
4. Check that `node --version` prints `v24.19.0` and `pnpm --version` prints `11.25.0`.

**macOS/Linux**

Use a Node version manager to install 24.19.0 (for example `fnm install 24.19.0`, which reads `.node-version`), then run `npm install -g pnpm@11.25.0`.

**Cloud agent containers**

Containers may ship another Node version. The install fails with an engine error until Node 24.19.0 is on `PATH`.

Node is pinned in `.node-version` and enforced by `engineStrict` in `pnpm-workspace.yaml`; pnpm is pinned by `packageManager` in `package.json`. Dependency versions are saved exactly (`saveExact`) and `pnpm-lock.yaml` is committed. Do not introduce a second lockfile. A normal clone needs no credentials for installation of the public packages selected here.

Keep machine-specific paths in local notes rather than shared commands. Avoid concurrent edits to one checkout.

## Commands

Run these from the repository root.

| Command | Expected result |
|---|---|
| `pnpm install --frozen-lockfile` | Installs the exact dependency graph from the lockfile |
| `pnpm dev` | Serves the development page at `http://127.0.0.1:5173/` until stopped |
| `pnpm lint` | Reports formatting and lint problems, if any |
| `pnpm format` | Applies automatic formatting and safe lint fixes |
| `pnpm typecheck` | Reports TypeScript errors, if any, without emitting files |
| `pnpm build` | Runs typechecking and creates `dist/` static assets |
| `pnpm preview` | Serves the built page at `http://127.0.0.1:4173/` until stopped |

Both servers bind to the local computer and use fixed ports. If a port is occupied, identify the process instead of stopping an unrelated service. Opening `index.html` directly from disk is not the application workflow; Vite serves the TypeScript entry point.

## Roles and review

- The project lead (`caseywalrath`) reviews all changes.
- Contributions from other developers require the lead's approval.
- The lead's own pull requests, including those opened by agents under the lead's account, merge after CI passes.
- Agents never merge.

Two repository rulesets on `main` implement this:

- **main – safety and CI** (no bypass): changes reach `main` only through a pull request; the `Verify foundation` check must pass with an up-to-date branch; conversations must be resolved; force pushes and branch deletion are blocked.
- **main – review**: one approval and code-owner review are required. Repository admins may bypass this ruleset on pull requests only, which lets the lead merge their own PRs after CI passes.

`.github/CODEOWNERS` requests the lead's review on every change. Methodology acceptance requires the designated reviewers' approval (see [methodology](docs/methodology.md)). Independent technical/GIS review is appropriate for major analytical boundaries and release readiness.

## Commit identity

Use your GitHub noreply address. Project lead: `Casey Walrath <256605663+caseywalrath@users.noreply.github.com>`. Other contributors: find yours under GitHub **Settings → Emails**.

## Requesting and reviewing changes

Tasks are GitHub issues created with the [task template](.github/ISSUE_TEMPLATE/task.yml): the user outcome, scope, representative input and expected result, requirement IDs, and who accepts it. Keep numerical methodology questions explicit.

Use a descriptive branch, implement the bounded task, run relevant checks, and open a PR that says `Closes #N`. The PR should provide:

- a plain-language explanation of the change;
- a local or approved hosted preview, or screenshots for visible changes;
- numerical before/after examples when calculations change;
- check results, limitations, and data/method version changes;
- recovery or rollback information when saved data or deployment changes.

Review whether you can complete the intended workflow and whether the reported examples match expectations.

Write public change descriptions and comments in neutral technical language: explain the change, rationale, verification, and limitations. Keep conversational history and unnecessary personnel/process details out of the record.

## Automated checks and deployment

The single `CI` workflow runs for PRs, pushes to `main`, and manual dispatch. On PRs it installs from the frozen lockfile, lints, typechecks, and builds (`Verify foundation`). On `main`, it then deploys the verified build to GitHub Pages (`Deploy GitHub Pages`); a failed verification prevents deployment. Neither job claims GIS accuracy, accessibility conformance, or test coverage. See [validation](docs/validation.md).

Pages must have **Settings → Pages → Build and deployment → Source** set to **GitHub Actions**. After a deployment, GitHub reports the site URL in the Actions run and the `github-pages` environment. The build uses relative asset paths, so the same output works at the Pages project URL and in a subdirectory. The page footer shows the short commit identifier of the deployed build. Pages hosts the current scaffold as a public development preview; it is not a CDOT environment.

Dependabot proposes monthly, grouped updates for application and Actions dependencies. `@types/node` major versions are ignored because they follow `.node-version`. Review and test updates; there is no automatic merge or deployment.

## Where files belong

- `src/ui/`: presentation and interaction.
- `src/domain/`: authoritative, independently testable calculations when introduced.
- `src/adapters/`: validated external data/service/storage boundaries when introduced.
- `pipeline/`: offline preparation, separately executable from the public app.
- `data/`: small reviewed fixtures/catalog metadata; full raw, staging, and generated packages are ignored.
- `docs/`: public-safe engineering guidance. The local planning packet is ignored pending separate publication review.
- `public/`: intentionally public static assets copied into the website build. Do not place contracts, credentials, or internal notes there.

There are no production credentials, remote data releases, or hosted sessions in the foundation. Do not use frontend environment variables for publishing secrets. An ignored local file can still leak a value if application code bundles it.

## Deployment, recovery, and handoff

For a future release, identify the source commit, locked dependency graph, app artifact, configuration, data release IDs, method version, and validation evidence. Promote a tested artifact through the approved staging process. Retain the previous compatible app/data combination and verify a rollback procedure before public release. Confirm the production host's asset paths and behavior before release. Record actual URLs and CDOT maintenance owners once approved.

To recover from an application change, use the prior approved source/release through the normal review process. Preserve unrelated local work and avoid history rewrites. Raw inputs require an approved external source/backup location; Git ignore rules are not backups. Session migration and data-package recovery procedures will be specified when those features exist.

## Open decisions

Open decisions are tracked as GitHub issues labeled `decision`.

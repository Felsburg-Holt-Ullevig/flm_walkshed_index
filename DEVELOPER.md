# Developer and reviewer guide

## What exists today

The repository has a minimal React/TypeScript/Vite application, shared agent guidance, a production-build check, and a pull-request workflow. It does not yet load GIS data or perform calculations. The [architecture overview](architecture_overview.md) describes the boundary between implemented structure and planned capabilities.

The source repository is [Felsburg-Holt-Ullevig/flm_walkshed_index](https://github.com/Felsburg-Holt-Ullevig/flm_walkshed_index). `main` is the integration branch. Proposed changes should be reviewed on feature branches before merging. A GitHub source page or a green check is not a deployed website.

## Getting a local working page

Install Node 24.19.0 and pnpm 11.25.0, then obtain a checkout of this repository. Use the commands below from its root folder. Coding agents should perform routine commands where their environment allows them; human leads should receive the outcome and evidence rather than unexplained command lists.

| Command | Expected result |
|---|---|
| `pnpm install --frozen-lockfile` | Installs the exact dependency graph from the lockfile |
| `pnpm dev` | Serves the development page at `http://127.0.0.1:5173/` until stopped |
| `pnpm typecheck` | Reports TypeScript errors, if any, without emitting files |
| `pnpm build` | Runs typechecking and creates `dist/` static assets |
| `pnpm preview` | Serves the built page at `http://127.0.0.1:4173/` until stopped |

Both servers bind to the local computer and use fixed ports. If a port is occupied, identify the process instead of stopping an unrelated service. Opening `index.html` directly from disk is not the application workflow; Vite serves the TypeScript entry point.

The runtime is pinned in `.node-version`; pnpm is pinned by `packageManager` in `package.json`. Dependencies are exact versions and `pnpm-lock.yaml` is committed. Do not introduce a second lockfile. A normal clone needs no credentials for installation of the public packages selected here.

The current agent environment supplies Node/pnpm through its bundled runtime. Another agent may need its own tool paths. Keep those machine-specific paths in session notes, not shared commands. The repository is suitable for Windows and Linux development; GitHub CI checks the Linux build. Avoid concurrent edits to one checkout. A nonsynced checkout can help if a synchronized folder causes locks, but moving files is a separate task.

## Requesting and reviewing agent work

Create a task describing the user outcome, scope, representative input/expected result, and who accepts it. Keep numerical methodology questions explicit. The [task template](.github/ISSUE_TEMPLATE/task.yml) provides those fields.

The agent should use a descriptive branch, implement the bounded task, run relevant checks, and open a PR when authorized. The PR should give you:

- a plain-language explanation of the change;
- a local or approved hosted preview, or screenshots for visible changes;
- numerical before/after examples when calculations change;
- check results, limitations, and data/method version changes;
- recovery or rollback information when saved data or deployment changes.

Review whether you can complete the intended workflow and whether the reported examples match expectations. Ask the other lead to review meaningful changes. An independent technical/GIS review is appropriate for major analytical boundaries and release readiness; an agent reviewing its own code cannot approve the scientific method.

## Automated checks and GitHub settings

The `CI` workflow runs for PRs, pushes to `main`, and manual dispatch. Its `Verify foundation` job installs from the frozen lockfile and typechecks/builds the app. It does not claim GIS accuracy, accessibility conformance, or test coverage. See [validation](docs/validation.md).

After its first successful PR run, an administrator can establish a rule for `main`:

1. Require a pull request and one approval from another reviewer.
2. Require the `Verify foundation` status check.
3. Require conversations to be resolved; prevent force pushes and branch deletion.
4. Apply the protection to administrators as appropriate for the team's emergency process.

The workflow file does not configure these settings. Verify the actual GitHub rule and its behavior. Add CODEOWNERS after the co-lead's GitHub identity and review responsibilities are confirmed. The initial PR should remain open for human review; agents should not infer merge approval from an implementation request.

Dependabot is configured to propose weekly application and Actions dependency updates. Review and test those updates; there is no automatic merge or deployment.

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

Production hosting is pending CDOT coordination. CI produces a build but performs no deployment. The relative asset base supports testing under a subdirectory; confirm the actual host's behavior before release.

For a future release, identify the source commit, locked dependency graph, app artifact, configuration, data release IDs, method version, and validation evidence. Promote a tested artifact through the approved staging process. Retain the previous compatible app/data combination and verify a rollback procedure before public release. Record actual URLs and CDOT maintenance owners once approved.

To recover from an application change, use the prior approved source/release through the team's normal review process. Preserve unrelated local work and avoid history rewrites. Raw inputs require an approved external source/backup location; Git ignore rules are not backups. Session migration and data-package recovery procedures will be specified when those features exist.

## Questions still requiring owners

Confirm the co-lead reviewer identity, scoring and GIS-method approvers, original model/benchmark location, data publishing owner, CDOT test/production hosts, accessibility/PDF acceptance, support contact, code license, and branding permissions. Track these as decisions/tasks rather than allowing an agent to choose silently.

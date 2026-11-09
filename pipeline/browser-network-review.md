# Local browser network review



The experimental harness loads a validated network package and computes source-node reachability in a dedicated worker. It does not establish regional coverage, station entrances, polygons, population or scores. Gate 5A requires developer review of an actual local result.



## Open the review



Run these commands from the repository root with the pinned Node/pnpm and Python environments installed:



```text

pnpm install --frozen-lockfile

pnpm schema:check

pnpm build

node scripts/review-server.mjs

```



Open `http://127.0.0.1:4174/` in a browser. Keep the terminal open. The loopback server serves built app files and five JSON files from the existing synthetic release `synthetic-f01-task52-20261104-e`; it exposes no general data-directory listing and copies no package into `dist` or `public`. Stop it with Ctrl+C. The same review is available at `http://127.0.0.1:4174/review/` to exercise subdirectory asset and package paths.



If the fixture is absent in a fresh checkout, create it first:



```text

python pipeline/tools/package_network.py build-synthetic --release-id synthetic-f01-task52-20261104-e

```



An existing successful release must not be overwritten. The builder writes its manifest-bound literal expectation separately under `data/generated/prototype/network-packages/_expected-results/`. The server intentionally serves only this small synthetic release. Regional browser loading and memory capacity have not been established.



## Review steps



1. Leave the manifest URL at `./__network-fixture__/manifest.json`. Select **Load package**. Confirm that the active release is the synthetic release above, with `synthetic_closed` coverage. Load time and bytes appear in the status line.

2. Leave source node ID at `1` and budget at `36.576` seconds. Select **Calculate reachability**. Confirm **150.000000 feet**. Node 1 must cost 0 seconds; node 2 must cost 24.384 seconds; node 3 must be absent. The first source segment covers 0–100 feet and the second covers 0–50 feet. The detailed JSON binds the result to the actual release, graph and manifest SHA-256.

3. Change the source node to `3`, leaving the same budget. Calculate again. Confirm zero feet and only node 3: the second segment permits forward walking only.

4. Set node `1` and budget `0`. Confirm zero feet and only node 1. Set node `999` and a positive budget; confirm `no_network` and null outputs. This is distinct from a valid zero-length result.

5. Confirm that changing a node or budget removes the previous result. Try a missing manifest URL and confirm an explicit error while the active release remains available. Restore the original URL. The automated browser suite additionally injects corrupt, mixed, unsupported and missing payloads.

6. Resize to a narrow window. Use Tab to move through labels and buttons and Enter/Space to activate buttons. A pending load or calculation exposes **Cancel**. No map is required for this review.

7. Report pass, fail or defer for the observed 150-foot result, directional behavior, zero/missing distinction and usability. Gate 5A is pending until the developer accepts these observations. Census specification is Task 5.4 and requires that acceptance.



## Boundaries and checks



`src/adapters/network-package.ts` registers checked-in Draft 2020-12 schemas offline, validates bounded UTF-8 JSON, checks duplicate keys and safe numbers, hashes required payloads, verifies bindings/topology/costs/geodesic lengths and reproduces the Python semantic identity. Candidate failure preserves the active graph. The pure domain module owns traversal and source interval union. A dedicated worker has a 120-second deadline and termination on cancellation; fetching has an independent 120-second deadline and byte caps. Synchronous schema and content-validation sections can delay cancellation until control returns; no hard browser memory ceiling is claimed.



`pnpm schema:generate` derives loader types from the schemas; `pnpm schema:check` rejects stale types. `pnpm test` checks literal expectations, four accepted Python references and semantic-hash parity. `pnpm test:browser` starts the loopback review server and fetches the actual generated package with Chromium; run `pnpm build` first and `pnpm exec playwright install chromium` once when required. Python and TypeScript consume the same small structural negative corpus. Browser tests compare the generated manifest-bound expectation rather than inventing a passing result.



Required commands are `pnpm lint`, `pnpm typecheck`, `pnpm build`, `pnpm schema:check`, `pnpm test`, and `pnpm test:browser`. CI includes synthetic browser verification; no CI execution or deployment is implied by local success. Six accepted byte-sensitive reference JSON files have a narrow formatter exemption in `biome.json`; lint remains enabled, and their bytes and acceptance hashes are preserved. Contract schema formatting changes have no structural or numerical effect.



## Dependencies and measured scope



Runtime additions are Ajv 8.20.0 (MIT; shared schema validation) and geographiclib-geodesic 2.2.0 (MIT; WGS84 ellipsoidal length verification). Development additions are json-schema-to-typescript 16.0.0 (MIT), Vitest 5.1.0 (MIT) and Playwright 1.64.1 (Apache-2.0). Versions are exact and locked. The complete application JavaScript bundle is approximately 402 kB minified / 123 kB gzip, plus a 1.42 kB worker; this is the whole resulting bundle, not an isolated dependency delta. No regional package is bundled.



The local Chromium trial fetched 4,749 bytes. Its measured root/subdirectory load times were 139.6 ms / 99.2 ms and end-to-end worker calculation 99.2 ms / 32.6 ms in the final recorded trial. Browser memory was not measured. These observations apply only to the three-node synthetic package and do not support regional capacity claims.


Gate 5A update (November 5, 2026): the developer confirmed the 150-foot result and all requested companion checks and accepted the synthetic local browser workflow. Historical pending statements above describe the earlier review state. Regional/browser memory capacity and coverage remain unestablished.

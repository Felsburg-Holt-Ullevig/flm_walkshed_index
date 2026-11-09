# Census ingestion implementation brief

Task 5.5 status: the experiment and local sources are accepted; authenticated ingestion, both county joins and reopened outputs passed. Population is available for all 576 block groups; household/no-vehicle quartets were null throughout, so those indicators remain unavailable. See the local Task 5.5 closeout for execution evidence. Follow the [variable specification](census-variable-spec.md) and [spatial experiments](spatial-allocation-spec.md); this task does not implement spatial allocation.

## Configuration and execution

Use `census-sample-1`, dataset `2024/acs/acs5`, state `08`, county allowlist `031,073`, and the twelve exact quartet fields in the specification plus `NAME`. Separate keys bind source product/year, metadata snapshot hash, accepted source hashes, request schema version, normalization version and cache snapshot. Unknown configuration keys and counties fail. No new runtime dependency is necessary: the implementation uses the existing locked GIS stack and standard-library HTTP/hash/JSON utilities.

The CLI is `python -m flm_pipeline census-sample --config <local-config>`. The safe example is [census-sample.example.toml](config/census-sample.example.toml); it intentionally cannot run because its acceptance value and source hashes are blank. Copy it under ignored `data/staging/prototype/`, then fill it only after the developer/data owner accepts the experiment and the exact source identities. The loader rejects unknown keys, other counties, unpinned sources, unsafe paths, and output locations outside the ignored Census sample directories.

The optional metadata hashes can pin validated official 2024 group metadata snapshots. If left blank, official metadata is still checked for the selected concepts, labels, quartet fields and types; its observed hash and retrieval time are recorded for review.

Set `CENSUS_API_KEY` in the same local PowerShell process used to run the command. Do not place the key in the config or chat. The command passes it only in an HTTPS ACS data request. It does not put the key in cache identity, reports, logs, command arguments, or browser code. A valid cached ACS response can be reused without the key. Set the key only in the current process environment and remove it after the live request. Cached responses require no key. Do not include the value in shell history, command arguments or saved files.

The first configured `cache.snapshot_id` is an immutable cache namespace. Repeated runs with the same ID reuse checksum-valid raw snapshots. An explicit refresh uses a new ID; the report compares response hashes with the most recent intact earlier snapshot for the same query. Cache corruption fails without replacement. Cached bodies and sanitized request metadata live under ignored `data/generated/prototype/census-cache/`; completed samples live under ignored `data/generated/prototype/census-samples/`. Failed runs stay under ignored `data/staging/prototype/census-samples/` without a completion report.

## Requests, credentials and cache

For each approved county issue one request to `https://api.census.gov/data/2024/acs/acs5` with:

```text
get=NAME,B01003_001E,B01003_001EA,B01003_001M,B01003_001MA,B08201_001E,B08201_001EA,B08201_001M,B08201_001MA,B08201_002E,B08201_002EA,B08201_002M,B08201_002MA
for=block group:*
in=state:08 county:031 tract:*
```

URL-encode parameter values; substitute county `073` for the second request. The geography hierarchy must remain state/county/tract/block group. The intended response has thirteen requested columns plus `state`, `county`, `tract`, `block group`; validate exact header names with no duplicates or unexpected columns. Column order may vary; map by name. Validate every row width and string geographic component, reject duplicate GEOIDs and HTML/error bodies even with HTTP 200. A 204/empty response cannot pass as a county with zero residents.

Read `CENSUS_API_KEY` only from the local process environment. Do not ask for it in chat, put it in TOML or frontend code, or log it. The HTTP adapter adds the documented `key` parameter only to the outgoing HTTPS request. URLs stored in metadata omit that parameter entirely. Sanitize HTTP exceptions before logging because exception text may contain the actual URL. Disable request/debug URL logging; cache keys and command lines contain no secret. Do not forward a key across redirects: reject redirects. No browser data request or new remote service is introduced.

Fetch and cache the official B01003/B08201 group metadata for the **2024 five-year** dataset, validating every selected field and its attributes. Metadata generally does not require a key, but record actual HTTP outcomes. Do not promote a dataset using the local unverified-year catalog as a substitute when official metadata cannot be verified.

Provisional engineering bounds: 30-second request timeout; at most four attempts per request; retry network timeouts, 429 and 5xx only, with 1/2/4-second backoff. Honor Retry-After only up to 60 seconds; longer waits stop with a retryable error. Authentication, 4xx other than 429, bad JSON and schema errors stop without retries. Limit each streamed body to 32 MiB and a complete supervised stage to 20 minutes / 4 GiB sampled process-tree RSS, using the existing supervisor. Fail resource limits instead of shrinking county coverage. These are unmeasured prototype caps.

Canonical cache identity excludes the key and includes endpoint, release year, sorted field set, exact geography predicates and normalization version. Store raw response bytes, SHA-256, timestamp, status, sanitized parameters and metadata snapshot hashes under ignored `data/staging`/`data/generated`. Each successful raw snapshot is immutable. A normal repeat reuses a checksum-valid complete snapshot; no automatic TTL refresh. Explicit refresh creates a new snapshot and reports differences. Validate cached bytes/shapes as strictly as live bytes. A corrupt cache fails with diagnostics; do not silently replace evidence. Never write a key-bearing exception/body into the cache; authentication/error bodies are not promoted data.

## Ordered implementation tasks

1. Load approved configuration and accepted source hashes, verify input/output containment and rehash ZIPs/catalog. Validate ZIP CRC and required members with existing inventory helpers. Refuse raw/output collisions and existing successful release IDs.
2. Build the pure normalization interface. For each quartet return raw tokens, numeric estimate/MOE or null, independent estimate/MOE status and annotations. Implement the sentinel ordering, annotation precedence and count constraints exactly. Preserve unknown/missing classifications. Test all documented sentinels, unknown codes, decimals, nulls, true zero and valid estimate with unavailable MOE.
3. Implement bounded metadata/data HTTP adapters and immutable cache. Unit tests supply controlled responses for success, 200 HTML, 204, malformed JSON, missing/duplicate columns, wrong row lengths, timeout, retry exhaustion, 429, 401/403, redirects, oversize, cancellation and exception redaction. Verify repeat cached runs issue zero requests. The data-query key must never appear in captured logs/reports.
4. Read full polygons/attributes for approved counties from each source ZIP; retain GEOID strings. Validate component/ID agreement, uniqueness, finite/nonnegative raw population/housing counts, CRS, nonempty polygon type and geometry validity. Reject invalid geometry with IDs; do not silently call make_valid. Leave statewide raw data unchanged.
5. Join the complete county ACS and 2024 block-group key sets one-to-one. Output counts for requested/received rows, geometry rows, duplicated keys and unmatched keys on both sides. Require zero unmatched keys for a complete join. Keep excluded counties as explicitly outside sample, not missing data. Do not join 2020 blocks to ACS by prefix.
6. Write separate `blocks-2020.gpkg` and `block-groups-2024-acs.gpkg`, normalized compact records and sanitized raw/cache metadata. Include unmodified source geometry and both source and transformed CRS identities. If exporting a projected diagnostic layer, retain the original geographic layer separately. Reopen all outputs and reconcile IDs, geometry, values/null status, field types, CRS, counts and file hashes.
7. Promote only a complete validated release under an ignored new ID. Failure leaves staging diagnostics; no consumable completion manifest. Emit report code/environment/config/source/metadata/cache identities, source and filtered counts, per-variable valid/missing/sentinel totals, duration and sampled RSS, and pass/fail/not-run outcomes. Do not add these files to the v1 routing manifest, whose closed schemas have no Census fields.

## Acceptance evidence and exclusions

Use meaningful synthetic fixtures and existing repository scripts; no real Census download in CI. Actual Task 5.5 acceptance requires at least one successful **key-authenticated** county query and a reopened one-to-one joined product; cached fixture success is reported separately. Verify all approved counties or mark the run incomplete. Sum counts only within their original vintage/geography, and reconcile full county records before station-area filtering. No count agreement between 2020 and ACS is expected. Raw source MOEs are retained; allocation and derived MOEs remain unimplemented.

No source pins, credentials, score weights, crosswalk, spatial repair or public data delivery can be inferred from this wiring brief. After Task 5.5, review the actual inputs and join evidence before Task 5.6 polygon/allocation implementation.

Implementation evidence recorded November 5, 2026: focused synthetic checks passed for normalization, HTTP/cache safety, response validation, source geometry reads, one-to-one joins and GeoPackage reopening. The safe example fails closed as intended. No approved local run configuration exists, `CENSUS_API_KEY` is not set in the current terminal, no authenticated ACS observation request was made, no county join was run against accepted inputs, and no sample GeoPackage was promoted. The Task 5.5 implementation is ready for source/method acceptance and then a supervised local run; Task acceptance is still pending live evidence.

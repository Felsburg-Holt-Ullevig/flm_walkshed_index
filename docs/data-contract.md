# Data contract status and boundaries

Status: preparation/runtime boundary agreed in principle; machine-readable schemas and file formats are pending the first approved data task.

## Separate products

- **Display:** tiles and styles for drawing the map.
- **Routing:** connected nodes/edges, traversal costs, pedestrian eligibility, and complete boundary links.
- **Indicators:** analytical geography, metric inputs, aggregation definitions, and reference distributions.

PMTiles is a candidate display/preparation product; ordinary cartographic tiles are not assumed to contain a valid routing graph or sufficiently precise analytical geometry. The initial app has no data endpoint or loader.

## Required contract content

For each prepared release, define a stable release ID, schema/graph versions, coverage, CRS/units, source years/URLs/hashes, processing revision/parameters, output URLs/checksums, attribution/distribution conditions, and app compatibility. Each metric needs a stable ID and approved semantics, including denominator and missing/suppressed-value policy.

Use immutable release paths and a small validated manifest. Publish a complete validated package before promoting its pointer, and retain the previous compatible release. Do not mix graph and indicator versions accidentally.

Record app revision, method version, data/reference release IDs, station inputs, and settings in future sessions/results/exports. Define compatibility and migration behavior before introducing stored files. Runtime validation is required even where TypeScript types exist.

The first implementation should use a small reproducible fixture with provenance. Keep cross-language field definitions generated from or validated against one explicit contract. Preparation tests and app-loader tests must exercise the same sample product. Refer to [methodology](methodology.md) and [validation](validation.md) before defining a schema.

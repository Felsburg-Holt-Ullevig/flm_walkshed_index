# Data contract status and boundaries

Status: preparation/runtime boundary agreed in principle; machine-readable schemas and file formats are pending the first approved data task.

## Separate products

- **Display:** tiles and styles for drawing the map.
- **Routing:** connected nodes/edges, traversal costs, pedestrian eligibility, and complete boundary links.
- **Indicators:** analytical geography, metric inputs, aggregation definitions, and reference distributions.

PMTiles is a candidate display/preparation product; ordinary cartographic tiles are not assumed to contain a valid routing graph or sufficiently precise analytical geometry. The initial app has no data endpoint or loader.

## Required contract content

- **Metric definition fields:** stable ID, definition, source field, unit, data year, numerator and denominator, missing and suppressed-value policy, spatial aggregation rule, score direction, method version.
- **Release manifest fields:** release ID, schema and graph-format versions, coverage, CRS and units, source vintages, URLs and hashes, processing revision and parameters, output URLs and checksums, license and attribution references, compatible application versions, and a source inventory including skipped or rejected records with reasons.
- **Schemas:** one machine-readable schema for each cross-language boundary (JSON Schema for manifests and session files), with binary graph formats documented separately. Do not maintain two handwritten field lists.
- **Results record:** application commit, method version, data release IDs, normalization reference, analysis settings, station inputs, and session schema version.
- **Partitioned routing data:** stable boundary node and edge identity; the search continues across partitions as needed. The map viewport is never an analytical boundary.

Use immutable release paths and a small validated manifest. Publish a complete validated package before promoting its pointer, and retain the previous compatible release. Do not mix graph and indicator versions accidentally.

Define compatibility and migration behavior before introducing stored files. Runtime validation is required even where TypeScript types exist.

The first implementation should use a small reproducible fixture with provenance. Preparation tests and app-loader tests must exercise the same sample product. Refer to [methodology](methodology.md) and [validation](validation.md) before defining a schema.

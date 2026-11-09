# Local allocation measurements v1

This boundary is separate from the network-package v1 manifest. It is not a
browser release, scoring contract, or public data product.

`weights.schema.json` is the machine-readable authority. Both the Python GIS
writer and Node arithmetic adapter validate it at runtime. It carries a polygon
identity, a Census release identity, explicit incomplete coverage, and named
allocation sets. A set states its original source-variable names and unique
station/diagnostic IDs. Its rows preserve string GEOIDs, full source polygon area,
intersection area (both square feet), representative-point membership, and
nullable additive counts. Missing fields are rejected. Negative/nonfinite values,
duplicate unit/set IDs, zero source area and out-of-range weights fail semantic
validation. Geometry validity/CRS are checked before constructing this boundary.

Combined unique sets must be measured after geometric union. The domain API
requires that operation and unique station IDs; it cannot prove an untrusted
adapter actually performed the union. The local run records and reopens the
geometries as evidence. Per-station totals must never be summed as unique totals.

`src/domain/allocation.ts` contains the GIS-independent arithmetic types and
functions. Source-format adaptation stays outside this module. The local Node
adapter calls this source directly using Node's TypeScript stripping; no extra
build/runtime dependency is required. Results identify allocation method/version,
complete total or null, known subtotal, missing-unit coverage, clamping, paired
rate status and `not_quantified` derived uncertainty. Source MOEs remain in the
separate GIS/source evidence, never manufactured as allocated MOEs.

See [execution and review guide](../../../pipeline/spatial-experiment-guide.md).

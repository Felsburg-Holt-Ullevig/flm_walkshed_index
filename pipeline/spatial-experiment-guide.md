# Local polygon and allocation experiment

Status: experimental implementation. The accepted spatial methods are in
[spatial-allocation-spec.md](spatial-allocation-spec.md). This is a network
corridor coverage experiment. It does not establish a pedestrian-accessible
land boundary, complete network coverage, verified station access, or FLM scores.

## What it demonstrates

The GIS adapter reads the accepted frozen `reachable_edge_portions` layer. Those
lines already contain only reached source offsets, using the accepted geodesic
interpolation. The adapter explicitly transforms WGS84 lines and NAD83 Census
polygons into EPSG:26913 with XY axis order. It buffers each reached line by
25 feet and 50 feet on each side, with flat caps and mitre joins (limit 5), then
unions each scenario. No node disks, geometry repairs, water subtraction, or
network connections are introduced. Areas are reported in square feet/acres.
Mixed polygon layers explicitly wrap single polygons as MultiPolygons before
writing; this preserves coordinates and supports exact GeoPackage reopening.

Uniform area allocation multiplies a source count by the fraction of the **full
source geometry** covered. Representative-point allocation assigns the full
count if the corridor covers a deterministic interior point, including its
boundary. These are sensitivity comparisons. Neither locates actual residents.
The second method can change sharply at a point boundary, particularly in large
rural units. ALAND/AWATER remain source attributes in square meters; they are
not the area denominator or a water mask. Points and source attributes,
including ACS estimate/annotation/MOE quartets, are retained in the evidence.

The Python adapter writes geometry measurements. The local Node adapter validates
those measurements against the separate
[weights schema](../contracts/allocation-experiment/v1/weights.schema.json), then
calls the pure TypeScript module under `src/domain/allocation.ts`. It uses the
same module a browser caller can import; the current browser harness does not
load Census or polygon results. No application or GIS runtime dependency is added.

## Reproduce locally

Use the existing locked Python environment and `pnpm install --frozen-lockfile`
setup in [README.md](README.md). Run from the repository root:

```powershell
.venv\Scripts\python.exe pipeline/tools/run_spatial_experiment.py --handoff docs/planning/2026-11-02/active-regional-run.json
```

The handoff must identify accepted Task 5.4 methods, the frozen Task 4.4 routing
report/GeoPackage and the Task 5.5 Census report by exact SHA-256. The command
rechecks all consumed Census output hashes and the routing GeoPackage before
processing and again before completing. It does not fetch Census or need an API
key. Do not change source hashes just to clear a failed check.

Each run gets a new ID under ignored
`data/generated/prototype/spatial-experiments/`. It runs under the existing
20-minute/4-GiB sampled process-tree limits. A failure remains under
`data/staging/prototype/spatial-experiments/` with a log and no consumable
completion report. Correct the reported problem and run again; preserve frozen
upstream artifacts and failed evidence. A successful build is promoted once.
The completion report records exact code, settings, inputs, outputs, environment,
timing and sampled RSS. These are local measurements, not browser capacity.

## Files to open

1. Open `comparison.csv` for the allocation table. Each row states the geographic
   sample, corridor width, source vintage, allocation method and variable. Blank
   `complete_total` means unavailable. `known_subtotal` is only the sum of usable
   covered records. `missing_units` and `missing_intersection_sqft` show the gap.
   Fractional estimates are intentional; display rounding is not a calculation.
2. Open `allocations.json` for paired household-rate status and exact domain
   results. Missing household fields yield `percent: null` with `missing_pairs`.
   A valid zero numerator yields zero percent when its denominator is positive;
   a zero denominator yields null. Source MOEs are not scaled or combined.
3. Open `comparison.gpkg` in a viewer that supports GeoPackage. Its layers are
   `reached_source_intervals`, `polygon_comparisons`, `full_census_units`, and
   `representative_points`. All use EPSG:26913. Viewer colors have no prescribed
   analytical meaning. Filter `polygon_id` or `set_id` to avoid displaying every
   scenario at once.
4. Open `run-report.json` for validity, component/hole counts, symmetric
   differences, critical-point checks and immutable file identities.

`weights.json` contains one measurement row per full source unit and scenario.
`sourceAreaSqft` is the full denominator; `intersectionAreaSqft` is its covered
area. The exact version is `allocation-weights-1`. The schema is local and separate
from the closed network-package v1 contract. Its `coverage` remains
`not_established`. Source count arithmetic lives in TypeScript, geometry in the
adapter. The local CLI can reproduce arithmetic alone:

```powershell
node scripts/allocate-experiment.mjs <run>/weights.json <new-local-output>/allocations.json
```

The output path must not already exist. Keep these files in ignored local storage.

## Review in plain language

For Denver, compare the narrow and wide corridors with reached lines visible.
The polygons should follow those lines, retain interior gaps, and cover their
midpoints. Wider corridors should contain the narrow corridor. They can cover
land across a river, fence or divided road; that overlap does **not** create a
walking connection. The convex hull is labeled `negative_control_no_allocation`
and has `allocation_allowed = false`; it intentionally spans gaps and never
enters the count calculations. Regional barrier-side visual review remains a
human check; geometric validity alone does not establish accessibility.

For Lincoln, every comparison is named `lincoln-synthetic-*`. These are
100-foot square areas placed around representative points of large rural source
units, with a second overlapping square and their unique union. They are not
routes or stations. Compare A, B and `unique`: the unique total uses the polygon
union, not the sum of A and B. Each vintage uses its own diagnostic anchor;
do not interpret the 2020 and ACS areas as identical station locations.

Inspect the large rural difference between uniform area and representative
points. A tiny area can receive a tiny fraction under uniform area but an entire
unit's count under representative-point assignment. That difference shows why
neither method is a precise local population measurement. It is not an error bar.

The accepted Census sample has population but no usable household/no-vehicle
values. Those totals and rates must remain unavailable. Do not interpret a known
subtotal of zero as evidence that no households exist. Missing MOE alone does not
erase a usable estimate; derived uncertainty is always `not_quantified`.
Missingness is conservatively reported for every geometrically covered unit,
even if representative-point assignment gives that unit zero weight.

`synthetic-reference.geojson` uses a local plane in **international feet**, not
longitude/latitude. Do not import it as a geographic map. It records the accepted
P01 rectangle and P03 conceptual river point. The tests separately compare the
buffer with an independently constructed rectangle, cover partial intervals,
holes/multipart units, gaps, duplicate areas, boundary points, zero/missing counts,
paired rates and CRS axis order. No expected values are regenerated from outputs.

## Verification and next task

```powershell
.venv\Scripts\python.exe -m pytest pipeline/tests/test_spatial_experiment.py -q
pnpm test
pnpm typecheck
pnpm lint
```

Synthetic rectangles compare within 0.000001 square foot. Projection tests use a
separate 0.000001-meter central-meridian check and 0.000000001-degree round trip.
Arithmetic reconciliation uses absolute 1e-9 count / relative 1e-12 tolerances;
these are engineering comparisons, not source precision or uncertainty claims.
Only floating-point weight overshoot within 1e-12 may be clamped, and the number
of clamped weights is reported. Larger overshoot and invalid geometry fail.

The next reproduction task should run this command into a new release ID after
the existing source/Census prerequisites, verify every output hash, and compare
the structured outcomes without requiring binary GeoPackage hashes to match
across runs. It must also validate the existing synthetic network package and
browser fetch path. Browser polygon/Census integration, a land mask, replacement
household variables, regional barrier inspection and authoritative methodology
remain separate work or decisions.

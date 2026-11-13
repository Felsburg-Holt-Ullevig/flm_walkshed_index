# Offline walk-tile reference tests

These local experimental references compare a reconstructed tile network with its
unpartitioned source graph. They are separate from the final product routing
engine. [Decision 0012](../docs/decisions/0012-plan-a-reference-tests.md) records the
approved six origins and numerical method. Existing source-node and charged-access
fixtures retain their historical behavior.

## Units and interpretation

Use exactly **2.8 mph**. The complete network budgets are 1,232 feet at 5 minutes,
2,464 feet at 10 minutes, and 3,696 feet at 15 minutes. Lengths and original-source
offsets use international feet. Times use minutes or seconds. EPSG:4326 coordinates
use longitude, latitude in degrees. The geometric connector is recorded and
consumes zero walking seconds. It does not test whether a fence, railway, highway,
or other barrier intervenes.

Source node IDs establish connections. Coincident coordinates and geometric
crossings do not create connections. Interior snaps enter only the selected source
segment, respecting its allowed direction. Endpoint snaps enter the source node's
permitted connections. Partial reached intervals retain their original source
orientation and copied lengths.

Policy omissions, unsupported restrictions, unresolved relation members, and
unestablished coverage remain limitations. A prepared extent or an unreached
extraction boundary does not prove street completeness. Numerical failures and
out-of-range origins are distinct from successfully executed results with no
positive reached length. No polygons, Census findings, or scores are produced.

## Numerical implementation

The foot-scaled WGS84 semi-major axis is 20,925,646.325459316 feet, with reciprocal
flattening 298.257223563. Candidate endpoint distances and segment lengths provide
triangle-inequality lower bounds. Every unique included segment participates in
this search; a candidate is skipped only when its guarded lower bound proves it
cannot win or fall within 500 feet.

For a remaining candidate, the complete arc must lie in a verified local
convexity domain about the origin. The runtime radius cap is 1,000,000 feet,
well inside the WGS84 curvature-based convexity bound. Within that domain, the
distance derivative brackets the global closest position. Bisection and convex
tangent lower bounds refine the position and distance. This uses the
[convexity of geodesic distance in a bounded-curvature neighborhood](https://pmc.ncbi.nlm.nih.gov/articles/PMC2735114/)
rather than assuming a single local minimum from sampled positions.

Derivative uncertainty first uses a conservative symmetric root bracket. If that bracket already meets the source-offset target, its resolved position is preserved. If it is too wide, separate signed derivative bounds tighten the left and right extents under the same convexity bound; the distance guard and acceptance targets remain unchanged.

The numerical target is at most 0.000001 foot of distance and source-offset
uncertainty. A 0.0000001-foot distance guard and range-dependent derivative guard
account for floating-point geodesic calculations. These are engineering error
bounds, not formal interval-arithmetic guarantees or claims of source survey
accuracy. The underlying [geodesic algorithm](https://arxiv.org/abs/1102.1215)
provides the direct/inverse calculations. Work limits, unsupported numerical
domains, unresolved thresholds, and unresolved nearest-candidate ordering raise
explicit numerical failures.

No guard enlarges the 500-foot acceptance limit. Exact inclusive comparison is
tested separately from coordinate roundoff: a coordinate generated nominally
500 feet away may have an uncertainty interval crossing the limit and must fail
numerically. Exact shared-point or ellipsoid-reflection ties use northernmost
latitude and then source ID. Distinct source IDs remain distinct connections.

## Preparation

The preparation command reads the accepted local source handoff, creates separate
Greeley, Broomfield, and Fraser extractions, and retains whole selected ways and
segments. Each box has a 6,000-foot nominal margin, with its minimum origin-to-edge
distance checked against the approved 5,000-foot minimum. The source PBF and
historical configurations are preserved. A local policy copy uses the separately
named `plan-a-walk-reference-2.8-v1` setting at exactly 2.8 mph; all eligibility
rules remain policy 0.3. The resulting tile manifests state the actual sample counts and
limitations. Existing Denver files are reused without modification.

The source evaluator's individual eligibility audit records retain
`public-walk-experiment-0.3`. The new configuration/report scenario names the
2.8-mph cost setting; it does not change those eligibility decisions. Reference
traversal uses copied lengths and the exact distance budgets above.

```powershell
.venv/Scripts/python.exe pipeline/tools/prepare_walk_samples.py --release-id <new-sample-id>
.venv/Scripts/python.exe pipeline/tools/build_walk_reference.py --samples-index data/generated/prototype/walk-samples/<new-sample-id>/sample-index.json --output data/generated/prototype/walk-references/<new-reference-id>
```

For a source inventory or extraction that needs more execution time, add `--stage-seconds 7200` to preparation. The default remains 1,200 seconds. The selected limit is written into each new source configuration before its fresh inventory runs; prior inventories and failed outputs remain historical evidence. Classification and graph workers retain their separate existing limits.

Choose new IDs; existing destinations are never overwritten. Partial failed
preparations remain diagnostic material and have no completed sample index.

## Outputs and inspection

The reference output directory contains `reference/cases.json`,
`reference/walk-reference.gpkg`, and `reference/validation.json`.

`cases.json` records entered origins, selected source identities, source-oriented
offsets, snap coordinates and distances, and the complete reached interval list
for each time budget. Rejected origins have a reason and null result metrics;
they are not successful zero-length walksheds. Network entries identify the tile
release, source reconstruction results, extraction bounds, and limitations.

Import `walk-reference.gpkg` through the transit analysis tool's GeoPackage import.
It provides `origins`, `snaps`, `connectors`, and `reached_streets` layers. Filter
`reached_streets` by `case_id` and `minutes` to compare one origin and budget.
Connectors are geometric inspection lines. Reached lines are densified with at
most 50 feet between geodesic positions for display; analytical results remain the
source offsets in `cases.json`.

The writer reopens every GeoPackage record and compares CRS, geometry, attributes,
and layer counts. This does not establish compatibility with the separate viewing
application. Import and visual review must be reported separately.


## Source and tile audit

After all samples complete, run the separate audit against their final index:

```powershell
.venv/Scripts/python.exe pipeline/tools/audit_walk_samples.py --samples-index data/generated/prototype/walk-samples/<sample-id>/sample-index.json --output data/generated/prototype/walk-sample-audits/<new-audit-id>
```

The audit checks completed source reports, canonical way-reference pairs, original
node identities and coordinates, whole boundary segments, graph directions and
2.8 mph costs. It compares copied tile records exactly and checks cell membership
with rational clipping. A separate foot-scaled WGS84 length recomputation uses the
existing graph validation tolerance and reports its observed difference; it never
replaces copied source lengths. The report measures serialized network files and
individual gzip level-9 sizes, including minimum, median, nearest-rank 95th
percentile, maximum, and totals. It writes a new local JSON/Markdown audit folder
and preserves the tile release.


For an independent graph and saved-output comparison, run:

```powershell
.venv/Scripts/python.exe pipeline/tools/independent_walk_reference_check.py . --samples-index data/generated/prototype/walk-samples/<sample-id>/sample-index.json --references data/generated/prototype/walk-references/<reference-id>
```

This checker implements its own Dijkstra traversal, source-to-tile mapping,
extraction-margin lower bounds, and display-geometry reconstruction. Its snap
comparison reuses the reference snapping implementation; it is not a second
independent snapping algorithm. It validates all six saved cases and reopens the
GeoPackage. Automated reopening does not establish viewing-application import or
human visual acceptance.

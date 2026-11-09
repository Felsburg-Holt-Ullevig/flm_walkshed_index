# Provisional polygon and allocation experiments

Versions: `corridor-polygon-experiment-1` and `allocation-comparison-1`; status accepted for the local experiment, November 5, 2026. Reachability retains `experimental-reachability-1` and its accepted seconds/feet semantics. No authoritative population method or walkshed boundary is selected by this proposal.

## Polygon construction and barriers

Keep reached source intervals as the primary network evidence. Convert partial offsets to their exact source-ordered geometry using the accepted geodesic interpolation; do not buffer whole source segments when only part was reached. Transform coordinates explicitly through a documented adapter into EPSG:26913 for the Colorado sample, with XY axis order. Its native linear unit is meters: convert the requested international-foot width by exactly 0.3048, compute areas consistently and report square feet/acres (43,560 square feet per acre). Preserve the source CRS and transformation/version metadata. Never calculate planar area directly in longitude/latitude.

Compare two corridor polygons: buffer the reached line pieces **25 feet** or **50 feet** on each side, using flat end caps and mitre joins (limit 5), then geometric union. Preserve holes and disconnected components; no hole filling, smoothing or connectivity repair. Do not add node disks. Zero positive reached length produces an empty polygon, not an origin circle. A shared reached junction is still a network connection; coincident disconnected geometry remains separate source evidence even if buffers overlap. Polygon overlap is a property of this area proxy and must not add routes.

Include a convex hull of reached endpoints only as a negative-control display layer. Three noncollinear points are needed for a positive-area hull; otherwise output empty with a reason. It intentionally demonstrates bridging gaps and barriers and is **excluded from population allocation**. No concave-hull tuning or unexplained alpha value is authorized.

A corridor can extend across a river, divided highway, fence or forbidden property even when traversal correctly excludes a connection. There is no approved water/parcel/barrier mask. Therefore name the output **network corridor coverage experiment**, never a proven pedestrian-accessible land polygon. Inspect named barrier-side points, disconnected networks, grade crossings and holes against reached edges. Do not declare the polygon valid merely because its geometry is valid. Record every buffer spillover as a limitation; do not use ad hoc erasures or water subtraction to hide it. For a 2020/2024 or rural comparison without a validated route, use explicitly synthetic polygons, not a fabricated station result.

Compare width scenarios using validity, component/hole counts, area, symmetric-difference area and named critical-point containment. Suggested numeric geometric equality tolerance: 1e-6 square feet on synthetic exact rectangles; projected/transform round trips use separately recorded tolerances. This tolerance is proposed, not a new golden baseline.

## Two allocation comparisons

Apply each method separately to 2020 block counts and 2024-geography ACS estimates. Preserve source year, unit, universe, original GEOID and geometry. Do not blend 2020 counts with ACS estimates or use 2020 block fractions to redistribute ACS until a reviewed crosswalk exists.

**A1: uniform area.** For each full source polygon G and corridor P, weight = area(G intersect P) / area(G), using a single projected CRS and full multipart geometry including its holes. Multiply additive counts by that weight; retain fractional results without rounding during computation. A zero-area/invalid/missing source polygon is an error or unallocatable record, never weight zero. Clamp only floating-point overshoot within an explicitly reported 1e-12 weight tolerance; larger out-of-range weights fail.

**A2: representative point.** Calculate a deterministic interior representative point from the full polygon using the recorded geometry library/version. Allocate the entire count when P covers that point, including the boundary; otherwise allocate zero. Sort geometry inputs deterministically and persist the selected point. Use the source's published INTPT fields only as a separately named future experiment, not an unnoticed replacement for the algorithm. This is a sensitivity comparison, not a claim of where residents live.

Use total geometric area for **both** numerator and denominator in A1. ALAND/AWATER attributes are source evidence in square meters, not a water mask and not necessarily identical to the transformed geometry's measured area. Do not divide a full-geometry intersection by ALAND. Retain published land/water values and report their shares separately. Land-only allocation is deferred until a versioned matching water geometry and denominator policy are accepted. Buffer widths in feet are unrelated to source ALAND units.

Missing estimate values remain null per variable. Record intersecting units, valid allocated subtotal, missing-unit count and geometric coverage of missing units. If any relevant covered unit is missing for a variable, the complete total is null/incomplete; an optional known subtotal is labeled as such. A missing MOE alone does not erase a valid estimate. An area fraction is not a sampling-confidence measure.

For two or more stations, union polygons **before** intersecting source units for combined unique totals. Keep per-station allocations separately. Never sum overlapping station totals. For household shares, use the same method and pairwise valid units for numerator/denominator; sum weighted counts first, then divide. Do not allocate percentages or medians, round household/person counts to integers before aggregation, or combine MOEs. Derived uncertainty remains `not_quantified`.

In rural units, uniform area may spread residents over large uninhabited parcels while representative points produce abrupt all-or-nothing jumps. Neither is ground truth; report their difference without interpreting it as an error bound. Household vehicle access cannot be located from a block-group total alone. All regional results inherit incomplete network/coverage status even when the arithmetic succeeds.

## Independent literal references for later implementation

These numbers are proposed hand calculations for review. Do not generate expected values from the implementation under test. Cartesian coordinates below are **international feet**, a local synthetic plane; production transformation is a separate adapter test.

| Case | Input | Required comparison |
|---|---|---|
| P01 corridor | Reached line (0,0) to (100,0), flat caps | 25-foot half-width gives 5,000 square feet; 50-foot half-width gives 10,000. Zero reached length gives empty/0 area. |
| P02 partial edge | Source line length 100; reached offsets 0–40 | Buffer only 40 feet: 25-foot half-width gives 2,000 square feet, not 5,000. |
| A01 partial unit | Full unit [0,100] x [0,100], population 100, housing 40; corridor covers x=0–30 | A1: 30 people, 12 housing units. A2 using interior point (50,50): 0 and 0. Full-unit denominator stays 10,000 square feet. |
| A02 overlap | Same unit/population 100; station A covers x=0–60, B x=40–100 | Per-station A1 gives 60 and 60; combined polygon covers the entire unit, so unique total = 100, not 120. |
| A03 household rate | BG1: N=10,D=100,weight=0.5; BG2: N=20,D=100,weight=1 | Weighted numerator 25, denominator 150; share 16.6666667%. An average of source shares (10%,20%) gives 15% and is incorrect. |
| A04 zero/missing | Denominator zero or missing; separate valid zero numerator with denominator 10 | Zero/missing denominator gives null rate with distinct reason. Numerator 0 / denominator 10 gives valid 0%. A covered missing count makes the complete total incomplete/null. |
| A05 water mismatch | Unit geometry 10,000 square feet, documented ALAND equivalent to 6,000 square feet, population100; intersection area2,500 | Total-area experiment gives 25 people. Dividing by ALAND to get 41.6667 is forbidden without a matching land mask. |
| A06 sparse rural | Full 1,000 x 1,000 foot square with population1,000; 100 x 100 corridor square away from center | A1 gives 10 people; A2 gives 0. No accuracy claim follows. |
| A07 hole/multipart | First component [0,100] x [0,100] with hole [40,60] x [40,60]; second component [200,250] x [0,100]; population146. P covers [0,50] x [0,100] | Full area = 10,000 - 400 + 5,000 = 14,600 square feet. Intersection = 5,000 - 200 = 4,800; A1 population = 48. Omitting the second component or filling the hole fails. |
| P03 barrier spillover | P01's 25-foot corridor; conceptual river occupies y=10–20 and is not a routing connection | Point (50,15) is geometrically covered. Record this as corridor spillover, not proof of a river crossing or pedestrian access. |

Add boundary-point inclusion, positive separated gaps, duplicate station polygons, two disconnected reached components, unknown count/MOE, zero-area and invalid polygons, swapped axes/CRS, and a barrier-side point case. For P01 use an independent rectangle construction, not the buffer function as its own expected output. A station location is never verified merely by passing a synthetic fixture.

## Outputs and ownership

Task 5.5 supplies inputs only. Task 5.6 should first implement the approved literal geometry and barrier-point references, obtain approval before adding or changing expectations, then implement pure TypeScript weighting/aggregation/union bookkeeping under `src/domain`. GIS projection, geometry libraries, imports and raw schemas remain adapters. Any polygon/topology dependency needs a separate license/bundle review. Python may supply clearly labeled experimental comparison geometries; browser-authoritative arithmetic cannot exist only in Python.

Keep separate reachability/polygon/allocation IDs and settings hashes, source release IDs, validity diagnostics, paired numerator/denominator coverage, uncertainty status and incomplete-network status. Export experimental layers separately from the current closed routing package schemas until an explicit contract extension is approved. Nothing in this document supplies score normalization, weights, public publishing approval or source completeness.

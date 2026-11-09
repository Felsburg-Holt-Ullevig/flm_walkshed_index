# Experimental routing references

Version: `routing-references-1`. Status: accepted experimental references and tolerances for prototype testing on November 3, 2026. Acceptance authorizes Tasks 4.2 and 4.3 within this scope; it does not approve authoritative methodology or complete regional analysis. Gate 3 is accepted for policy 0.3 and documented diagnostic limitations.

Companions: [reference data](fixtures/routing-references-v1.json), [accepted benchmark settings](config/routing-benchmarks.v1.toml), [accepted reference manifest](fixtures/routing-reference-acceptance-v1.json), [source fixtures](fixtures/routing-source-cases-v1.json), [graph contract](routing-graph-contract.md), [policy](pedestrian-policy.md), and [validation policy](../docs/validation.md).

## Scope and acceptance

These references test shortest base walking time and reachable portions of source segments, separately from polygons, scores, legal access, safety and wheelchair accessibility. Existing policy remains unchanged. Acceptance of these references would authorize the separately labeled origin experiment below; it would not silently change `verified_source_node` in the accepted policy configuration. Regional routing remains diagnostic while policy or coverage blockers exist.

Two independent fixture layers are required:

1. Metric graphs with declared lengths in international feet. These isolate traversal arithmetic from geodesic measurement and source preparation. They are intentionally not files accepted by the production graph validator. Their hand-set lengths need not match a map drawing.
2. Source fixtures through the actual PBF reader, extractor, classifier and graph builder. Their original node references and tags determine connectivity. Their EPSG:4326 coordinates determine geodesic lengths. Do not inject metric lengths into the production builder.

No expected result may be computed using the traversal, snapping or builder function being tested. Expected values below are arithmetic references. A future test can evaluate the documented arithmetic expressions using the standard library, independently of production functions. Baseline changes require owner review.

## Arithmetic and interval convention

Retain accepted speed `4500 / 1609.344` mph, equivalent to `1250 / 304.8` international feet per second. Thus **one foot costs exactly 0.24384 seconds**. A distance-equivalent budget Q feet means a time budget `Q * 0.24384` seconds; Q is a convenient description of a time limit, not a second routing mode. No rounded display speed enters calculations.

Each fixture segment has a unique ID, source-order endpoints and length L. Interval `[a,b]` means offsets in feet measured from its source-order start, inclusive. Reverse travel does not reverse this reporting axis. Union intervals per segment, not per arc. Parallel source segments remain separate; coincident geometry does not merge their identities. Total reached source length sums interval unions for each segment once, never both directed arcs.

For an allowed forward arc with reached start distance d, reach `[0,min(L,Q-d)]` when d <= Q. For an allowed reverse arc with reached end distance e, reach `[max(0,L-(Q-e)),L]` when e <= Q. Union contributions; both endpoints being reached does not imply the whole segment is reached. An interior origin contributes directly along each permitted direction even if neither endpoint is reached. Access cost is subtracted first. Report reached nodes at equality, but omit zero-length intervals from line exports. A zero-budget origin is a valid reached point, with zero reached line length.

## Hand-calculated fixture table

All unspecified edges are bidirectional; all unspecified access/coverage is supported and complete in the synthetic universe. `A=0,B=100` denotes shortest distance from the origin in feet; multiply by 0.24384 for seconds. The JSON companion is the mechanical transcription of this table, not an output from a routing engine.

| ID | Network and request | Exact expected result and arithmetic |
|---|---|---|
| F01 chain | AB=100, BC=100; origin A; Q=150 | A=0, B=100; AB [0,100], BC [0,50]; total 150 ft. C is beyond budget. |
| F02 branch | AB=100, BC=100, BD=100; A; Q=150 | A=0, B=100; AB [0,100], BC and BD [0,50]; total 200 ft. The budget limits each path, not summed network length. |
| F03 loop | AB=BC=CD=DA=100; A; Q=150 | A=0, B=D=100; AB and DA full; BC [0,50], CD [50,100]; total 300 ft. C has shortest distance 200 and is unreached. |
| F04 parallel | Two distinct AB segments of lengths 100 and 200; A; Q=120 | A=0, B=100; short full, long [0,120] union [180,200]; total 240 ft. Gap (120,180) remains. |
| F05 disconnected | AB=100 and CD=100; A; Q=200 | Only A=0,B=100; AB full; no CD interval; total 100 ft. |
| F06 forward direction | AB=100 forward only; origin B; Q=100 | B=0 only; no positive interval. Origin A instead reaches A=0,B=100 and full AB. |
| F07 reverse direction | AB=100 reverse only; A; Q=100 | A=0 only; no positive interval. Origin B instead reaches B=0,A=100 and full AB. |
| F08 physical barrier | AB=BC=100, B has barrier=wall; origin A; Q=200 | Policy excludes both incident candidates, zero arcs. Origin absent from routing graph: `no_network`, not a complete zero-length walk. Retain exclusion evidence. No approach-to-barrier segment is invented. |
| F09 grade separation | AB and CD cross geometrically; distinct endpoint IDs; bridge on CD; A; Q=200 | Only A=0,B=100, AB full, CD absent; total 100 ft. The crossing is not a node. |
| F10 coincident IDs | AB=100 and CD=100; B and C share XY but differ in ID; A; Q=200 | Same result as F09. Exact XY equality does not connect B to C. |
| F11 interior origin | AB=100; origin at offset 50, zero access cost; Q=20 | No endpoints reached; AB [30,70]; total 40 ft. |
| F12 two-ended partial | OA=OB=30, AB=100; O; Q=50 | O=0,A=B=30; OA and OB full; AB [0,20] union [80,100]; total 100 ft. Middle 60 ft remains unreached. |
| F13 exact boundary | AB=BC=100; A; Q=100 | A=0,B=100; AB full; no positive BC interval; total 100 ft. No numerical allowance grants a positive extension. |
| F14 zero budget | AB=100; A; Q=0 | A=0 only; no positive intervals; total 0 ft; synthetic complete, not failed. |
| F15 directional interior | AB=100 forward only; offset 50; Q=20 | No endpoints reached; AB [50,70]; total 20 ft. Reverse-only gives [30,50]. |
| F16 access cost | AB=100; projected offset 50; perpendicular access=10 ft; Q=20 | Access consumes 10 ft equivalent; AB [40,60]; network total 20 ft; connector length 10 ft separately. No endpoints reached. |
| F17 exhausted access | Same as F16; Q=10, then Q=9 | At 10: access point reached at 2.4384 s; zero positive network length. At 9: `budget_exhausted_before_network`; no reached network point/line. Both retain connector evidence. |

Each directional alternative in F06, F07 and F15 is a separate request. Include F01 with Q=99,100,101: reached lengths 99,100,101 ft; B appears only at Q>=100. Increase each fixture budget to check set inclusion, not just totals. Reordering edges and stations must not change ID-associated results. Two identical origins must not double combined unique source length.

## Accepted origin experiment for Task 4.3

Current accepted regional mode remains a named source node with no connector. Proposed additional mode: project onto an included source segment, maximum **100 feet**, charging the straight-line access distance at the same walking speed. This is an experimental geometric connector, not proof of a walkable station entrance or barrier crossing. Keep the connector separate from network intervals; show a warning and exact source candidate ID. Never snap onto unknown/excluded candidates. Never create a junction between nearby or crossing source segments.

For synthetic snap tests use a declared local Cartesian plane in international feet. Segment AB from (0,0) to (100,0); origin (50,10) projects to offset 50 and distance 10. Origins (50,100), (50,100.01) are respectively accepted at the limit and `off_network`. A closer excluded segment must not displace an allowed candidate. Equidistant distinct candidates return `ambiguous_origin` with sorted candidate IDs; require an explicit selection, rather than silently choosing a bridge or street. At a shared source-node endpoint, coalesce only projections to that same source ID; unrelated coincident IDs remain ambiguous. Invalid explicit selection fails. Do not use these synthetic planar coordinates as EPSG:4326 input.

For geographic snapping, minimize WGS84 geodesic distance to each source geodesic segment, return geodesic along-segment offset and projected longitude/latitude. A spatial index may narrow candidates but must not omit an eligible candidate within 100 feet. No fixed local projected-distance cutoff establishes that guarantee. Ties within 0.01 foot are ambiguous; this is a declared selection threshold, not floating-point tolerance. Record all competing identities. At an interior origin inject a virtual point on the selected segment only: allowed forward travel to its end and allowed reverse travel to its start, without a reverse arc or source-ID mutation. A later shortest path may reenter that segment by its original endpoints.

## Tolerances

| Comparison | Proposed tolerance | Reason |
|---|---|---|
| Source IDs, eligibility, directions, reached-node membership, interval count, statuses | exact | These are semantic results; numeric tolerances cannot hide wrong topology. |
| Metric fixture node costs | absolute 1e-9 s | Tiny networks with exactly specified costs; roundoff only. |
| Metric interval endpoints/union lengths | absolute 1e-8 ft | Roundoff only; interval topology remains exact. |
| Geographic length/cost reopen | existing graph relative 1e-12 or absolute 1e-9 ft/s, whichever larger | Preserve the current validator. |
| Independent equatorial geodesic check | absolute 1e-6 ft | Closed-form WGS84 equator reference versus implementation. |
| Geographic projected point / clipped interval endpoint | geodesic separation <=0.01 ft; along-offset <=0.01 ft | Allows iterative projection/interpolation convergence while exposing foot-scale errors. |

No rounding before comparisons. Tolerances are assertions, never extra travel budget. Production traversal must not inflate budget by them. Preserve exact endpoint costs where possible; a negative residual never creates an interval. Add explicitly separated inside/outside cases by 0.001 ft (0.00024384 s), much larger than arithmetic tolerance. Nonfinite/negative inputs fail rather than compare approximately. No polygon tolerance is defined here.

## Independent source fixtures for Task 4.2

Author tiny PBF fixtures with literal positive decimal source IDs and ordered way refs. Use footway defaults and explicit pedestrian direction tags; test barrier=wall, kerb, unknown gate, and access=private separately. Check expected adjacency directly from the literal source references before invoking the builder; checking output against another builder-derived object is insufficient.

For exact numerical end-to-end checks, use equatorial nodes with longitude increments of 0.001 degree, latitude 0. WGS84 semi-major axis is exactly 6,378,137 source meters. A short equatorial segment has length `(6378137 * pi / 180 * 0.001) / 0.3048` international feet. Compute this in the test with standard-library decimal/math, not PyProj or a production length helper. Construct F01, F05, F06/F07, F10 and parallel identities this way. Equatorial coordinates are artificial, not a Colorado fixture.

For branch/loop/bridge fixtures use separate geographic layouts with shared or disjoint source IDs as specified. Verify source topology exactly; test hand lengths in the metric layer rather than asserting that a distorted geographic drawing has those lengths. Include a crossing with no midpoint node, a shared junction with a midpoint node, and disjoint coincident midpoint IDs. Distinguish these three cases explicitly. Include IDs above JavaScript's exact integer range as strings, missing references, duplicate IDs, nonfinite coordinates, same-node and coincident-distinct-node zero-length candidates. Malformed data must fail; valid zero-length candidates are excluded with G_ZERO_LENGTH.

## Coverage and failure expectations

| Case | Required outcome |
|---|---|
| Valid origin outside declared usable domain | `out_of_coverage`; no complete walk or zero score |
| Empty graph, supported inputs | `no_network`; no route |
| No allowed projection within maximum | `off_network`; no connector silently extended |
| Unknown candidates or unsupported restrictions anywhere in current selected scenario | `incomplete`; preserve diagnostic intervals and blockers, never label complete |
| Reached frontier with remaining budget and unresolved continuation | `incomplete_coverage`; preserve frontier evidence |
| Exact-budget frontier endpoint | No extension beyond budget; boundary warning retained; this alone does not prove broader coverage |
| Missing/invalid inputs or hash/schema mismatch | `failed`; no result promoted |
| Conflicting nearest projections | `ambiguous_origin`; require candidate choice |

Return separate computation status, origin status, policy readiness and coverage readiness so one warning does not erase another. Diagnostic intervals are nullable when traversal did not execute; an unexecuted result is not an empty successful set.

The current node-in-bbox complete-way selection is not intersection-complete. A route staying inside the rectangle does not prove completeness. Later work must compare original and expanded extracts from identical source bytes and identical policy using the same verified core origins. Compare source identities, dispositions, node costs and interval unions inside the common core; classify every difference. An unchanged expanded comparison is supporting evidence, not proof that both selections omitted no crossing way. Keep coverage `not_established` until a separately reviewed extraction/coverage argument resolves this limitation. Synthetic completeness refers only to its explicitly closed universe.

## Mechanical implementation brief

Task 4.2 implements fixtures and structural tests only. Read accepted spec/data/config hashes and acceptance record first. Reject draft/unaccepted references at dispatch; do not change expectations to make tests pass. Use existing pytest fixtures and package APIs. Add small fixtures under `pipeline/fixtures/` and tests under `pipeline/tests/`; document their source IDs, tags and coordinate construction. Production traversal assertions remain a checklist for Task 4.3, not skipped tests advertised as passes.

Verify the metric JSON transcription against the table without importing a routing engine. Test production extraction/classification/build/validators for source fixtures. Exercise wrong shared-node wiring and forbidden-edge inclusion by temporary local mutations, demonstrate the intended assertion fails, remove mutations, then rerun relevant tests. Preserve the failure evidence locally. Do not leave a broken mutation or introduce a switch in production code. Run the shared Python suites; report new versus existing coverage. Changes to core tests alter upstream implementation identity: preserve existing regional artifacts as historical, and do not regenerate large regional runs merely to run fixture tests.

Task 4.3 adds pure experimental traversal/snapping separately from I/O. Use these expected results unchanged. Do not add NetworkX merely for convenience; a dependency requires a stated need and review under repository policy. No app code, browser package, polygon, Census calculation, station stress runner or public release belongs to Task 4.1/4.2.

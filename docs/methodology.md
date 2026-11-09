# Methodology

Status: no approved method. The application implements no FLM formulas or GIS calculations yet.

No reference implementation exists: the original ArcGIS model is not available. The method will be written in this document, approved by the designated methodology approver and CDOT reviewers, and verified against independent reference calculations (see [validation](validation.md)).

## Rules for implementation

- Implement only definitions recorded below as approved, with their method version.
- Propose alternatives with evidence in an issue labeled `decision`. Do not fill a missing definition with a plausible default.
- A plausible polygon or score is not validation.
- An approved change needs a new method version and updated benchmark evidence.

## Constraints that apply to any method

- Missing data is not zero, and no residents is not the same as no coverage. Report each distinctly.
- A failed or incomplete analysis is reported as failed. Never substitute a zero score or a circular buffer unless a separately labeled buffer mode is approved.
- Counts can be summed. Rates are recomputed from summed numerators and denominators. Medians and averages are not summed or area-averaged without an approved method.
- Walksheds of nearby stations can overlap. Per-station results may overlap; combined totals use unique coverage and never sum per-station totals.
- Units are explicit. The accepted offline experiment uses international feet, miles, mph and seconds; geographic coordinates retain their stated angular CRS. Historical source fields retain their declared units.
- Geographic identifiers are stored as text so leading zeros are preserved.
- Scores of 0 or 100 must not imply a universal condition when they only mark the extremes of one batch.

## Decisions required

| Decision | Required definition |
|---|---|
| Walkshed meaning | Whether the analytical area is the reachable street segments, a polygon derived from them, or another approved area model |
| Pedestrian network | Source, eligibility, restrictions, bridges and tunnels, crossings, unknown sidewalk information, coverage |
| Origin and access | Coordinate system, maximum snap distance, entry onto an edge, access cost, disconnected or out-of-coverage behavior |
| Walking costs | Speed, units, crossing delay model, edge direction, partial edge reachability, any slope assumption |
| Analytical area | Polygon construction, rivers and divided highways, holes, sparse networks, acceptable differences from reference outputs |
| Indicators | For each metric: geography, data year, numerator and denominator, weighting, missing and suppressed values, uncertainty |
| Overlap | Per-station versus combined unique totals and double-count prevention |
| Normalization | Reference for scaling. A fixed, versioned reference distribution or thresholds is the leading candidate for statewide comparability. Batch-relative scaling is allowed only as an explicitly labeled comparison mode, if approved. |
| Scores | Factor direction, weights, sub-index and total-index combination, ties, missing factors, zero denominators |
| Reproducibility | How saved results retain data versions, method versions, settings, and benchmark references when current data change |
| Acceptance | Independent references, tolerances, reviewers, and baseline change approval |

## Approved definitions

None yet. Record each as: identifier, definition, method version, approval date, approver.

## Offline experimental policy proposal

[Pedestrian policy 0.3](../pipeline/pedestrian-policy.md) is accepted by the developer for experimental use with imperial units. It separates access from sidewalk evidence and identifies unsupported cases and base costs. The separate experimental acceptance does not approve authoritative CDOT methodology. No authoritative definitions are added here.


## Experimental graph review boundary

Task 3.4 compares accepted pedestrian policy 0.2 against the pinned reference classification on identical source IDs and geodesic lengths. The [review procedure](../pipeline/graph-policy-review.md) defines that controlled comparison, components, source cases and diagnostic gap screening. The regional graph remains incomplete because unknown candidates and unsupported restrictions block analytical promotion. Conservative treatment of kerbs, level tags and unrelated-mode conditionals is explicit; no policy refinement or corrected benchmark is approved by the comparison. Gate 3 requires developer acceptance of the exact scenario and limitations. Synthetic reference design can be authorized separately from complete regional walking analysis. No authoritative definitions are added here.


## Accepted experimental kerb revision and travel scope

Pedestrian policy 0.3 permits exact kerb-tagged nodes for general pedestrian traversal, retaining explicit access, locked-node and other restriction rules. The developer accepted this refinement and the primary scope of a simple pedestrian walkshed. Wheelchair-specific routing and documentation are outside that scope; available raw accessibility tags are retained without new collection or dedicated calculations. Interface and exported-document accessibility requirements continue to apply. [Decision 0010](decisions/0010-general-pedestrian-walkshed-and-kerb-policy.md) records the choice. Version 0.2 evidence remains historical, and Gate 3 is not accepted by this revision. No authoritative CDOT methodology is established.

## Proposed Census and spatial experiments

Gate 5A is accepted for synthetic browser use. Task 5.4 proposes [Census variables](../pipeline/census-variable-spec.md) and [polygon/allocation comparisons](../pipeline/spatial-allocation-spec.md) with explicit universes, vintages, missingness, water/area denominators, overlap and uncertainty limits. The developer accepted these local experiments on November 5, 2026; authoritative methodology approval remains pending. No authoritative definition is approved by these proposals; complete network coverage remains unresolved; user-defined origin connection rules are recorded below.


## Accepted initial user-defined origin rules

[Decision 0011](decisions/0011-user-defined-origins-and-snapping.md) defines initial
product behavior: snap to the closest eligible pedestrian segment position or
node within 500 feet, including exactly 500 feet; compare straight-line distances;
start with the full walking budget; flag and reject points without an eligible
candidate. Successful snaps require no user-facing flag. Verified station
entrances are not a general prerequisite. Exactly equal distances prefer the northernmost candidate, measured at its
closest snap point; a remaining latitude tie uses stable source candidate ID
ordering. Numerical measurement details remain to be specified before implementation. This limited
product decision does not approve the remaining FLM methodology.

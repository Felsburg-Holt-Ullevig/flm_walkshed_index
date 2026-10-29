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
- Units are explicit (meters, seconds) and coordinate reference systems are stated.
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

# Methodology status

Status: unresolved analytical baseline. The repository foundation implements no FLM formulas or GIS calculations.

Before scoring is authoritative, obtain the existing spreadsheet/model, representative inputs and expected outputs, and approval from the designated methodology lead/CDOT reviewers. Record accepted rules and method versions here or in linked specifications.

| Decision | Required definition |
|---|---|
| Pedestrian network | Eligibility, restrictions, bridges/tunnels, crossings, unknown sidewalk information, coverage |
| Origin/access | Coordinate system, snapping threshold, access cost, disconnected/out-of-coverage behavior |
| Walking costs | Speed, time/distance units, crossing delay model, edge direction, partial edge reachability |
| Analytical area | Polygon derivation, barriers, holes, sparse-network behavior, and acceptable differences from reference outputs |
| Indicators | Geography/year, numerator/denominator, weighting, missing/suppressed values, uncertainty |
| Overlap | Per-station versus combined unique totals and double-count prevention |
| Scores | Factor direction, weights, normalization/reference distribution, ties, missing factors, zero denominators |
| Acceptance | Independent reference, tolerances, reviewers, and change/baseline approval |

Agents may implement approved definitions and propose alternatives with evidence. They must not silently supply a missing policy or treat a plausible polygon/score as validation. Approved changes need a method version and updated benchmark evidence. See [validation](validation.md).

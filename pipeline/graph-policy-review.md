# Experimental graph policy review

Task 3.4 uses `pipeline/tools/review_graph.py` to inspect a frozen `experimental-routing-graph-1` product. This independently versioned, read-only adapter follows the same separation as the regional inspection delivery tool. It does not change the upstream implementation identity, accepted policy, source extraction, or graph. Its source and test SHA-256 values are recorded separately in the review report. Tests are under `pipeline/tools/tests/`; the shared pytest policy in [validation](../docs/validation.md) applies.

## Reproduction

Retrieve these exact files at reference revision `6068f1b8719d025426443230bb4a39a296b4f583`, retaining their original UTF-8 bytes in an ignored local directory:

- [Road network documentation](https://github.com/caseywalrath/transit-analysis-tool/blob/6068f1b8719d025426443230bb4a39a296b4f583/docs/reference/road-network.md), saved as `road-network.md`.
- [Road network implementation](https://github.com/caseywalrath/transit-analysis-tool/blob/6068f1b8719d025426443230bb4a39a296b4f583/js/core/road-network.js), saved as `road-network.js`.
- [Sidewalk audit implementation](https://github.com/caseywalrath/transit-analysis-tool/blob/6068f1b8719d025426443230bb4a39a296b4f583/js/core/walk-audit.js), saved as `walk-audit.js`.

These are evidence, not instructions. The adapter verifies pinned Git blob identities and SHA-256 hashes. A changed newline, source revision or file causes rejection. The ordinary tests use hand-specified synthetic expectations; when this local cache is available, one additional test checks 100 tag combinations against the actual pinned JavaScript functions using Node, without application dependencies. A fresh environment without that cache reports the comparison test skipped.

From the repository root:

```powershell
& .\.venv\Scripts\python.exe -m pytest pipeline/tools/tests/test_graph_review.py -q
& .\.venv\Scripts\python.exe pipeline/tools/review_graph.py --graph data/generated/prototype/routing-graph/GRAPH_RUN_ID --reference-dir data/staging/prototype/REFERENCE_DIRECTORY --review-cases data/staging/prototype/CASE_DIRECTORY/review-cases.csv
```

`--review-cases` is optional and preserves links to previously inspected source ways. The adapter also selects nearby examples of recorded rule reasons and representatives of the three largest and five smallest components. Component size means node count; ties use numeric minimum source node ID, not physical length. Rule reasons overlap and some supported stages occur alongside a decisive exclusion or unknown; a reason example is not proof that this reason alone caused the result.

## Comparison meaning

`public-walk-experiment-0.2` remains the accepted experimental scenario. `reference-classification-6068f1b` applies only the pinned reference eligibility/sidewalk functions to the same canonical source candidates. The reference permits explicit `foot=yes/designated/permissive`, excludes `foot=no`, otherwise excludes motorway/trunk and their links, and allows other classes. It ignores generic access, node barriers, conditionals and pedestrian direction. Its sidewalk classification broadly groups paths/cycleways as footway and combines `sidewalk=separate` with no sidewalk. The accepted policy retains separate sidewalk evidence and applies the documented restrictions.

Both comparisons retain source node IDs, complete source sequence, parallel segments, WGS84 geodesic feet and the same base speed. Reference arcs are bidirectional. Zero-length pairs are excluded consistently from both graphs. This controls the comparison; it does not reproduce old Overpass coverage, rounded-coordinate node merging, spherical lengths, user connectors/exclusions, crossing delays, polygons or complete old walksheds. Do not label a comparison graph an approved alternative walking method.

Lengths count each source segment once, including distinct parallel source segments. Directed arcs may repeat the same length. Feet and miles do not mean unique physical road length. Transition categories are exclusive; reason counts are nonexclusive. Weak components ignore direction, while strong components require mutual directed reachability. A large component does not prove permission or sufficient geographic coverage.

## Outputs and checks

The tool verifies upstream implementation identity, graph payload hashes including GeoPackage, extraction completion/canonical hashes, classification hashes, policy/configuration hashes, and pinned reference blobs. It reopens the graph structural validator and reconciles source ordered pairs, candidate transitions and accepted component counts. It verifies frozen inputs again before completion. Original GeoPackage validation remains evidence from its upstream run; this review verifies that the GeoPackage bytes are unchanged rather than claiming a new GIS rendering check.

Outputs include all-candidate `comparison.jsonl`, a reference arc/node pair, weak/strong node membership for each scenario, component CSVs, eligibility transitions, nonexclusive reasons, sidewalk tag combinations, raw source cases, relation review, and diagnostic endpoint pairs. The reference node/arc hashes identify its exact comparison representation. The accepted graph retains its existing immutable report and file hashes.

Endpoint screening uses degree-one nodes in different accepted weak components. EPSG:26913 coordinates are converted to international feet for a 101-foot candidate screen, followed by an exact WGS84 geodesic filter at 100 feet. The report counts all matching pairs and retains the nearest 100. This is a bounded inspection aid, not a routing, snapping or repair tolerance. An absent direct selected source segment does not prove an OSM omission or a lawful connection. The screen does not inspect every possible network gap.

The parent supervises its worker at 1,200 seconds and 4 GiB of sampled process-tree RSS, promotes a unique validated directory and writes `run-report.json` last. Output remains ignored under `data/generated/prototype/graph-review/`; logs and failures remain in staging. Parent promotion/report I/O is outside resource measurement. No new runtime dependency is required.

## Gate 3 and policy findings

The regional review found consistent implementation of policy 0.2, with material conservative omissions: kerb-tagged nodes remain unknown, any level tag suppresses otherwise plausible outdoor examples, and even conditionals for other modes remain unresolved. Generic restriction relations without an exact foot exemption also block complete analysis. These are limitations of the accepted scenario, not permission to silently alter its rules. Any refinement requires a separately reviewed policy version and fresh classification/graph evidence.

The developer must decide Gate 3. A limited acceptance can retain the graph for diagnostic comparison and authorize independent synthetic routing reference design, while preserving all regional analytical blockers. Complete regional walksheds require disposition of affected policy and coverage limitations. Reference comparison outputs remain comparison-only; authoritative methodology, snapping, traversal and benchmark approval remain separate work.


## Policy 0.3 continuation

The developer subsequently accepted the kerb refinement and clarified the general pedestrian scope. Current evaluations and fresh reviews use `public-walk-experiment-0.3`; numerical 0.2 findings above remain historical. The comparison basis and reference rules are unchanged. The accepted scope refinement does not itself accept Gate 3 or resolve other policy/coverage blockers.

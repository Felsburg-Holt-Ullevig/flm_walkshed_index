# Prototype overview

The prototype turns a saved OpenStreetMap extract into a pedestrian network, follows that network from a test starting point, draws experimental bands around reached streets, and compares ways of assigning Census population to those bands.

## What works

1. Read local OSM and Census sources and record file fingerprints, versions and units.
2. Extract complete selected ways while preserving original node IDs and connectivity. A geometric crossing alone does not create a junction.
3. Classify candidate pedestrian segments as included, excluded or unresolved, then build directed connections with lengths in feet and costs in seconds.
4. Calculate reachable street portions within a time budget, including partial segments.
5. Produce a validated network package. The browser loads and traverses a small synthetic package in a worker.
6. Read separate 2020 blocks and 2024 block-group geometries with 2020–2024 ACS estimates. Local county joins and output reopening have been checked.
7. Compare 25-foot and 50-foot bands on each side of reached lines, area-weighted counts and representative-point counts, and merged overlap totals. Export GeoPackage and CSV evidence.

## What the results mean

Reached lines are the network calculation. Shaded bands are an experimental area around those lines; they can cross barriers or leave wedges at bends. Population figures allocate counts from Census areas; they do not locate residents or verify actual station access. The requested household/no-vehicle observations were missing and remain unavailable, not zero. The Census vintages remain separate.

The local demonstration passed developer inspection and a locked-environment repetition using frozen routing outputs. Exact GIS geometry, attributes and allocation results matched. This is not a complete fresh rebuild of every stage or evidence of statewide completeness. Gate 5B was accepted for this limited local experiment. Final FLM methodology, scores, production hosting and data distribution remain unapproved.

## User-defined origins

The intended app accepts clicks or latitude/longitude points representing stations, stops or other locations. The initial rule connects to the nearest walkable segment position or node within 500 feet, charges no connecting time, and flags/rejects points without an eligible candidate. Exactly equal distances prefer the northernmost snap point. Successful snaps need no warning. See [decision 0011](decisions/0011-user-defined-origins-and-snapping.md). This coordinate-origin workflow is specified but not implemented in the browser harness.

## Running and inspecting

Use [developer setup](../DEVELOPER.md), [pipeline commands](../pipeline/README.md), [synthetic browser review](../pipeline/browser-network-review.md), and [spatial experiment instructions](../pipeline/spatial-experiment-guide.md). Regional raw inputs and generated maps are not included in Git. A fresh clone can run synthetic tests and build a synthetic package; regional reproduction requires separately supplied approved sources and local configuration.

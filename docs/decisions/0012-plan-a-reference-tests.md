# 0012. Plan A offline reference tests

Status: Accepted for experimental testing
Date: 2026-11-11

## Decision

Use exactly 2.8 mph for Plan A reference calculations. All physical lengths and
offsets are international feet. Times are minutes or seconds; geographic
coordinates remain longitude/latitude in degrees. The 5-, 10-, and 15-minute
network budgets are exactly 1,232, 2,464, and 3,696 feet. The geometric origin
connector consumes no walking time, as specified by decision 0011.

The approved test origins, in longitude/latitude order, are:

| ID | Location | Longitude | Latitude |
|---|---|---:|---:|
| D01 | Denver Union Station area | -105.0004685 | 39.7529095 |
| G01 | Greeley Lincoln Park area | -104.6928167 | 40.4249000 |
| B01 | Broomfield Library area | -105.0687700 | 39.9175800 |
| C01 | Commerce City/72nd station area | -104.9430570 | 39.8263610 |
| F01 | Fraser Town Hall area | -105.8194500 | 39.9477600 |
| D02 | Sloan's Lake interior rejection control | -105.0490000 | 39.7480000 |

Prepare separate bounded Greeley, Broomfield, and Fraser samples from the accepted
local OSM source using pedestrian policy 0.3. Provide at least a 5,000-foot margin
around each origin and retain whole boundary segments. This expands the earlier
Denver-only preparation scope without establishing complete network coverage.

Use shortest WGS84 ellipsoid geodesics between source endpoints. A foot-scaled
WGS84 ellipsoid has semi-major axis 20,925,646.325459316 international feet and
reciprocal flattening 298.257223563. Include endpoints and interior closest
positions. Search globally with distance lower bounds; an optimization must not
omit a closer candidate. Seek distance and source-offset uncertainty no greater
than 0.000001 foot, with a finite work cap and explicit numerical failure when
the answer cannot be resolved.

The 500-foot limit is inclusive and receives no epsilon extension. Refine
uncertainty that overlaps the limit or candidate ordering; unresolved comparisons
fail numerically. Exact ties use greater snap-point latitude, then lexicographic
source candidate ID. Coalesce shared endpoints only by source node ID. Map the
selected source-oriented fraction to the copied segment length. Preserve source
connectivity and direction, including disconnected crossings and coincident IDs.

## Boundaries

These are offline comparison references for a separate reader or routing engine.
They do not select the final product engine or establish authoritative FLM
methodology. Geometric connectors do not test intervening barriers. No slope,
crossing, stair, or turn delay is added. Preserve historical 100-foot,
charged-connector fixtures and earlier generated products.

Implementation is limited to Plan A Step 3 and the three required sample
preparations. Census findings, publication, and subsequent steps remain outside
this authorization. Numerical feasibility and generated outputs must be checked;
approval of this method is not evidence that an implementation meets it.

# Synthetic source-network cases

Task 2.1 reviewed design cases for `source-network-1`. These are hand-specified source-preservation expectations, not approved analytical benchmarks or executable tests. Task 2.2 must encode them as tiny synthetic OSM fixtures and exercise the actual extraction path. Coordinates below use EPSG:4326; extraction bbox is [0,0,2,2], core [0.5,0.5,1.5,1.5], expanded [-1,-1,3,3]. Each case is independent. Unspecified tags are empty; listed ways have `highway=residential` unless stated otherwise. No relations unless listed.

| Case | Source records | Required result |
|---|---|---|
| Coincident distinct IDs | nodes 1=(1,1), 2=(1,1), 3=(0.5,1), 4=(1.5,1); ways 10=[3,1], 11=[2,4] | 4 nodes, 2 ways, 2 derived segments. IDs 1 and 2 remain distinct; no cross-way source junction. |
| Shared source junction | nodes 1=(1,1), 2=(0.5,1), 3=(1.5,1); ways 10=[2,1], 11=[1,3] | 3 nodes, 2 ways, 2 segments; both ways reference exactly node 1. No extra node generated. |
| Complete boundary way | nodes 1=(-1,1), 2=(1,1), 3=(3,1); way 10=[1,2,3] | All 3 nodes and ordered refs retained, including outside nodes 1 and 3; 2 segments, no clipping. |
| Crossing without interior node | nodes 1=(-1,1), 2=(3,1); way 10=[1,2] | Empty output despite geometric bbox crossing; report empty selection and coverage limitation. |
| Inclusive boundary | nodes 1=(0,0), 2=(-1,0); way 10=[1,2] | Way selected through corner node 1; outside node 2 retained. |
| Geometric crossing | nodes 1=(0.5,1), 2=(1.5,1), 3=(1,0.5), 4=(1,1.5); ways 10=[1,2] (`bridge=yes`, `layer=1`), 11=[3,4] | 4 nodes, 2 ways, 2 segments; no node at intersection and no connection inferred. Tags unchanged. |
| Tagged standalone node | node 1=(1,1) tagged `barrier=gate`, `foot=private`, `crossing=uncontrolled`; node 2=(1.5,1) untagged; no ways | Only node 1 retained; zero ways; no claim of a routing network. |
| Raw tag fidelity | nodes 1=(1,1) tagged `barrier=bollard`, 2=(1.5,1); way 10=[1,2] tagged `highway=mystery`, `foot:forward=no`, `foot:conditional=yes @ (sunrise-sunset)`, `sidewalk:left=separate`, `sidewalk:right=no`, `tunnel=no`, `custom:key=` (empty value) | All keys/values survive exactly; no eligibility or direction decision. Repeat with empty `highway` value: still selected. |
| Repeated/coincident refs | nodes 1=(1,1), 2=(1,1), 3=(1.5,1); way 10=[1,1,2,3,1] | Ordered 5 refs, 4 segments with sequences 0..3; segments 0 and 1 zero length, reported and retained; closing ref remains. |
| Relation scope | nodes 1=(1,1), 2=(1.5,1), 3=(4,4); ways 10=[1,2], 11=[3,3]; relation 20 members way10 role=from, way11 role=to, node3 role=via, relation21 role= (tags `type=restriction`); relation21 member way10 role=; relation22 member relation20 role= | Emit nodes 1/2, way10, relations20/21. Relation20 flags way10=true, way11=false, node3=false, relation21=true; relation21 way10=true. Do not emit relation22 or pull in way11/node3. Restriction remains uninterpreted. |

Additional negative cases must fail with IDs/reasons: selected way references absent node; required node has invalid location; way has one reference; duplicate node/way/relation identity; non-string tag values in canonical input validation. Unresolved relation members alone do not fail. Empty selection must be distinguishable from a normal nonempty result. An OSM ID such as `9007199254740993` must round-trip as exact text.

For every accepted case, verify canonical record counts, references/tags, deterministic hashes across two runs, and no synthetic junctions. Task 2.3 additionally checks derived segment IDs/endpoints/counts, coverage polygons, CRS, geometry and length tolerances after reopening GeoPackage. Expected counts here are independently derived from the listed records; do not regenerate them from extractor output to clear failures.

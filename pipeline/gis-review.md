# Source-network GIS review

Status: review procedure for `source-network-1`. A completed synthetic check does not establish real regional coverage. The [readiness review](readiness-review.md) records the current gate disposition. This procedure supports source preservation review before pedestrian eligibility and routing are implemented.

ArcGIS Pro is one viewer option. The proposed [Google Earth inspection specification](google-earth-inspection-spec.md) and [plain-language guide](google-earth-user-guide.md) describe an alternative local-file workflow. That adapter and its actual viewer trial are pending. Apply the same identity, case, reconciliation, and finding requirements with the viewer recorded; an ArcGIS Pro installation is not a Gate 2 requirement.

## Required input and record

Use a completed export directory containing `source-network.gpkg` and its matching `run-report.json`, plus the report's linked canonical extraction, inventory, configuration, and code manifest. Verify the GeoPackage SHA-256 against `output.sha256` before opening it. Keep raw inputs and accepted output files unchanged. Save the ArcGIS Pro project, screenshots, selections, and review table under ignored `data/generated/` or the local planning packet.

Record the reviewer, date, GIS product/version, export and extraction run IDs, source/config/code/inventory hashes, GeoPackage hash, and spatial reference. For each observation record: case ID, place/search extent, longitude/latitude, layer, source way/node IDs, segment IDs/sequences, raw tags, expected source representation, observed representation, evidence path, status, classification, and disposition. Use `not_run`, `pass`, `fail`, or `unresolved`. A location with no matching source object is `unresolved` until the pinned source is checked; absence from the map alone does not prove a source omission.

## ArcGIS Pro setup

1. Create a local map with display CRS EPSG:26913. Add the GeoPackage's `source_nodes`, `source_ways`, `source_segments`, and `coverage` feature layers and the `source_relations` standalone table. Their stored spatial CRS must remain EPSG:4326. Record the transformation selected by the GIS if a basemap requires one. Do not run Define Projection to change a stored CRS label.
2. Use hollow outlines for coverage. Make separate copies filtered by `coverage_kind = 'core'`, `'extract'`, and `'expanded_comparison'`. Label the last one **planned comparison extent; no expanded extraction demonstrated**. Neither polygon fill nor complete-way overhang proves route completeness.
3. Draw segments as thin lines with source-order arrows; label `segment_id` at close zoom. Draw nodes above lines and label `osm_id`. Keep source ways available for selection and full geometry comparison, with their visibility off when duplicated linework obscures segments. Use contrasting symbols and text labels for each inspected ID.
4. Add a segment copy filtered by `zero_length = 1`. Zero-length lines may be invisible; inspect their endpoint nodes and attribute rows. Select nodes with `inside_extract = 0` separately. Source IDs and references are text; select with quoted values, for example `osm_id = '2'` or `way_id = '10'`. Never use the GeoPackage's internal feature ID as source identity.
5. Inspect `tags_json`, `node_refs_json`, and `members_json` in the attribute tables. They are JSON text. Search raw tags to locate candidates, then read the complete JSON to confirm key/value meaning. A text search is a candidate finder, not an eligibility rule.
6. Use a basemap only as supplemental context and record its date/source when known. Compare the pinned PBF/canonical records for source claims. A live OSM map can differ from the pinned snapshot and cannot establish an extraction defect by itself.

## Required inspection cases

| Case | Layers and source evidence | Acceptance evidence |
|---|---|---|
| Representative street | Ways, segments, nodes; ordered references and all tags | Each consecutive pair produces exactly one segment with the original order. Labels and coordinate sequences agree with canonical records. |
| Separated path and sidewalk evidence | Distinct source ways; `highway`, `footway`, `sidewalk:*`, `access`, `foot` | Separate paths retain their own IDs and references. Sidewalk tags remain evidence; no invented sidewalk geometry or permission. |
| Shared-node crossing | At least two ways referencing the same node ID | Both retain the shared reference. Node crossing/barrier/access tags survive. Source sharing alone does not settle pedestrian permission. |
| Same XY, different IDs | Coincident nodes on different ways, inspected by ID and endpoint references | IDs remain distinct; no added segment or endpoint substitution. Check source-reference components if another route could connect the ways elsewhere. |
| Geometric crossing | Intersecting line interiors without a shared source node | No synthetic node, split, snap, or inferred connector. A geometric intersection is insufficient evidence of a junction. |
| Bridge | Way/node references plus `bridge`, `layer`, `level` | Tags and source identity survive. Confirm actual shared references and approach ramps; do not disconnect solely from a layer value. |
| Tunnel/underpass | Way/node references plus `tunnel`, `layer`, `level` | Same preservation check; no connection inferred where lines overlap in map view. If no tagged candidate exists, record missing case coverage. |
| Barrier or restricted access | Node and way tags, including conditional restrictions | Evidence survives on its original object. No permission, barrier traversal, or conditional interpretation is claimed in this phase. |
| All four extract edges and corners | Coverage, complete source ways, `inside_extract` node flag | Outside vertices of selected ways remain. Trace a boundary way back to the pinned source. Also check a crossing way with no inside node: documented selection can omit it. |
| Repeated/zero/duplicate geometry | Diagnostic IDs, segments, nodes and canonical refs | Counts and sequence agree; original features remain present. Coincidence and duplicates are not repaired automatically. |
| Relations | Relation member IDs/roles/resolution flags | Unresolved members remain visible. No restriction semantics or recursive completeness inferred. |

For each case, inspect more than one example when available. Include both ordinary and apparent defective examples; record the selected IDs so another reviewer can repeat the check. A screenshot supports a finding but does not replace the reference/ID checks.

## Count and identity reconciliation

Record actual table counts and compare them to both reports. Required equalities are:

- GeoPackage node, way, and relation counts equal extraction emitted-node, selected-way, and emitted-relation counts.
- Segment count equals the sum of `len(node_refs) - 1` over selected ways. Reference total is not a unique-node count.
- Every segment ID names its way and zero-based sequence. Its endpoints equal that exact consecutive pair; its geometry endpoints equal those node coordinates.
- Spatial CRS is EPSG:4326. Geodesic lengths are WGS84 ellipsoidal meters; projected lengths are EPSG:26913 diagnostics. Displaying the map in a projected CRS does not change those fields.
- Record repeated references, zero-length segments, duplicate groups/extra features, degenerate geometries, and unresolved relation members. A zero report count is different from an unperformed check.

## Finding classification and disposition

| Classification | Evidence needed | Disposition |
|---|---|---|
| Source omission or inconsistency | Pinned PBF objects/refs/tags and independent contextual evidence | Record IDs and source hash. Consider an explicitly versioned source correction only after review; no final-file edit. |
| Extraction/export defect | Pinned input satisfies the documented inclusion rule, but canonical records or GeoPackage disagree | Preserve a minimal failing fixture. Correct source code, run checks, regenerate inventory/extraction/export under the new code identity, and repeat affected review. |
| Selection limitation | Object crosses the bbox but has no inside reference, or lies outside selected source scope | Record as known incomplete coverage. A changed selection algorithm requires a reviewed contract/configuration revision. |
| Future eligibility decision | Source object is preserved but access, sidewalk, barrier, direction, or relation meaning is undecided | Carry the exact object/tags to the provisional rule specification. Do not classify missing permission as a broken extractor. |
| Display artifact | Different draw order, scale, CRS transformation, or hidden zero-length feature explains appearance | Record the setting and confirm the unchanged IDs/geometry. |
| Unresolved | Insufficient pinned-source evidence or required case unavailable | Keep the case open with the missing evidence named. |

Any proposed correction must identify its source, scope, rationale, original objects, changed objects, and version. Implement accepted corrections in configuration or source code and regenerate. Do not edit the final GeoPackage into a manually repaired network.

## Gate evidence

Gate review requires a real regional export, reconciled counts/hashes, named source-object findings, map inspection evidence, known-defect dispositions, and developer acceptance. Mark manual ArcGIS checks `not_run` until performed. A Python geometry/identity inspection is recorded separately from ArcGIS Pro operation. Synthetic fixtures establish preservation behavior only. Routing, pedestrian policy, expanded-boundary sufficiency, source publication, and methodology acceptance require subsequent work.

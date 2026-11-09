# Google Earth source-network inspection specification

Date: November 3, 2026. Specification version: `earth-inspection-1`.
Status: Task 2.4b implements the offline exporter, synthetic topology and diagnostic package profiles, automated KML/evidence validation, and supervised promotion. Automated package-structure and source-evidence checks are implemented. The developer accepted the synthetic Google Earth browser trial and revised description usability under Task 2.4c. The readiness review records the user observations and environment-evidence limitations. Regional Gate 2 remains open.

## Purpose and boundaries

Provide a local Google Earth inspection workflow for the regional source network described by [source-network-1](source-network-contract.md). It supports the visual/source-object review in [GIS review](gis-review.md). The [user guide](google-earth-user-guide.md) describes the human workflow. Requirements supported: R-03, R-06, and R-07; none becomes met solely through this deliverable.

Canonical JSONL remains the source subset authority. The GeoPackage remains the GIS inspection product. KMZ is an additional derived view. Preserve source coordinates, IDs, ordered references, and raw tags. Pedestrian permissions, graph repair, routing, population, and FLM scores are outside this specification. No changes to the transit-analysis-tool repository or FLM browser application are required.

Google Earth supplies visual context. It cannot establish source-reference connectivity by line appearance. Imagery may have a different date or registration from the pinned source. Record disagreement as an observation pending source investigation.

## Entry conditions and ownership

The implementer prepares and validates files, runs automated checks, and supplies exact paths and completion evidence. The reviewer opens files, records observations, and judges usability. The developer accepts source limitations and Gate 2. The reviewer does not edit pipeline configuration, repair code, or hand-edit final geometries.

Synthetic development may proceed using generated fixtures with their own pinned identities and fixture inventories. Real execution requires accepted local OSM identity/provenance limitations, its pinned hash, a fresh unedited inventory under frozen code/configuration, and completed extraction/export. Resolve the location-cache, resource-control, and canonical-ID findings in [readiness review](readiness-review.md), or record an explicitly accepted disposition, before regional execution. Preserve all historical evidence; regenerate when current code identity changes.

## Inputs and command boundary

The `earth-export` command accepts the matching configuration, canonical extraction directory, and successful GeoPackage export directory. It validates their existing completion reports, source/config/code identities, canonical input hashes, GeoPackage hash, and count linkage before writing. An explicit empty source selection may produce an `empty` inspection package, with visible wording that no regional network was selected. Invalid or incomplete input fails without a completed package.

The adapter is implemented in `pipeline/src/flm_pipeline/kml_export.py`, separate from source extraction and authoritative analytical modules. It uses standard-library XML/ZIP/JSON/CSV support and existing GeoPackage readers; no new runtime dependency was added. From the repository root, call:

```powershell
& .\.venv\Scripts\python.exe -m flm_pipeline earth-export --config pipeline/config/CONFIG.toml --extraction data/generated/prototype/EXTRACTION_RUN_ID --gpkg-export data/generated/prototype/EXPORT_RUN_ID --dataset-kind synthetic --review-profile topology
```

Use `--review-profile diagnostic` for a separately identified synthetic diagnostic packet. Regional export uses `--dataset-kind regional --review-profile regional`; it still requires pinned-source prerequisites, completed human viewer trial, accepted technical findings, and real review-case population. The CLI enforces technical input hashes and package limits, not human acceptance decisions.

Recheck source/config/code/input hashes before completion. Execute export and validation under configured time and sampled process-tree RSS limits; report measurement interval and sampled peak. Use unique ignored staging/generated run directories, refuse replacement, validate before promotion, and write the final completion report last. A KMZ without its matching completed report is not accepted output. On failure retain diagnostics and prevent partial output from appearing complete.

## Proposed output directory

Names below are specified future artifacts, not currently available files:

```text
data/generated/prototype/<inspection-run-id>/
  inspection-manifest.json
  source-network-inspection.kmz
  source-evidence.jsonl
  review-cases.csv
  review-observations-template.csv
  README.md
  run-report.json
```

The manifest uses `inspection_version: earth-inspection-1`, a unique package/run ID, `synthetic` or `regional` dataset kind, `topology`, `diagnostic`, or `regional` review profile, and explicit `complete` or `empty` scope. Include region ID, extraction/export run IDs and report hashes, source SHA-256 and provenance limitations, source inventory/report hashes, config hash, code identity, environment versions, contract/selection IDs, bounds/actual extent, CRS, length method, counts, file byte lengths and SHA-256, partition membership, automated checks, manual checks (`not_run` until performed), and known limitations. Use repository-relative paths in shared metadata; exclude credentials and unrelated machine paths.

Hash every payload file in the manifest except the manifest itself and final report. The final report hashes the manifest, records input identities, durations/resource measurements, counts, diagnostics and every automated check result. Record manual checks separately as `not_run` until performed. An export can pass automated conversion checks while human viewer acceptance remains pending.

`source-evidence.jsonl` preserves full node/way/relation objects and derived segment evidence. Every compact JSON line has `entity_type`; node/way/relation records retain exact string `osm_id`, raw tags, coordinates or ordered refs/members, resolved flags, and empty values. Segment records retain `segment_id`, `way_id`, consecutive ordered endpoint IDs, sequence, raw `tags_json`, lengths, zero-length state, and longitude/latitude coordinates. No contributor metadata is added. Automated validation reconciles all node/way/segment IDs, tags, ordered references, lengths, and coordinates against the evidence and requires relations to reconcile by exact entity count. This is a local inspection companion, not a new browser routing format.

The package README identifies the dataset kind, package ID, repository-relative package folder, completion status, file hashes/counts, intended viewer, which folders start visible, review sequence, and missing cases. Include source attribution and known license/provenance limitations without implying distribution clearance. Large files and reviewer evidence remain ignored local artifacts.

## KML/KMZ encoding

- Use KML 2.2 XML, UTF-8, and a KMZ ZIP containing `doc.kml` and three generated local PNG symbols. Do not include network links, remote icons, scripts, external styles, or automatic refresh behavior.
- Coordinates are longitude, latitude in WGS84 decimal degrees. Preserve each original pair to within 1e-9 degrees when parsed back. Do not round for display and then reuse those rounded values as geometry.
- Use `clampToGround` with ordinary line rendering; disable terrain tessellation initially so it does not introduce additional rendered subdivisions. No invented elevations, extrusion, bridge heights, tunnel depths, snapping, simplification, clipping, or node merging. Explain that ground-clamped display cannot show actual vertical separation.
- KML XML element IDs must be legal identifiers, for example `node-2` and `way-10-segment-0`. Store exact source identities independently as text in ExtendedData. Never use JavaScript-number conversion or the XML ID as a replacement for source identity.
- Each segment retains its source pair in order. Source order is not permitted walking direction. Preserve geodesic/projected length fields as labeled source values; Google Earth ruler results do not replace them.
- Escape XML and description HTML correctly. Render raw tag values as text, including characters such as `<`, `&`, quotes, newlines, and `]]>`. A missing tag and an empty tag value remain distinguishable. Avoid clickable markup derived from arbitrary source values.
- Use simple names/descriptions that remain useful if a viewer omits custom balloon styling. Show source fields in ExtendedData and a plain labeled description; keep complete evidence in the companion file.
- Closed boundaries use hollow outlines. Label the expanded polygon as planned comparison extent, not an executed expanded extraction. Keep complete-way overhang visible.

Google documents KML [custom data](https://developers.google.com/kml/documentation/extendeddata) and [geometry/altitude elements](https://developers.google.com/kml/documentation/kmlreference). The above restrictions are this project's inspection design.

## Folder and feature design

| Folder | Initial visibility | Contents |
|---|---|---|
| Package information | on | A package metadata placemark with dataset kind, package ID, source identity, limits and attribution |
| Review cases | on | Named case placemarks/viewpoints with instructions and linked source IDs |
| Coverage | on | Separate core/extract outlines; planned expanded outline off |
| Source segments | on | One line per ordered reference pair; names include exact segment ID |
| Source nodes | off for regional; on for trial | One point per source node, including coincident IDs and tagged standalone nodes |
| Source ways | off | Complete original coordinate sequences; names include way ID |
| Diagnostics | off | Case markers for zero-length/degenerate features, repeated references, duplicates, unresolved relations, and boundary overhang |

Descriptions include package ID, entity type/ID, coordinates or ordered endpoint IDs, segment sequence, raw tags, lengths/units when applicable, and node incident-segment IDs for the reviewed nodes. A way includes its full ordered references; a node includes its original tags and core/extract flags. An oversized description may point to a keyed full record in the companion evidence file, but it must explicitly label the abbreviated display and retain the identifying fields. Record actual truncation counts and IDs.

Coincident nodes remain separate placemarks named by ID, with identical geometry. Do not offset source points to make them selectable. Zero-length lines may be invisible: retain the original segment and add a distinct diamond diagnostic point explicitly labeled as a display marker with segment/endpoint IDs. Diagnostic markers and case pins are counted separately from source features. The first implementation emits at most 500 diagnostic markers and reports missing spatial context and cap omissions. Relations have no invented geometry; retain them in evidence and summarize unresolved member cases at relevant existing nodes/ways where possible, labeling those pins as review aids.

Use text labels and different symbol forms as well as colors. Define fixed, documented colors and account for KML's color encoding. Test actual rendering before relying on the legend. Support individual layer toggles so linework does not hide nodes or duplicate ways.

## Partitioning and performance

Begin with the tiny synthetic package. Set explicit feature/vertex/byte limits in the implementation configuration before a regional run; document their initial trial rationale. Do not infer local-file capacity from Google's cloud-project limits. Record observed load time, browser/product/version, machine, bytes and feature/vertex counts; avoid capacity extrapolation.

If the regional file exceeds tested limits, produce deterministic spatial partitions or case packages. Preserve whole source geometries and IDs, list exact membership, flag duplicated cross-partition features, and reconcile unique entity totals. Record every omitted object and reason. A case-only sample has `partial` scope and cannot be described as the full regional network. The manifest must let a reviewer locate every selected source feature; never silently drop nodes or long ways to make loading succeed. A selected file set that cannot support the required review triggers a smaller documented trial or another viewer.

## Automated acceptance

The implementation reopens KMZ KML using `xml.etree.ElementTree`, checks namespace/structure, unique XML IDs, exact source string IDs, ordered node/segment references, full tag evidence, lengths, parsed coordinate sequences, folder counts, local-only resources, ZIP members/CRCs, and payload hashes/limits. It reconciles node/way/segment evidence to KML and source evidence counts to GeoPackage counts. Repeat-export tests compare canonical evidence and source-feature KML semantics, excluding package-specific IDs/timestamps. Regional over-limit packages currently fail without truncation; deterministic partition generation remains a regional-stage dependency and must be completed before a regional package that exceeds these trial caps can be reviewed.

Meaningful tests include: the existing 12-node/five-way/seven-segment topology fixture; ID `9007199254740993`; Unicode/escaped/empty tags; repeated refs; zero-length and duplicate geometries; outside vertices; incomplete relations; empty input; corrupt/stale/mismatched inputs; timeout/resource failure; failed promotion; deterministic semantic repeat export. No basemap or Google service is required for automated tests. Report pass/fail/not-run using the repository validation policy.

## Actual viewer trial and acceptance

The existing topology fixture has five undirected source-reference components: `{1,2,3,8,9}`, `{4,5}`, `{6,7}`, `{10,11}`, `{12}`. Nodes 2 and 4 share coordinates `(1,1)` but have distinct IDs. Node 2 is a real shared street/branch reference. A path and tunnel line cross the street without shared references. Node 8 is outside extract bounds. Synthetic locations near zero longitude/latitude have no expected Colorado imagery; navigate through the case list, not a Denver search.

In addition to that fixture, export a tiny diagnostic fixture for repeated refs, zero-length segments, duplicates, and unresolved relations. Clearly separate fixture/package identities. The trial must actually demonstrate folder loading/toggling, readable descriptions, access to both coincident IDs, preserved source pairs/tags, zero-length diagnostic selection, and package identity. Record screenshot/table evidence and product/browser/version. Do not mark this passed from a successful XML parse. If the interface blocks required inspection, record the failed case and choose a revised package or another viewer; no automatic gate acceptance.

Google Earth web's Local KML editor is the first candidate. Existing desktop Google Earth may be trialed separately if available. A successful trial applies only to the recorded product/version and measured package. The [user guide](google-earth-user-guide.md) describes local-file operation and recording results. Opening a Drive project or uploading data is a different workflow and is not required or authorized by this specification.

## Regional review and completion

After a successful viewer trial and regional prerequisites, generate the real package. Populate cases from actual pinned-source IDs for ordinary streets, separated paths, shared crossings, geometric overlaps, bridges, tunnels, barriers, every extract edge/corner, and reported diagnostics. Use the nominated Denver areas in the local review packet as search areas, not asserted source facts. Missing case coverage stays visible.

The reviewer records findings using the template in the user guide. The implementer investigates against canonical and pinned source objects and classifies findings using the shared GIS procedure. Keep display limitations, source omissions, selection limitations, extraction defects, and future eligibility decisions distinct. Version any accepted repairs in source/configuration and regenerate affected evidence. Gate 2 requires regional map review, count reconciliation, finding dispositions, and explicit developer acceptance. Google Earth trial acceptance alone does not open Phase 3.

## Readability revision

Feature balloons show IDs, endpoints, key source tags and labeled lengths first. A secondary Technical details section retains package identity, coordinates, ordered references and diagnostic length information; all raw tags remain available below it and in ExtendedData/evidence. Inline BalloonStyle uses the description explicitly to avoid an automatic raw-field table becoming the primary display. Simple headings/tables are used without requiring expandable HTML controls. Source tag labels explain fields without interpreting walking eligibility. Actual Google Earth rendering of the revised balloons requires user confirmation.

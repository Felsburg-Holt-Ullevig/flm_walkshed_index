# Review the source network in Google Earth

Date: November 3, 2026. Status: exporter and automated synthetic packages are available. The user has opened the synthetic packets in Google Earth browser and reports passing topology and diagnostic checks. The developer approved the revised description readability, completing Task 2.4c synthetic viewer usability.

## What you are reviewing

You will check whether the exported streets, paths, nodes, and crossings preserve the source evidence and whether anything looks wrong against the available map context. A node is a source point with an ID. A segment joins two consecutive source points. Two lines crossing on the screen do not necessarily connect in the source network.

You do not need to fix code, edit the source file, or decide walking permissions during this review. Report what you see. The implementer investigates the cause. The [technical specification](google-earth-inspection-spec.md) defines how the files will be generated and checked.

## Step 1: Choose your viewer

The first trial is intended to use [Google Earth in a browser](https://earth.google.com/) and its **Local KML editor**. An existing desktop installation is an alternative to test; installation is not a prerequisite for the browser trial. Record which product and browser/version you actually use.

Google's current instructions offer the Local KML editor from the home screen or **File > Open local KML file**. This mode opens a device file rather than creating a Drive project. Google documents the distinction in its [local-file guidance](https://mapsplatform.google.com/resources/blog/can-i-use-google-earth-on-the-web-without-storing-my-data-in-the-cloud/) and [import guide](https://developers.google.com/maps/documentation/earth/import-data). Interface labels may change; the trial will record the actual labels used.

Local-file handling does not make the whole application offline. Google Earth still requests map/imagery content over the network. Use the local-file path for this experiment. If the interface instead asks you to upload to Drive, create a cloud project, or publish, stop and report the prompt. Those actions are not needed for this review.

## Step 2: Obtain the inspection packet

Wait for the implementer to provide a completed packet with:

1. An exact folder path and a short README stating **synthetic** or **regional**, the package ID, and the completion status.
2. One or more `.kmz` files. A KMZ is a compressed map overlay; leave it compressed when opening it in Google Earth.
3. A review-case list, a blank observation table, and full source evidence for objects that are difficult to inspect in the map.
4. A validation report with feature counts and file checksums. A checksum identifies the exact file; the implementer checks it for you. It is not proof of real-world accuracy.

Do not try to open the `.osm.pbf`, `.gpkg`, TOML configuration, or JSONL source evidence as a Google Earth map. The KMZ is the file prepared for this viewer. Use only the packet named by the implementer; older successful files may refer to older code or inputs.

For the synthetic trial, you need no real-source acceptance. Before a regional packet can be produced, the developer must accept the local OSM file's identity and documented provenance limitations. Provide its known download origin/date and whether it has been edited; unknown facts can remain unknown. The implementer computes the hash, presents it for acceptance, pins the accepted value, fixes the open technical findings, and runs the pipeline. A source-acceptance statement should name the exact hash and permit local inventory/extraction/export. It does not approve methodology or publication.

## Step 3: Open the synthetic trial

1. Keep the original packet unchanged. Create a separate local folder for your notes and screenshots. Record the package ID at the top of your notes.
2. Open Google Earth and enter the Local KML editor. Choose the option to open a KML/KMZ file from your device, and select the supplied synthetic `.kmz` file.
3. Confirm that the interface indicates local KML operation. If you cannot confirm it, report that before proceeding.
4. Open the imported document/folder list. Find **Review cases**, **Coverage**, **Source segments**, **Source nodes**, **Source ways**, and **Diagnostics**. The implementer may split packages; follow its README for the files needed together.
5. Select a review case and use its zoom/navigation action. If selecting it only opens a description, use the viewer's available zoom-to-feature action. Record any case you cannot reach.
6. Toggle a folder off and on. Confirm that its contents disappear and reappear. Turn **Source ways** off while inspecting segments, since they draw the same linework at a different grouping.
7. Click a source segment. Its description should identify the package, segment, source way, endpoint IDs, sequence, tags, and lengths with units. A sequence is the pair's position in its original way; it is not a walking-direction rule.

Synthetic coordinates are near longitude/latitude zero. They will not appear in Denver or match local streets in the imagery. This trial checks the file and interface.

## Step 4: Complete the trial checklist

| Trial | What to do | What to report |
|---|---|---|
| Basic selection | Open the description for `way/10/segment/0`. | It should show endpoint IDs `1` and `2`. Can you read and copy the IDs? |
| Coincident nodes | Find node `2` and node `4` through the folder list. Toggle each individually if clicking selects only one. | Both exist at the same coordinates. Can you inspect each ID and its incident-segment evidence separately? |
| Shared junction | Find node `2` and segment `way/14/segment/0`. | The branch uses node `2`; the segment should show endpoints `2` and `9`. |
| Bridge and tunnel | Inspect ways `11` and `13`. | Are `bridge=yes` and `tunnel=yes` readable on their respective objects? Both are drawn at ground level for inspection. |
| Boundary overhang | Inspect node `8` and way `10`. | The node should remain beyond the extract outline. The way must continue to that node. |
| Invisible/overlapping features | Open the separately identified diagnostic trial package and its case list. | Can you find a zero-length segment through its diagnostic point, and inspect duplicate features individually? Record its separate package ID. |
| Legibility | Toggle nodes, segments, coverage, and diagnostic folders. | Are labels/descriptions useful? Are any features hidden, impossible to select, or slow to load? |

Use `pass`, `fail`, `unresolved`, or `not_run` for each row. Report usability problems even if automated checks passed. You can say: "The synthetic viewer is usable for regional inspection, except for [cases]." That is a viewer decision, not Gate 2 acceptance.

### What the diagnostic check means

This check uses the separate diagnostic KMZ. A zero-length segment has both endpoints at the same point, so it cannot appear as a visible line. In the Diagnostics folder, select the zero_length_segment marker for `way/13/segment/0`. Confirm it identifies endpoints `1` and `1`, then find the retained segment by its ID under Source segments.

Overlapping duplicates are separate records drawn on the same coordinates. Under Source segments, select `way/10/segment/1` and `way/13/segment/1` individually. Both should identify endpoints `1` and `2`. Turn one off and leave the other on; the line should remain visible. Report whether both IDs can be inspected separately. These checks establish that difficult-to-see source records remain accessible.

## Step 5: Review the real regional packet when supplied

1. Close or hide the synthetic package to avoid confusing its objects with regional data. Open the regional packet through the same local-file workflow.
2. Confirm its package ID, regional label, source hash, and review-case list match the README. A file that loads without warnings can still be the wrong file.
3. Use the named review cases to visit ordinary streets, separate paths, crossings, bridges, underpasses, barriers, and boundary locations. The implementer will supply actual source IDs and views. Missing cases are explicitly listed.
4. At each case, inspect the linework and node/segment descriptions. Compare imagery when useful. Record the imagery date if shown; otherwise write "unknown." Apparent displacement or disagreement is a finding to investigate, not permission to move the geometry.
5. At a crossing, read the endpoint/node IDs. Write down whether source IDs are shared or different. If you cannot determine this, mark it unresolved. Map appearance alone is insufficient.
6. At each extract edge and corner, inspect the assigned case. Ways may extend outside the outline because complete source ways are retained. The outline does not prove that all paths or routes are covered.
7. Save one overview screenshot and a close view for each suspicious case, showing object IDs/descriptions where possible. Use filenames such as `DEN-03-bridge-detail.png` and record the package ID in the observation table.
8. Record all required cases, including ones not inspected. You do not need to manually count every feature: the implementer supplies automated reconciliation and investigates discrepancies you observe.

The planned expanded-comparison outline represents a possible later extraction. Seeing it on the map does not mean expanded data was generated.

## Step 6: Record and return observations

Use the supplied observation table or copy this template into a local Markdown file. Keep each suspicious feature in its own record.

```text
Package ID:
Reviewer and date:
Google Earth product; browser/version if applicable:
Case ID and place:
Source way/node IDs and segment IDs:
Longitude/latitude, if available:
Expected observation from case list:
Actual observation:
Status: pass / fail / unresolved / not_run
Imagery date: known date / unknown
Screenshot filenames:
Question or requested follow-up:
```

Example observation: "DEN-03: two lines overlap in plan view. I can see different endpoint IDs, but the bridge approach is unclear in imagery. Status: unresolved. Please check the original source references." You need not decide whether this is a source omission, an export defect, or a future walking-rule issue.

Return the notes and screenshot paths in the development chat. Avoid editing or re-exporting the original KMZ; your evidence must continue to refer to the validated file. The implementer records the investigation, cause, and disposition, and supplies a new package if code/source changes require regeneration.

## Step 7: Make the regional acceptance decision

After findings are investigated, review the case outcomes, count reconciliation, known defects, unperformed checks, and stated limitations. If satisfactory, an acceptance statement can say:

> I accept Gate 2 for regional inspection package [ID], source hash [hash], with the documented limitations and finding dispositions [reference]. This permits provisional pedestrian-policy development.

If a required case remains unresolved, identify it and request follow-up. A successful Google Earth import, synthetic trial, or plausible picture does not by itself complete Gate 2.

## Troubleshooting

| Problem | Action |
|---|---|
| No package path was included with the handoff | Ask the implementer for the exact topology and diagnostic package folders. Do not select the newest folder by guesswork; use the package ID and README. |
| KMZ will not open or is slow | Record product/version, filename, file size, error and approximate load time. Ask for a smaller validated partition or another viewer; do not delete features to make it fit. |
| Only one coincident node is clickable | Select by ID in the folder list, toggle the other feature off, or use the companion evidence. Record the limitation if both cannot be inspected. Do not drag points apart. |
| A zero-length line is invisible | Use its diagnostic marker and read the segment/endpoint IDs. An invisible line is not necessarily a missing source record. |
| Text is cut off | Record the object ID and use its keyed full evidence record. Ask the implementer for a readable excerpt; do not assume missing display text means missing source tags. |
| Bridge looks flat or tunnel looks above ground | Ground-level rendering is intentional. Inspect tags and references; this package has no measured vertical elevations. |
| Imagery disagrees with a path | Record location, IDs, imagery date and screenshot. Preserve geometry until the pinned source is investigated. |
| Viewer requests cloud upload | Stop that import path and ask for local-file instructions or another viewer. |
| Folder controls or descriptions differ from this guide | Record the screen labels/error. Viewer-specific steps must be confirmed in the actual trial. |

## Check the revised descriptions

Open the newly supplied topology packet and select `way/10/segment/0`. The description should start with Segment ID, From node, To node, and Length along Earth's surface, followed by key source tags. Technical details and the complete raw tag list should follow below. Check node 2, way 11, and one diagnostic marker as well. Report whether the important fields are readable without searching through technical information. Revised packets need a fresh readability check; the earlier functional passes remain historical evidence for the earlier packets.


## Regional partial packets

Follow the [case-only delivery procedure](regional-case-delivery-spec.md#user-review) when a regional package is labeled partial. Open its overview first, then use the case CSV `kmz_files` column to select network files. Work on a separate copy of the observation template. A missing object outside the selected view is not evidence of a missing source record. Record the package ID with every review. Current regional manual review is pending.

# Requirements

Requirement IDs are stable; do not renumber them. Reference them in issues and pull requests. Status values: Not started, In progress, Met (link the evidence), Deferred (link the decision).

| ID | Requirement | Status | Evidence / notes |
|---|---|---|---|
| R-01 | **Deployment.** The application builds to static files that run from a CDOT-managed host, including from a subdirectory. A deployment to an approved CDOT test URL demonstrates this, including range-request data loading, a web worker, and a file download. | Not started | The GitHub Pages preview is a development preview, not CDOT deployment evidence. |
| R-02 | **Methodology.** A written, versioned, approved specification defines the pedestrian network, station access, walking costs, analytical area, indicators, normalization, sub-indices, and total index. | Not started | [Methodology](methodology.md) |
| R-03 | **Data preparation.** A reproducible offline pipeline produces versioned display (PMTiles), routing, and indicator products described by a release manifest. Scoring runs in the browser unless a decision record approves otherwise. | Not started | [Data contract](data-contract.md) |
| R-04 | **Station input.** Users create, move, and delete stations on the map and import station files. Invalid, duplicate, and out-of-coverage records are reported without discarding current work. Optional ridership and forecast fields are accepted, and results state when they are absent. | Not started | Supported formats: see open scope items. |
| R-05 | **Results and exports.** A linked map and accessible tables show individual metrics, sub-indices, and the total index. Exports include tabular data, GIS geometry, and a printable accessible PDF report stating sources, data years, settings, method version, and limitations. | Not started | Browser print alone does not satisfy the PDF requirement. |
| R-06 | **Verification.** Benchmark, functional, accessibility, performance, browser-compatibility, and user-acceptance evidence is recorded. | Not started | [Validation](validation.md) |
| R-07 | **Handoff.** A maintainer can build the application, prepare a sample data release, deploy, and roll back using repository documentation alone. User guidance accompanies the release. | Not started | [Developer guide](../DEVELOPER.md) |
| R-08 | **Workflow behavior.** Walkshed generation and analysis run only on explicit user action. Changing an input marks existing results stale. Sessions can be saved to and restored from a local versioned file. Results distinguish per-station totals from combined unique coverage. | Not started | |
| R-09 | **Accessibility.** The application and its PDF output conform to WCAG 2.1 Level AA at minimum, as required for Colorado state agencies (HB21-1110 and OIT accessibility standards); the engineering target is WCAG 2.2 Level AA, consistent with Section 508. Every map action has a keyboard-operable alternative that does not require the map. | Not started | Automated checks alone do not establish conformance. |

## Open scope items

Decide these before implementing the affected feature; record the decision and update this file.

- **File formats:** CSV and GeoJSON first. SHP and KML import/export pending decision. Coordinate-system rules for each format.
- **Supported browsers:** list to be agreed with CDOT, including Microsoft Edge.
- **Supported input envelope:** maximum station count and acceptable time to results, set from measured performance evidence.

## Enhancements (not baseline)

Do not implement without an approved issue: multiple time budgets, slope or weather adjustments, user-drawn barriers or network exclusions, additional datasets, non-transit origin types, and transit travelsheds.

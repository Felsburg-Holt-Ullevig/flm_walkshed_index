# Regional case-only inspection delivery

## Purpose and authority

Provide small local Google Earth views of selected source objects when the complete regional dataset exceeds the core KMZ export limits. The developer selected case-only packets explicitly marked as partial views. This adapter does not change the canonical source-network contract, interpret access, repair topology, or approve Gate 2.

## Inputs and implementation

`tools/regional_inspection_delivery.py` consumes an accepted local configuration, a completed matching GeoPackage export, a source-backed case directory, and a source-acceptance record. Run with the pipeline Python environment:

```text
python pipeline/tools/regional_inspection_delivery.py --config <accepted.toml> --export <export-directory> --cases <case-directory> --acceptance <source-acceptance.json> --dataset-kind regional --case-only --grid 1
```

The delivery has its own version and script hash. Its manifest links the frozen parent pipeline identity, canonical file hashes, GeoPackage and report hashes, configuration, acceptance record, and case-selector hash. Editing this derived delivery adapter does not retroactively change completed upstream products.

## Selection and preservation

- Include case-requested ways and segments as complete ways. Include all ways incident to explicitly requested case nodes. Retain each included way's complete ordered node references and segments.
- Preserve exact string IDs, raw tags, coordinates, lengths, repeated references, and diagnostic geometry. Ground-clamped display does not imply physical connectivity.
- Divide whole-way groups into bounded KMZ files. Never clip or simplify a way to meet a limit. Reject an individual group that cannot fit.
- Declare node copies across files in the membership index. A coincident node with another ID remains a separate object.
- Retain the full canonical dataset and GeoPackage separately. List every excluded geometry and excluded relation record in compressed omission evidence. Included relation resolution flags describe the full parent subset, not the partial map.

## Outputs and acceptance

The overview KMZ contains coverage, case navigation and selected diagnostic pins. Network KMZ files contain source objects. The case CSV identifies which files to open. Companion evidence, membership, omissions, source acceptance, instructions and hashes accompany the files. All manual case statuses start as `not_run`.

The supervised worker validates input identities, reopens every KMZ, compares source fields and geometry to the parent, checks file membership and limits, and reconciles full versus included/excluded counts. Success promotes an output directory atomically and writes its completion report last. Failed staging remains available. No runtime dependency is added.

Automated coverage is in `tools/tests/test_regional_delivery.py`: source preservation, whole-way closure, coincident and large IDs, omissions, relation scope, repeatability, limit rejection and acceptance-hash rejection. Human inspection is separate. Missing selection criteria remain explicit gaps; they do not establish regional absence.

## User review

1. Read the generated `README.md` and confirm its package ID and **partial case-only** scope.
2. Open the overview through Google Earth's Local KML workflow already used for the synthetic trial.
3. Open `review-cases.csv`. For one case, open the network file(s) named in `kmz_files`. Keep only the files needed for that case visible.
4. Select objects from their source folders. Compare IDs, ordered endpoints, tags and geometry with the case instructions and companion evidence. Use visibility toggles to inspect overlapping objects individually.
5. Save a separate copy of `review-observations-template.csv`. Record pass, fail or unresolved, what was selected, and the observed mismatch or question. Do not edit the delivered evidence or completion report.
6. Return the package ID and observations. Regional inspection and explicit developer disposition are required before Gate 2 can close. An automated pass does not approve pedestrian connectivity or routing.

# Offline data preparation

Future preparation scripts will turn reviewed GIS and indicator sources into versioned display, routing, and analytical products consumed by the web app. This code can share the repository while executing separately from the public application.

No pipeline language/environment, source network, routing encoding, publishing account, or full dataset is configured yet. Python is a candidate; select and lock its dependencies when the first preparation task is approved.

Preserve provenance, CRS/units, source vintages, processing versions, coverage, output hashes, and rejected/skipped-record reasons. Validate a candidate package before promoting its published manifest. Keep large raw/staging/generated files in approved external storage or the ignored local data paths. See [data contract](../docs/data-contract.md) and [validation](../docs/validation.md).

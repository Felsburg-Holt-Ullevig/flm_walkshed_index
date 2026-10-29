# Data storage policy

Keep only small cleared fixtures, source catalogs, and release metadata in ordinary Git history. Add their contracts and provenance with the first dataset. There are no data fixtures or production releases in the foundation.

`raw/`, `staging/`, and `generated/` are ignored local working locations. Statewide GIS data and published archives need an approved external source/storage location; ignored files are not backed up by Git. Do not put client documents, credentials, or user sessions here for public publication.

See the [data contract](../docs/data-contract.md) for the distinction between map display, routing connectivity, and indicator inputs.

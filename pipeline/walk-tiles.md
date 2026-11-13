# Walk tile build

The [version 0 reader guide](../contracts/walk-tiles/v0/README.md) describes the
folder layout, every field, boundary rules, graph reconstruction and a worked
example without requiring access to the builder code.

The offline tile builder writes `data/generated/prototype/walk-tiles/<release-id>/`. Each release contains `manifest.json`, a `network/` directory of fixed 0.01-degree cells, and `size-report.md`. Each tile contains whole source segments that touch its closed cell boundaries; readers deduplicate by segment `id` and connect only matching OpenStreetMap node IDs. Coordinates and lengths preserve the source values. Tile files are experimental JSON, not the existing browser package format.

Lengths are international feet; the manifest declares exactly `default_speed_mph: 2.8`. Readers calculate travel time from feet and mph (5,280 feet per mile, 3,600 seconds per hour). Longitude/latitude and the grid remain angular degrees. Tile geometry, connectivity and lengths are unaffected by the default speed. Historical source-package travel times are not exported or used as the new default.

Build the accepted Denver sample from the repository root:

```powershell
.venv/Scripts/python.exe pipeline/tools/build_walk_tiles.py --release-id denver-policy03-walk-tiles-20261111-imperial
```

Run focused verification tests and the full Python suite:

```powershell
.venv/Scripts/python.exe -m pytest pipeline/tests/test_walk_tiles.py
.venv/Scripts/python.exe -m pytest pipeline/tests
pnpm lint
```

The output omits 24,170 excluded and 11,645 unknown candidates. Coverage is not established; this folder does not prove that an absent cell has no real-world walkable street. Walking restrictions in 1,050 relations remain unsupported and 47,490 relation members are unresolved. Snapping, reachability, Census data, wheelchair assessment, and map display are not implemented here. Public redistribution is not cleared. No tile-reader compatibility result is claimed.

The separate [Step 3 reference workflow](walk-reference.md) prepares bounded
Greeley, Broomfield, and Fraser samples and compares tile-based and source-graph
reachability. Their tile folders use the same schemas, with an explicit
complete-way extraction selection and their own omission/restriction counts.
The counts above describe Denver only. The existing Denver files are preserved.

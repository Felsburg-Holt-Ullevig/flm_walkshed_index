# Walk tiles version 0: reader guide

A walk-tile release stores a pedestrian network as UTF-8 JSON files. Load the
manifest first, then the network tiles it lists. The routing engine is separate:
these files supply segment geometry, lengths and allowed directions. They contain
no walking times, polygons, Census indicators or scores.

## Folder layout

```text
<release-id>/
  manifest.json
  network/
    <col>_<row>.json
  size-report.md
```

`manifest.json` describes one release. Each listed network file contains a cell's
segments. `size-report.md` is a human-readable build report, not reader input;
reported gzip sizes are measurements, not additional compressed files.
Reference tests are delivered separately as `reference/cases.json`,
`reference/walk-reference.gpkg` and `reference/validation.json` beneath a reference
output directory. They are not required to load a network release. See the
[reference guide](../../../pipeline/walk-reference.md) for those testing products.

## Manifest fields

All fields below are required. The [manifest schema](manifest.schema.json) defines
the exact accepted values and structure; unknown fields are rejected in version 0.
Schema identifiers are names, not download endpoints. Resolve the three supplied
schemas locally when validating files.

| Field | Meaning |
|---|---|
| `format`, `version` | Exactly `"walk-tiles"` and integer `0`. Reject unsupported formats or versions. |
| `release_id` | This tile release's identity; letters, digits, hyphens and underscores. |
| `source_release_id` | Identity of its source network. Do not mix releases. |
| `grid` | Cell definition and boundary rules, specified below. |
| `crs`, `coordinate_order` | Exactly `"EPSG:4326"`, `"longitude_latitude"`; positions are `[longitude, latitude]` in degrees. |
| `length_unit` | Exactly `"international_foot"`. |
| `default_speed_mph` | Exactly `2.8`. |
| `coverage` | Included-geometry extent and coverage warning, specified below. |
| `tiles` | Nonempty list of existing network files, specified below. |
| `source` | Source dates, eligibility-rule version and selection rule, specified below. |
| `counts` | Source totals and tile totals, specified below. |
| `attribution` | `"© OpenStreetMap contributors"`. |
| `license`, `license_url` | `"ODbL-1.0"`, `"https://opendatacommons.org/licenses/odbl/1-0/"`. |
| `attribution_url` | `"https://www.openstreetmap.org/copyright"`. |
| `distribution_status` | `"local_experimental_not_cleared_for_redistribution"`; copying files locally does not authorize publication. |
| `limitations` | Nonempty list of warnings that must remain attached to results. |

`coverage.bbox` is `[west, south, east, north]`, the extent of included geometry.
`coverage.readiness` is `"not_established"`; `coverage.meaning` is
`"extent of included source geometry, not a guarantee of complete walkable streets"`.
An unlisted cell has no exported segment, but this does **not** establish that it
has no real-world walkable street. The box is not an accepted coverage boundary.
An unreadable listed tile is a loading failure, not an empty cell.

Each `tiles` entry has integer `col` (0–35999), integer `row` (0–17999),
`path` exactly `network/<col>_<row>.json`, positive integer `segments` (records in
that file, including cross-cell copies), and positive integer `bytes` (the UTF-8
file's byte count). Entries are sorted by column then row, without duplicates.
Resolve paths relative to the manifest directory; do not construct arbitrary
paths from unvalidated input. There are no tile checksums in this format.

`source` has `osm_data_timestamp` (`"2026-11-01T21:21:36Z"`), `download_date`
(`"2026-11-02"`), `walking_rule_version` (`"pedestrian-policy-0.3"`), and
`selection`. Selection is either
`"existing included segments; no re-extraction or reclassification"` or
`"highway-node-in-bbox-complete-way-1; pedestrian-policy-0.3 included segments"`.
Version 0 schemas intentionally accept these source dates and rules only.

`counts` contains `included` (unique exported segments), `excluded` and
`unknown_left_out` (omitted candidates), `nodes` (unique endpoint IDs),
`directed_arcs` (allowed directed connections), `tiles`, `segment_copies` (sum of
all tile record counts), and `total_length_ft` (sum of unique segment lengths).
All are integer counts except positive numeric `total_length_ft`.

## Grid and boundaries

`grid` contains these exact values:

```json
{
  "cell_size_degrees": 0.01,
  "origin": [-180, -90],
  "coordinate_scale": 10000000,
  "cell_size_scaled": 100000,
  "coordinate_rounding": "none; exact decimal input, maximum seven places",
  "segment_membership": "closed cells; whole segment in every touched cell",
  "point_index": "floor((lon+180)/0.01), floor((lat+90)/0.01) using exact decimal arithmetic"
}
```

Use decimal arithmetic or exact scaled integers, not floating-point rounding at
cell edges. Multiply a coordinate by 10,000,000 exactly; reject more than seven
decimal places rather than rounding. A cell's west/south scaled corner is
`(col * 100000 - 1800000000, row * 100000 - 900000000)`, and its east/north
corner adds 100,000 to each coordinate. All four edges are included.

A whole segment appears in **every** cell touched by any part of its line,
including endpoint, edge and corner contact. Edge contact belongs to both cells;
corner contact can belong to four. Keep only valid global columns/rows. At +180
or +90 degrees, the point formula yields an index outside that range; membership
uses the touching valid edge cells. The format does not specify longitude wrapping.
Segments are never cut at cell boundaries. Their coordinates may extend beyond
the tile that contains them. Point indexing alone does not determine segment
membership, and a line's bounding box alone is insufficient.

## Tile and segment fields

A tile has exactly `col`, `row`, and a nonempty `segments` array. Its indices must
match its manifest entry and filename. Records are sorted by `id`, with no ID
repeated inside one tile. The [tile schema](tile.schema.json) references the
[segment schema](segment.schema.json).

Every segment has all of these fields:

| Field | Meaning |
|---|---|
| `id` | Nonempty, stable segment identity. Treat it as opaque text. |
| `from`, `to` | Nonempty OpenStreetMap endpoint node IDs, stored as text. |
| `len_ft` | Positive, finite length in international feet, copied from the source. Use this value for costs rather than measuring the drawn line again. |
| `dir` | `both`: both directions; `forward`: `from` → `to`; `reverse`: `to` → `from`. |
| `coords` | At least two `[longitude, latitude]` positions, ordered from `from` to `to`, including when `dir` is `reverse`. |
| `way_id` | Nonempty OpenStreetMap way ID as text; multiple segments can share it. |
| `hwy` | Nonempty source `highway` tag. |
| `name`, `sidewalk`, `footway` | Source tag strings; `""` means the tag is absent. It does not mean `no`. |

## Reconstructing the network

Validate input at runtime, including finite numbers, duplicate JSON keys and
cross-file identities/counts. Deduplicate loaded segments by `id`; repeated copies
must agree in every field. Conflicting copies are an error. Keep distinct segment
IDs even if geometry is identical. Join endpoints **only by node ID**. Geometric
crossings, coincident coordinates and intermediate line positions do not create
connections. No separate node file or tile-stitching operation is needed.

For each unique segment, add the directed connection(s) permitted by `dir`, each
with the stored length. At exactly 2.8 mph:

```text
feet per minute = 2.8 * 5280 / 60 = 246.4
seconds = len_ft * 3600 / (2.8 * 5280)
```

Continue loading tiles needed by a search; a map viewport or loaded-tile edge is
not a routing boundary. A search over an incomplete subset must not claim a
complete result. Loading all manifest-listed tiles reconstructs the full exported
network. Origin snapping and search algorithms belong to the consuming engine.
Unsupported restrictions and other manifest limitations still apply.

## Worked example: one saved Denver segment

Release `denver-policy03-walk-tiles-20261111-imperial` lists
`network/7500_12975.json` with 2,672 records and 683,562 bytes. Its cell extends
from longitude -105.00 to -104.99 and latitude 39.75 to 39.76. This is one actual
record from that file, not the complete tile:

```json
{
  "id": "way/1053553372/segment/0",
  "from": "176099653",
  "to": "3286982561",
  "len_ft": 41.774602929756,
  "dir": "both",
  "coords": [[-104.9941572, 39.7503754], [-104.9942639, 39.7504552]],
  "way_id": "1053553372",
  "hwy": "secondary",
  "name": "18th Street",
  "sidewalk": "",
  "footway": ""
}
```

Both positions are inside this cell; this segment occurs in this tile only.
Create two directed connections between the two node IDs, each costing
41.774602929756 feet, or approximately **10.172387 seconds** at 2.8 mph. A segment
with the same endpoint ID joins here; one with only the same coordinate does not.
Deduplicating the complete release yields 312,004 segments, 624,008 directed
connections and 23,928,706.607894484 feet, rather than counting its 320,483 tile
copies as separate segments. Coverage remains unestablished.

# Basemap label fonts

MapLibre glyph files (signed-distance-field PBF) for the basemap's labels, served with the
application so label rendering does not wait on the tile service's slow font endpoint.

- Font: Noto Sans Regular, Italic and Bold (Google Noto project), SIL Open Font License 1.1.
- Source: prebuilt glyphs from the OpenMapTiles fonts project,
  `https://github.com/openmaptiles/fonts`, `gh-pages` branch, folders
  `Klokantech Noto Sans Regular|Italic|Bold`, renamed here to `Noto Sans Regular|Italic|Bold`.
- Ranges included: `0-255` (Basic Latin, Latin-1), `256-511` (Latin Extended),
  `8192-8447` (general punctuation). Characters outside these ranges have no glyphs and are not
  drawn.

Status: provisional. The published basemap style specifies Avenir Next LT Pro and Tahoma, which are
not redistributable; `src/adapters/basemaps/oit-vector.ts` maps each label to the nearest Noto Sans
style. Adoption beyond the prototype needs the data owner's approval of the change in label
typography.

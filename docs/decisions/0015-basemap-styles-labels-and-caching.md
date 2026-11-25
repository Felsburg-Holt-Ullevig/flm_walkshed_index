# 0015. Basemap styles, labels and caching

Status: Proposed for the prototype; data-source and typography approval pending
Date: 2026-11-25

## Context
The OIT vector basemap adopted in [decision 0014](0014-map-renderer-and-provisional-basemap.md) loaded slowly and competed visually with walkshed overlays. Its label data limits label control, and its place names lack hierarchy.

**Load time.** Measured in headless Chrome at 1366×800, at the default Denver view, three runs each. A first visit took 6.8–10.2 s to a fully drawn map; a return visit took 2.4–3.0 s.
- The three label font files took 2–7.7 s. Each is about 75 kB, is served uncompressed, and waits 2.2–2.5 s for its first byte.
- Every service response is marked `Cache-Control: max-age=0, must-revalidate`, so return visits revalidate every file.
- The style request waited for the lazily loaded map engine.

**Label data.** Decoding the service's tiles at zoom 6–16 showed that label features carry only `_name`, `_label_class` and `_len`.
- Road labels come in four fixed classes; there is no road type or functional class.
- Local road and trail names exist from zoom 14, but the published style shows them from 15.9.
- Place names are one point layer that mixes municipalities with unincorporated localities. It has no type or population and is absent above zoom 10.
- Municipal boundary polygons have no attributes. The tiles have no neighbourhoods, sidewalks or transit stops.

## Decision
**Loading**
- Start the style request on first render, in parallel with the map engine download.
- Serve label glyphs with the application: Noto Sans Regular, Italic and Bold (SIL Open Font License), ranges 0–255, 256–511 and 8192–8447. Each published font maps to the nearest Noto Sans style. The published fonts (Avenir Next LT Pro, Tahoma) are commercial and are not redistributed.
- In production builds, a service worker caches responses from the vector basemap host. It serves the cached copy and refreshes it in the background. Entries are limited to 3,000 and are not served after seven days, except when the network fails.

**Styles**
Every style is a rewrite of the published style as it loads, keyed to tile data layers (`source-layer`) rather than layer IDs:
- muted (default);
- dark;
- high contrast;
- minimal;
- walking focus, limited to trails, parks and water because the tiles have no pedestrian infrastructure;
- tinted.

The published style, the dynamic map service and a plain background remain available. `?basemap=` selects a style, and the panel records the choice in the address.

**Labels**
A walkshed label preset (default; `?labels=original` disables it):
- local road and trail names from zoom 14;
- bold and larger major road names;
- wider label spacing and padding;
- placeholder names ("Private Rd") hidden;
- regional names hidden above zoom 12;
- collision priority, from highest: shields, major roads, place names, trails and parks, neighbourhoods, local roads, water and regional names.

**Place names**
`public/data/place-labels.geojson` (560 points, about 93 kB), built by `scripts/build-place-labels.mjs`, replaces the tile place names:
- municipalities and census-designated places from the U.S. Census Bureau (TIGERweb 2020), ranked into three tiers by 2020 population;
- label positions from USGS GNIS populated-place points (454 of 482 matched by name within 40 km). The Census internal point is only guaranteed to lie inside a place, and was about 9 km from downtown Denver;
- Denver statistical neighbourhoods from the City and County of Denver.

Municipalities are drawn in bold spaced capitals, unincorporated communities in regular type, and neighbourhoods in italic spaced capitals. They are visible to zoom 15–17.

## Evidence
Same method as the baseline above, after the changes:

| | Before | After |
|---|---|---|
| First visit | 6.8–10.2 s | 1.6–4.2 s (median about 2.3 s, with or without the service worker) |
| Return visit | 2.4–3.0 s | 0.50–0.52 s (one run 1.2 s) |

The service's response time varied widely between runs. Visual checks covered each style at desktop width and at 390 px, and place labels at zoom 10–15. Other browsers, devices and network locations were not measured.

## Alternatives considered
- Leave fonts on the service: about 5 s of each first visit.
- Redistribute the published fonts: licence not available.
- Write a complete custom style: more control and no style request, but a separate design effort. Retained as an option.
- Use another provider's basemap (OpenFreeMap, Protomaps, MapTiler, Esri): different data and terms. Not pursued while the state basemap is preferred.
- Restyle only CDOT's place points with a fixed municipality list: improves hierarchy only to zoom 10.

## Consequences
- **Labels look different from the published map.** Label typography changes from Avenir/Tahoma to Noto Sans. Characters outside the bundled ranges are not drawn.
- **Return visits can be stale.** They show the basemap as last cached, and an OIT update appears one visit later. Cached responses occupy browser storage, about 10–30 MB at the limit.
- **Style rewrites can silently stop applying.** They depend on the tile data layer names; if OIT renames them, a variant stops restyling those layers without an error.
- **New data sources need approval.** Census and USGS data are public domain. Denver's neighbourhood data is provided "as is", and its terms require users to indemnify the City and County of Denver. The data owner must approve all three sources, and the typography change, before use beyond the prototype.
- **Neighbourhood coverage is Denver only.** Place populations are from 2020 until the file is rebuilt.
- **The source data has quirks.** Its capitalisation ("18Th St") and inconsistent road-name variants cannot be corrected in the style.

## Revisit when
- The data owner declines a source, the Denver terms, or the typography change.
- OIT changes the service's tile data layers, cache headers or fonts.
- Measured load times on the CDOT host differ materially from these.
- A custom or self-hosted basemap is adopted.

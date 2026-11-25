# 0014. Map renderer and provisional basemap

Status: Accepted for the prototype; production basemap use pending State of Colorado OIT confirmation
Date: 2026-11-25

## Context
The application needs an interactive map with a background basemap, user stations and walkshed polygons, without a paid map provider or a custom map server. Three State of Colorado GeoData items were candidates. Inspection of their ArcGIS item records found that the "State of Colorado Basemap" item (`62f677708c5040399e490cc58505cdec`) is a web map whose basemap is an OIT-owned hosted vector tile service, `Statewide_Basemap/VectorTileServer`, drawn over Esri World Hillshade. The same OIT content is also published as a dynamic map service, `OIT/Colorado_State_Basemap/MapServer`, which has no tile cache. The two "Light Gray Canvas" items are Esri's `World_Basemap_v2` service under the Esri Master License Agreement.

## Decision
- Render the map with MapLibre GL JS (BSD-3-Clause), pinned at an exact version.
- Use the OIT hosted vector tile service as the default basemap. A validated adapter converts the published ArcGIS style into MapLibre sources and layers: absolute resource URLs, an explicit tile template, prefixed IDs, and street labels offset from road lines.
- Offer the OIT dynamic map service (`/export` images) and a plain background as alternates.
- Build the rendered style from the selected basemap plus application overlays. Losing or switching the basemap never removes stations or walksheds; walkshed fills draw beneath basemap labels.
- Request basemap resources directly from the browser; no proxy.

## Evidence
Measured on 2026-11-25 from one cloud location in headless Chromium:

| Check | Vector tile service | Dynamic map service `/export` |
|---|---|---|
| Cross-origin requests | Allowed (origin reflected) | Allowed (origin reflected) |
| 16 uncached tiles requested together, Aurora | 4 vector tiles cover the area, about 0.7 s each | 13–14 s each |
| First complete render, Denver Union Station, zoom 15 | 4.0 s | 60 s |
| First complete render, Leadville, Craig, Aurora (zoom 14–16) | 2.5–3.1 s | 2.3–2.8 s |
| Failed requests | None | None |

The dynamic service caches recently drawn images, so repeat views are faster than first views. Other browsers, high-density displays and other network locations were not measured.

## Alternatives considered
- Dynamic map service as the default: first loads of 7–60 s in dense areas.
- Esri Light Gray Canvas: licence and access terms for a public CDOT application are unconfirmed.
- Self-hosted vector basemap (PMTiles): requires basemap preparation, range-request hosting and a refresh process; retained as the fallback if the state service is unsuitable.
- Server-side proxy: unnecessary for cross-origin access and would add CDOT hosting and maintenance.

## Consequences
- The basemap depends on an OIT ArcGIS Online service whose operation, limits and change schedule FHU does not control. The service item was created in 2026 and carries a no-warranty disclaimer.
- Basemap tile requests reveal the map areas a user views to the State of Colorado and ArcGIS Online. Station coordinates are not sent.
- Attribution names State of Colorado OIT, CDOT and partners, and OpenStreetMap contributors; building footprints in the basemap are OpenStreetMap data.
- The source data title-cases ordinal street names ("15Th St").
- The map engine adds about 286 KB (gzip) of JavaScript, a 147 KB (gzip) worker and 10 KB (gzip) of CSS, loaded separately from the initial page.
- The MapLibre worker is emitted as a `.js` asset, because some static hosts do not serve `.mjs` with a JavaScript content type.

## Revisit when
OIT or CDOT GIS responds on supported public use, usage limits and address stability; CDOT supplies a preferred basemap; the service changes or becomes unavailable; or measured performance on the CDOT host or other browsers is unacceptable.

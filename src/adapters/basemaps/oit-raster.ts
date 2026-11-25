import { BASEMAP_LAYER_PREFIX, type BasemapStyle } from './basemap';

/**
 * The same OIT basemap content published as a dynamic ArcGIS MapServer. It has no tile cache,
 * so each map tile is an `/export` request that the server draws on demand. It is kept as an
 * alternate because it can be slow in dense areas.
 */
export const OIT_MAPSERVER_URL =
  'https://gis.colorado.gov/public/rest/services/OIT/Colorado_State_Basemap/MapServer';

export const OIT_RASTER_SOURCE_ID = 'basemap-oit-raster';

export function oitRasterBasemap(serviceUrl: string, attribution: string): BasemapStyle {
  // MapLibre substitutes {bbox-epsg-3857} with each tile's Web Mercator bounds in metres.
  const tile =
    `${serviceUrl}/export?bbox={bbox-epsg-3857}&bboxSR=3857&imageSR=3857` +
    '&size=256,256&format=png32&transparent=false&f=image';
  return {
    sources: {
      [OIT_RASTER_SOURCE_ID]: { type: 'raster', tiles: [tile], tileSize: 256, attribution },
    },
    layers: [
      { id: `${BASEMAP_LAYER_PREFIX}oit-raster`, type: 'raster', source: OIT_RASTER_SOURCE_ID },
    ],
  };
}

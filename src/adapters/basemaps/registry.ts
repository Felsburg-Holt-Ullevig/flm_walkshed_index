import type { BasemapDefinition, BasemapId } from './basemap';
import { OIT_MAPSERVER_URL, oitRasterBasemap } from './oit-raster';
import { loadOitVectorBasemap, OIT_VECTOR_SERVICE_URL } from './oit-vector';

// Service addresses can be replaced at build time without changing application code.
const vectorUrl = import.meta.env.VITE_OIT_VECTOR_BASEMAP_URL || OIT_VECTOR_SERVICE_URL;
const rasterUrl = import.meta.env.VITE_OIT_RASTER_BASEMAP_URL || OIT_MAPSERVER_URL;

const OIT_ITEM_URL = 'https://geodata.colorado.gov/maps/62f677708c5040399e490cc58505cdec/explore';

/**
 * Credits for the OIT basemap. The linked item lists every layer source: CDOT, DOLA, CPW, CDPHE,
 * the City and County of Denver, USGS NHDPlus, federal land agencies and Esri Living Atlas.
 * Building footprints are OpenStreetMap data, which requires the OpenStreetMap credit.
 */
export const OIT_ATTRIBUTION =
  `Basemap: <a href="${OIT_ITEM_URL}">State of Colorado OIT, CDOT and partners</a>; ` +
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

function hostOf(url: string): string {
  return new URL(url).host;
}

export const BASEMAPS: readonly BasemapDefinition[] = [
  {
    id: 'oit-vector',
    label: 'Colorado state basemap',
    description: 'Pre-built vector tiles published by the State of Colorado OIT.',
    host: hostOf(vectorUrl),
    load: (signal) => loadOitVectorBasemap(vectorUrl, OIT_ATTRIBUTION, signal),
  },
  {
    id: 'oit-raster',
    label: 'Colorado state basemap (map server images)',
    description:
      'The same map drawn on request by the state map server. Slower; dense areas can take up to a minute.',
    host: hostOf(rasterUrl),
    load: async () => oitRasterBasemap(rasterUrl, OIT_ATTRIBUTION),
  },
  {
    id: 'none',
    label: 'No basemap',
    description: 'Plain background. Stations and walksheds still display.',
    host: null,
    load: async () => ({ sources: {}, layers: [] }),
  },
];

export const DEFAULT_BASEMAP_ID: BasemapId = 'oit-vector';

export function basemapById(id: BasemapId): BasemapDefinition {
  const found = BASEMAPS.find((basemap) => basemap.id === id);
  if (!found) throw Error(`Unknown basemap: ${id}`);
  return found;
}

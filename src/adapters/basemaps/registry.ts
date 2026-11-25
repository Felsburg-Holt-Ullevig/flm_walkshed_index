import type { BasemapDefinition, BasemapId, BasemapStyle } from './basemap';
import { applyLabelPreset, type LabelPreset } from './labels';
import { muteBasemapStyle } from './muted';
import { OIT_MAPSERVER_URL, oitRasterBasemap } from './oit-raster';
import { loadOitVectorBasemap, OIT_VECTOR_SERVICE_URL, prefetchOitVectorStyle } from './oit-vector';
import { type BasemapVariant, styleVariant } from './variants';

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

/**
 * Label fonts are served with the application (public/fonts) because the tile service answers
 * glyph requests slowly. MapLibre needs an absolute template, resolved against the page so the
 * app also works from a subdirectory.
 */
function appUrl(path: string): string {
  return new URL(`${import.meta.env.BASE_URL}${path}`, window.location.href).href;
}

function localGlyphsUrl(): string {
  // Appended after resolving, because URL parsing would percent-encode the template braces.
  return `${appUrl('fonts/')}{fontstack}/{range}.pbf`;
}

function hostOf(url: string): string {
  return new URL(url).host;
}

/** Loads the state vector basemap, restyles it, then applies the label preset. */
async function loadVector(
  signal: AbortSignal,
  restyle: (style: BasemapStyle) => BasemapStyle,
  labels: LabelPreset = DEFAULT_LABEL_PRESET,
): Promise<BasemapStyle> {
  const style = await loadOitVectorBasemap(vectorUrl, OIT_ATTRIBUTION, signal, fetch, {
    localGlyphs: localGlyphsUrl(),
  });
  // Labels first, so each style also recolours the place-name layers the preset adds.
  return restyle(
    applyLabelPreset(style, labels, { placesUrl: appUrl('data/place-labels.geojson') }),
  );
}

/** A restyled version of the state vector basemap (see variants.ts). */
function variant(
  id: BasemapId,
  name: BasemapVariant,
  label: string,
  description: string,
): BasemapDefinition {
  return {
    id,
    label,
    description,
    host: hostOf(vectorUrl),
    load: (signal, options) =>
      loadVector(signal, (style) => styleVariant(style, name), options?.labels),
  };
}

export const BASEMAPS: readonly BasemapDefinition[] = [
  {
    id: 'oit-vector',
    label: 'Standard',
    description: 'The state vector basemap in its published colours.',
    host: hostOf(vectorUrl),
    load: (signal, options) => loadVector(signal, (style) => style, options?.labels),
  },
  {
    id: 'oit-vector-muted',
    label: 'Muted',
    description: 'The state vector basemap in light greys so stations and walksheds stand out.',
    host: hostOf(vectorUrl),
    load: (signal, options) => loadVector(signal, muteBasemapStyle, options?.labels),
  },
  variant('oit-vector-dark', 'dark', 'Dark', 'Dark background with light streets and labels.'),
  variant(
    'oit-vector-contrast',
    'contrast',
    'High contrast',
    'White background, dark streets, black labels and no area shading except water.',
  ),
  variant(
    'oit-vector-minimal',
    'minimal',
    'Minimal',
    'Very light streets, water and parks only; public lands, trails, rail and buildings hidden.',
  ),
  variant(
    'oit-vector-walking',
    'walking',
    'Walking focus',
    'Muted, with trails, parks and water in colour. The state tiles have no sidewalks or transit stops.',
  ),
  variant('oit-vector-tinted', 'tinted', 'Tinted', 'The muted map in pale blue-greys.'),
  {
    id: 'oit-raster',
    label: 'Map server images',
    description:
      'The standard map drawn on request by the state map server. Slower; dense areas can take up to a minute.',
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

export const DEFAULT_BASEMAP_ID: BasemapId = 'oit-vector-muted';

export const DEFAULT_LABEL_PRESET: LabelPreset = 'walkshed';

/** The label preset named by `?labels=` (walkshed or original), else the default. */
export function labelsFromAddress(search: string): LabelPreset {
  return new URLSearchParams(search).get('labels') === 'original'
    ? 'original'
    : DEFAULT_LABEL_PRESET;
}

/** Host whose responses the service worker (public/sw.js) caches. */
export const CACHED_BASEMAP_HOST = hostOf(vectorUrl);

/** Starts fetching a vector basemap's style before the map engine has downloaded. */
export function prefetchBasemap(id: BasemapId): void {
  if (id.startsWith('oit-vector')) prefetchOitVectorStyle(vectorUrl);
}

/** Short names accepted in the `?basemap=` address parameter. */
export const BASEMAP_PARAM: Readonly<Record<string, BasemapId>> = {
  standard: 'oit-vector',
  muted: 'oit-vector-muted',
  dark: 'oit-vector-dark',
  contrast: 'oit-vector-contrast',
  minimal: 'oit-vector-minimal',
  walking: 'oit-vector-walking',
  tinted: 'oit-vector-tinted',
  images: 'oit-raster',
  none: 'none',
};

/** The `?basemap=` name for a basemap. */
export function basemapParam(id: BasemapId): string {
  return Object.keys(BASEMAP_PARAM).find((name) => BASEMAP_PARAM[name] === id) ?? 'standard';
}

/** The basemap named by `?basemap=` (see BASEMAP_PARAM), else the default. */
export function basemapFromAddress(search: string): BasemapId {
  const name = new URLSearchParams(search).get('basemap');
  if (name !== null && !Object.hasOwn(BASEMAP_PARAM, name)) return DEFAULT_BASEMAP_ID;
  return (name !== null && BASEMAP_PARAM[name]) || DEFAULT_BASEMAP_ID;
}

export function basemapById(id: BasemapId): BasemapDefinition {
  const found = BASEMAPS.find((basemap) => basemap.id === id);
  if (!found) throw Error(`Unknown basemap: ${id}`);
  return found;
}

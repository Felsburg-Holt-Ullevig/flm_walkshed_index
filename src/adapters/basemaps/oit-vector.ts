import {
  BASEMAP_LAYER_PREFIX,
  BasemapError,
  type BasemapStyle,
  type LayerSpecification,
  type SourceSpecification,
} from './basemap';

/**
 * Colorado OIT statewide basemap published as an ArcGIS Online hosted vector tile service.
 * It is the service behind the "State of Colorado Basemap" item on geodata.colorado.gov.
 */
export const OIT_VECTOR_SERVICE_URL =
  'https://ti-cooit.img.arcgis.com/arcgis/rest/services/Statewide_Basemap/VectorTileServer';

export const OIT_VECTOR_SOURCE_ID = 'basemap-oit-vector';

const LAYER_TYPES = new Set([
  'background',
  'fill',
  'line',
  'symbol',
  'circle',
  'fill-extrusion',
  'heatmap',
  'hillshade',
  'raster',
]);
const MAX_LAYERS = 1000;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function invalid(detail: string): never {
  throw new BasemapError('invalid_content', `vector basemap style ${detail}`);
}

/** Resolves a style-relative resource URL and restores URL-template braces. */
function resolveTemplate(relative: string, styleUrl: string, field: string): string {
  let resolved: URL;
  try {
    resolved = new URL(relative, styleUrl);
  } catch {
    return invalid(`${field} is not a valid URL`);
  }
  if (resolved.protocol !== 'https:') invalid(`${field} must use HTTPS`);
  return resolved.href.replaceAll('%7B', '{').replaceAll('%7D', '}');
}

/** Vertical shift, in text heights, that moves a line label off its road. */
export const LINE_LABEL_OFFSET_EMS = 0.8;

/**
 * The published style centres street names on the road line. A label halo covers the road
 * beneath each letter but not beneath spaces, so a short piece of road shows between words and
 * reads as a dot. Moving plain text labels just off the line, as the service's own image
 * rendering does, removes the artefact. Shield labels (with an icon) and layers that already
 * set an offset are unchanged.
 */
function offsetLineLabel(layer: Record<string, unknown>): void {
  const layout = layer.layout;
  if (layer.type !== 'symbol' || !isRecord(layout)) return;
  const placement = layout['symbol-placement'];
  if (placement !== 'line' && placement !== 'line-center') return;
  if (layout['text-field'] === undefined || layout['icon-image'] !== undefined) return;
  if (layout['text-offset'] !== undefined || layout['text-anchor'] !== undefined) return;
  layout['text-offset'] = [0, -LINE_LABEL_OFFSET_EMS];
}

/**
 * Converts the style document an ArcGIS VectorTileServer publishes into MapLibre sources and
 * layers. ArcGIS styles use relative resource URLs and a source `url` that points at the
 * service description rather than TileJSON; both are replaced with absolute addresses and an
 * explicit tile template. Layer and source IDs are prefixed so overlays cannot collide.
 */
export function adaptEsriVectorStyle(
  input: unknown,
  serviceUrl: string,
  attribution: string,
): BasemapStyle {
  if (!isRecord(input)) invalid('is not a JSON object');
  if (input.version !== 8) invalid('is not style specification version 8');

  const sources = input.sources;
  if (!isRecord(sources)) invalid('has no sources object');
  const sourceEntries = Object.entries(sources);
  if (sourceEntries.length !== 1) invalid('must contain exactly one source');
  const [sourceKey, source] = sourceEntries[0] as [string, unknown];
  if (!isRecord(source) || source.type !== 'vector') invalid('source is not a vector source');

  const layers = input.layers;
  if (!Array.isArray(layers) || layers.length === 0) invalid('has no layers');
  if (layers.length > MAX_LAYERS) invalid(`has more than ${MAX_LAYERS} layers`);

  const styleUrl = `${serviceUrl}/resources/styles/root.json`;
  const ids = new Set<string>();
  let needsGlyphs = false;
  const adaptedLayers = layers.map((layer: unknown, index): LayerSpecification => {
    if (!isRecord(layer)) invalid(`layer ${index} is not an object`);
    const { id, type } = layer;
    if (typeof id !== 'string' || id === '') invalid(`layer ${index} has no ID`);
    if (ids.has(id)) invalid(`layer ID is duplicated: ${id}`);
    ids.add(id);
    if (typeof type !== 'string' || !LAYER_TYPES.has(type))
      invalid(`layer ${id} has unsupported type`);
    if (type !== 'background' && layer.source !== sourceKey)
      invalid(`layer ${id} references an unknown source`);
    const layout = layer.layout;
    if (type === 'symbol' && isRecord(layout) && layout['text-field'] !== undefined)
      needsGlyphs = true;
    const copy = structuredClone(layer);
    copy.id = `${BASEMAP_LAYER_PREFIX}${id}`;
    if (type !== 'background') copy.source = OIT_VECTOR_SOURCE_ID;
    offsetLineLabel(copy);
    return copy as unknown as LayerSpecification;
  });

  const adaptedSource: Record<string, unknown> = {
    type: 'vector',
    tiles: [`${serviceUrl}/tile/{z}/{y}/{x}.pbf`],
    attribution,
  };
  for (const key of ['minzoom', 'maxzoom'] as const) {
    const value = source[key];
    if (value !== undefined) {
      if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 24)
        invalid(`source ${key} is invalid`);
      adaptedSource[key] = value;
    }
  }
  const bounds = source.bounds;
  if (bounds !== undefined) {
    if (
      !Array.isArray(bounds) ||
      bounds.length !== 4 ||
      !bounds.every((value) => typeof value === 'number' && Number.isFinite(value))
    )
      invalid('source bounds are invalid');
    adaptedSource.bounds = [...bounds];
  }

  const result: BasemapStyle = {
    sources: { [OIT_VECTOR_SOURCE_ID]: adaptedSource as unknown as SourceSpecification },
    layers: adaptedLayers,
  };
  if (input.sprite !== undefined) {
    if (typeof input.sprite !== 'string') invalid('sprite must be a single URL');
    result.sprite = resolveTemplate(input.sprite, styleUrl, 'sprite');
  }
  if (input.glyphs !== undefined) {
    if (typeof input.glyphs !== 'string') invalid('glyphs must be a URL template');
    const glyphs = resolveTemplate(input.glyphs, styleUrl, 'glyphs');
    if (!glyphs.includes('{fontstack}') || !glyphs.includes('{range}'))
      invalid('glyphs template lacks {fontstack} or {range}');
    result.glyphs = glyphs;
  } else if (needsGlyphs) {
    invalid('has text labels but no glyphs URL');
  }
  return result;
}

export async function loadOitVectorBasemap(
  serviceUrl: string,
  attribution: string,
  signal: AbortSignal,
  fetchImpl: typeof fetch = fetch,
): Promise<BasemapStyle> {
  const styleUrl = `${serviceUrl}/resources/styles/root.json`;
  let response: Response;
  try {
    response = await fetchImpl(styleUrl, { signal, credentials: 'omit' });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new BasemapError('fetch_failed', `vector basemap style request failed (${error})`);
  }
  if (!response.ok)
    throw new BasemapError('fetch_failed', `vector basemap style returned HTTP ${response.status}`);
  let json: unknown;
  try {
    json = await response.json();
  } catch (error) {
    if (signal.aborted) throw error;
    throw new BasemapError('invalid_content', 'vector basemap style is not JSON');
  }
  return adaptEsriVectorStyle(json, serviceUrl, attribution);
}

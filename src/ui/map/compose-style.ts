import type {
  BasemapStyle,
  LayerSpecification,
  SourceSpecification,
  StyleSpecification,
} from '../../adapters/basemaps/basemap';

/** Application layers drawn over any basemap. IDs must not start with `basemap`. */
export interface OverlayStyle {
  sources: Record<string, SourceSpecification>;
  /** Drawn above basemap features but beneath basemap labels, so street names stay legible. */
  belowLabels: LayerSpecification[];
  /** Drawn above everything, including basemap labels. */
  onTop: LayerSpecification[];
}

/** No application layers yet; stations and walksheds will be added here. */
export const NO_OVERLAYS: OverlayStyle = { sources: {}, belowLabels: [], onTop: [] };

export const BACKGROUND_LAYER_ID = 'app/background';
export const BACKGROUND_COLOR = '#f2f2f0';

/**
 * Builds the complete style from an optional basemap and the application overlays. The map is
 * always rendered from this one description, so replacing or losing the basemap never removes
 * stations or walksheds.
 */
export function composeStyle(
  basemap: BasemapStyle | null,
  overlays: OverlayStyle,
): StyleSpecification {
  for (const id of Object.keys(overlays.sources))
    if (id.startsWith('basemap')) throw Error(`Overlay source ID is reserved: ${id}`);
  for (const layer of [...overlays.belowLabels, ...overlays.onTop])
    if (layer.id.startsWith('basemap') || layer.id === BACKGROUND_LAYER_ID)
      throw Error(`Overlay layer ID is reserved: ${layer.id}`);

  const baseLayers = basemap?.layers ?? [];
  const firstLabel = baseLayers.findIndex((layer) => layer.type === 'symbol');
  const split = firstLabel === -1 ? baseLayers.length : firstLabel;
  const style: StyleSpecification = {
    version: 8,
    sources: { ...(basemap?.sources ?? {}), ...overlays.sources },
    layers: [
      {
        id: BACKGROUND_LAYER_ID,
        type: 'background',
        paint: { 'background-color': BACKGROUND_COLOR },
      },
      ...baseLayers.slice(0, split),
      ...overlays.belowLabels,
      ...baseLayers.slice(split),
      ...overlays.onTop,
    ],
  };
  if (basemap?.sprite !== undefined) style.sprite = basemap.sprite;
  if (basemap?.glyphs !== undefined) style.glyphs = basemap.glyphs;
  return style;
}

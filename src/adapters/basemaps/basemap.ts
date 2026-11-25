import type { Map as MapLibreMap } from 'maplibre-gl';

// MapLibre does not re-export its style-specification types, so they are derived from the
// public setStyle signature instead of adding the style-spec package as a direct dependency.
export type StyleSpecification = Exclude<Parameters<MapLibreMap['setStyle']>[0], string | null>;
export type LayerSpecification = StyleSpecification['layers'][number];
export type SourceSpecification = StyleSpecification['sources'][string];

export type BasemapId =
  | 'oit-vector'
  | 'oit-vector-muted'
  | 'oit-vector-dark'
  | 'oit-vector-contrast'
  | 'oit-vector-minimal'
  | 'oit-vector-walking'
  | 'oit-vector-tinted'
  | 'oit-raster'
  | 'none';

/** Layer IDs of every basemap start with this prefix; source IDs start with `basemap-`. */
export const BASEMAP_LAYER_PREFIX = 'basemap/';

/**
 * The renderer-ready part of a basemap. It is merged with application overlays, so it carries
 * only its own sources and layers plus the style-level resources its symbol layers require.
 */
export interface BasemapStyle {
  sources: Record<string, SourceSpecification>;
  layers: LayerSpecification[];
  sprite?: StyleSpecification['sprite'];
  glyphs?: string;
}

export interface BasemapDefinition {
  id: BasemapId;
  label: string;
  description: string;
  /** Host that supplies imagery or tiles, shown so users know where map requests go. */
  host: string | null;
  /** `labels` applies to the vector basemaps only (see labels.ts). */
  load(signal: AbortSignal, options?: { labels?: 'walkshed' | 'original' }): Promise<BasemapStyle>;
}

export type BasemapErrorCode = 'fetch_failed' | 'invalid_content';

export class BasemapError extends Error {
  readonly code: BasemapErrorCode;
  constructor(code: BasemapErrorCode, detail: string) {
    super(`${code}: ${detail}`);
    this.name = 'BasemapError';
    this.code = code;
  }
}

import {
  type MapEventType,
  Map as MapLibreMap,
  NavigationControl,
  ScaleControl,
  setWorkerUrl,
} from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
// MapLibre looks for its worker beside its own module, which does not survive bundling. Vite
// emits the self-contained worker as a separate asset and supplies its final address.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import { useEffect, useRef, useState } from 'react';
import type { BasemapId, BasemapStyle } from '../../adapters/basemaps/basemap';
import { basemapById } from '../../adapters/basemaps/registry';
import { composeStyle, type OverlayStyle } from './compose-style';
import { FIXTURE_VIEW } from './fixtures';

setWorkerUrl(workerUrl);

export type BasemapState =
  | { kind: 'loading' }
  | { kind: 'ready' }
  | { kind: 'partial'; failedTiles: number }
  | { kind: 'unavailable'; reason: string };

interface MapViewProps {
  basemapId: BasemapId;
  overlays: OverlayStyle;
  onBasemapState: (state: BasemapState) => void;
}

// Colorado with a margin; the state basemap has no content beyond its borders.
const MAX_BOUNDS: [[number, number], [number, number]] = [
  [-112.5, 34.5],
  [-97.5, 43.5],
];

interface LoadedBasemap {
  id: BasemapId;
  style: BasemapStyle | null;
}

/**
 * Owns one MapLibre instance for the component's lifetime. The rendered style is always
 * rebuilt from the selected basemap and the current overlays, so switching or losing the
 * basemap never discards application layers.
 */
export function MapView({ basemapId, overlays, onBasemapState }: MapViewProps) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [loaded, setLoaded] = useState<LoadedBasemap | null>(null);
  const report = useRef(onBasemapState);
  const overlaysRef = useRef(overlays);
  // Tile failures for the current basemap; reset whenever a different basemap is applied.
  const tileFailures = useRef(0);
  const lastReport = useRef('');
  // The basemap most recently requested; an older one still on screen must not report ready.
  const requested = useRef(basemapId);

  useEffect(() => {
    report.current = onBasemapState;
  }, [onBasemapState]);

  // Stable for the component's lifetime: it reads only refs.
  const emit = useRef((state: BasemapState) => {
    const key = JSON.stringify(state);
    if (key === lastReport.current) return;
    lastReport.current = key;
    report.current(state);
  }).current;

  useEffect(() => {
    if (!container.current) return;
    const map = new MapLibreMap({
      container: container.current,
      style: composeStyle(null, overlaysRef.current),
      center: FIXTURE_VIEW.center,
      zoom: FIXTURE_VIEW.zoom,
      maxBounds: MAX_BOUNDS,
      dragRotate: false,
      pitchWithRotate: false,
      touchPitch: false,
      maxPitch: 0,
    });
    map.touchZoomRotate.disableRotation();
    map.keyboard.disableRotation();
    map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
    map.addControl(new ScaleControl({ unit: 'imperial', maxWidth: 120 }), 'bottom-left');
    map.on('error', (event: MapEventType['error']) => {
      const sourceId = (event as { sourceId?: unknown }).sourceId;
      if (typeof sourceId === 'string' && sourceId.startsWith('basemap')) tileFailures.current++;
      else console.warn('Map error', event.error);
    });
    mapRef.current = map;
    return () => {
      mapRef.current = null;
      map.remove();
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    requested.current = basemapId;
    lastReport.current = '';
    emit({ kind: 'loading' });
    basemapById(basemapId)
      .load(controller.signal)
      .then(
        (style) => setLoaded({ id: basemapId, style }),
        (error: unknown) => {
          if (controller.signal.aborted) return;
          setLoaded({ id: basemapId, style: null });
          emit({
            kind: 'unavailable',
            reason: error instanceof Error ? error.message : String(error),
          });
        },
      );
    return () => controller.abort();
  }, [basemapId, emit]);

  useEffect(() => {
    overlaysRef.current = overlays;
    const map = mapRef.current;
    if (!map) return;
    // A diff needs a fully loaded current style; otherwise rebuild without attempting one.
    map.setStyle(composeStyle(loaded?.style ?? null, overlays), {
      diff: map.isStyleLoaded() === true,
    });
    // An unchanged style draws nothing; request a frame so an idle event still follows.
    map.triggerRepaint();
  }, [loaded, overlays]);

  // Report the basemap ready, or partly failed, each time the map finishes loading tiles.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded || loaded.style === null) return;
    tileFailures.current = 0;
    const onIdle = () => {
      if (loaded.id !== requested.current) return;
      emit(
        tileFailures.current > 0
          ? { kind: 'partial', failedTiles: tileFailures.current }
          : { kind: 'ready' },
      );
    };
    map.on('idle', onIdle);
    return () => {
      map.off('idle', onIdle);
    };
  }, [loaded, emit]);

  return <div ref={container} className="map-canvas" data-testid="map" />;
}

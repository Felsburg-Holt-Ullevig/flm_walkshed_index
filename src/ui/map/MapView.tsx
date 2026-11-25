import {
  type GeoJSONSource,
  type MapEventType,
  type MapLayerMouseEvent,
  type MapLayerTouchEvent,
  Map as MapLibreMap,
  NavigationControl,
  ScaleControl,
  setWorkerUrl,
} from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
// MapLibre looks for its worker beside its own module, which does not survive bundling. Vite
// emits the self-contained worker as a separate asset and supplies its final address.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import { type RefObject, useEffect, useRef, useState } from 'react';
import type { BasemapId, BasemapStyle } from '../../adapters/basemaps/basemap';
import type { LabelPreset } from '../../adapters/basemaps/labels';
import { basemapById } from '../../adapters/basemaps/registry';
import type { Location } from '../../domain/locations';
import {
  LOCATION_MARKER_LAYER_ID,
  LOCATIONS_SOURCE_ID,
  locationsGeoJSON,
} from '../locations/overlay';
import { composeStyle, type OverlayStyle } from './compose-style';

setWorkerUrl(workerUrl);

export type BasemapState =
  | { kind: 'loading' }
  | { kind: 'ready' }
  | { kind: 'partial'; failedTiles: number }
  | { kind: 'unavailable'; reason: string };

interface MapViewProps {
  basemapId: BasemapId;
  labels: LabelPreset;
  overlays: OverlayStyle;
  onBasemapState: (state: BasemapState) => void;
  locations?: LocationInteraction;
  controller?: RefObject<MapController | null>;
}

export interface LocationInteraction {
  items: readonly Location[];
  selectedId: string | null;
  addMode: boolean;
  onAdd: (lng: number, lat: number) => void;
  onSelect: (id: string | null) => void;
  onMove: (id: string, lng: number, lat: number) => void;
}

export interface MapController {
  center: () => { lng: number; lat: number };
  flyTo: (lng: number, lat: number) => void;
}

/** Opening view: downtown Denver at a station-area scale. */
const INITIAL_VIEW = { center: [-105.0, 39.7535] as [number, number], zoom: 14 };

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
export function MapView({
  basemapId,
  labels,
  overlays,
  onBasemapState,
  locations,
  controller,
}: MapViewProps) {
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
      center: INITIAL_VIEW.center,
      zoom: INITIAL_VIEW.zoom,
      maxBounds: MAX_BOUNDS,
      dragRotate: false,
      pitchWithRotate: false,
      touchPitch: false,
      maxPitch: 0,
    });
    map.touchZoomRotate.disableRotation();
    map.keyboard.disableRotation();
    map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
    // Top left: the attribution line along the bottom wraps and would cover it.
    map.addControl(new ScaleControl({ unit: 'imperial', maxWidth: 120 }), 'top-left');
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
    if (!controller) return;
    controller.current = {
      center: () => {
        const center = mapRef.current?.getCenter();
        return {
          lng: center?.lng ?? INITIAL_VIEW.center[0],
          lat: center?.lat ?? INITIAL_VIEW.center[1],
        };
      },
      flyTo: (lng, lat) =>
        mapRef.current?.flyTo({ center: [lng, lat], zoom: Math.max(mapRef.current.getZoom(), 15) }),
    };
    return () => {
      controller.current = null;
    };
  }, [controller]);

  const interaction = useRef(locations);
  useEffect(() => {
    interaction.current = locations;
    const canvas = mapRef.current?.getCanvas();
    if (canvas) canvas.style.cursor = locations?.addMode ? 'crosshair' : '';
  }, [locations]);

  // Click to add or select; drag a marker to move it (committed once, on release).
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    let dragging: { id: string; moved: boolean } | null = null;
    // The click that follows a drag's release must not add or deselect.
    let suppressClick = false;
    const markerAt = (point: { x: number; y: number }): string | null => {
      if (!map.getLayer(LOCATION_MARKER_LAYER_ID)) return null;
      const id = map.queryRenderedFeatures([point.x, point.y], {
        layers: [LOCATION_MARKER_LAYER_ID],
      })[0]?.properties?.id;
      return typeof id === 'string' ? id : null;
    };
    const onClick = (event: MapLayerMouseEvent) => {
      const current = interaction.current;
      if (!current) return;
      if (suppressClick) {
        suppressClick = false;
        return;
      }
      const id = markerAt(event.point);
      if (id) current.onSelect(id);
      else if (current.addMode) current.onAdd(event.lngLat.lng, event.lngLat.lat);
      else current.onSelect(null);
    };
    const start = (event: MapLayerMouseEvent | MapLayerTouchEvent) => {
      if ('points' in event && event.points.length !== 1) return;
      const id = markerAt(event.point);
      if (!id || !interaction.current) return;
      event.preventDefault();
      dragging = { id, moved: false };
      suppressClick = false;
      map.getCanvas().style.cursor = 'grabbing';
    };
    const move = (event: MapLayerMouseEvent | MapLayerTouchEvent) => {
      const current = interaction.current;
      if (!dragging || !current) return;
      dragging.moved = true;
      const items = current.items.map((item) =>
        item.id === dragging?.id ? { ...item, lng: event.lngLat.lng, lat: event.lngLat.lat } : item,
      );
      (map.getSource(LOCATIONS_SOURCE_ID) as GeoJSONSource | undefined)?.setData(
        locationsGeoJSON(items, dragging.id),
      );
    };
    const end = (event: MapLayerMouseEvent | MapLayerTouchEvent) => {
      const current = interaction.current;
      if (!dragging || !current) return;
      const { id, moved } = dragging;
      dragging = null;
      suppressClick = moved;
      map.getCanvas().style.cursor = current.addMode ? 'crosshair' : '';
      current.onSelect(id);
      if (moved) current.onMove(id, event.lngLat.lng, event.lngLat.lat);
    };
    const hover = (event: MapLayerMouseEvent) => {
      if (dragging) return;
      const over = markerAt(event.point) !== null;
      map.getCanvas().style.cursor = over
        ? 'grab'
        : interaction.current?.addMode
          ? 'crosshair'
          : '';
    };
    map.on('click', onClick);
    map.on('mousedown', start);
    map.on('touchstart', start);
    map.on('mousemove', move);
    map.on('touchmove', move);
    map.on('mouseup', end);
    map.on('touchend', end);
    map.on('mousemove', hover);
    return () => {
      map.off('click', onClick);
      map.off('mousedown', start);
      map.off('touchstart', start);
      map.off('mousemove', move);
      map.off('touchmove', move);
      map.off('mouseup', end);
      map.off('touchend', end);
      map.off('mousemove', hover);
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    requested.current = basemapId;
    lastReport.current = '';
    emit({ kind: 'loading' });
    basemapById(basemapId)
      .load(controller.signal, { labels })
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
  }, [basemapId, labels, emit]);

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

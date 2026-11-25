import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from 'react';
import type { BasemapId } from '../../adapters/basemaps/basemap';
import {
  BASEMAPS,
  basemapById,
  basemapFromAddress,
  basemapParam,
  labelsFromAddress,
  localGlyphsUrl,
  prefetchBasemap,
} from '../../adapters/basemaps/registry';
import { loadLocations, saveLocations } from '../../adapters/storage/locations-store';
import {
  initialState,
  type Location,
  locationsReducer,
  MAX_LOCATIONS,
  redoChange,
  undoChange,
} from '../../domain/locations';
import { LocationsPanel } from '../locations/LocationsPanel';
import { locationsOverlay } from '../locations/overlay';
import type { BasemapState, LocationInteraction, MapController } from '../map/MapView';

// The map engine is the largest dependency; loading it separately lets the page shell render first.
const MapView = lazy(() =>
  import('../map/MapView').then((module) => ({ default: module.MapView })),
);

function statusMessage(id: BasemapId, state: BasemapState): string {
  const basemap = basemapById(id);
  switch (state.kind) {
    case 'loading':
      return id === 'oit-raster'
        ? 'Loading basemap images. The state map server can take up to a minute in dense areas.'
        : 'Loading basemap.';
    case 'ready':
      return id === 'none' ? 'No basemap selected.' : `Basemap style loaded: ${basemap.label}.`;
    case 'partial':
      return `${state.failedTiles} basemap ${state.failedTiles === 1 ? 'tile' : 'tiles'} did not load. Locations still display.`;
    case 'unavailable':
      return `Basemap unavailable (${state.reason}). Locations still display.`;
  }
}

/** Records a choice in the address so the current view can be shared as a link. */
function setAddressParam(name: string, value: string | null): void {
  const url = new URL(window.location.href);
  if (value === null) url.searchParams.delete(name);
  else url.searchParams.set(name, value);
  window.history.replaceState(null, '', url);
}

// Matches the stacked layout breakpoint in styles.css.
const NARROW_QUERY = '(max-width: 48rem)';

const isNarrow = () => window.matchMedia(NARROW_QUERY).matches;

function isTextField(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable ||
      target instanceof HTMLTextAreaElement ||
      (target instanceof HTMLInputElement &&
        !['checkbox', 'radio', 'button'].includes(target.type)))
  );
}

interface Notice {
  text: string;
  undo?: boolean;
}

export function AppShell() {
  const [startOpen] = useState(() => !isNarrow());
  // Starts from the address (e.g. ?basemap=dark) so a chosen look can be shared as a link.
  const [basemapId, setBasemapId] = useState(() => basemapFromAddress(window.location.search));
  const [labels, setLabels] = useState(() => labelsFromAddress(window.location.search));
  const [notice, setNotice] = useState<Notice | null>(null);
  const chooseBasemap = useCallback((id: BasemapId) => {
    setBasemapId(id);
    setNotice(null);
    setAddressParam('basemap', basemapParam(id));
  }, []);
  const chooseLabels = useCallback((walkshed: boolean) => {
    setLabels(walkshed ? 'walkshed' : 'original');
    setAddressParam('labels', walkshed ? null : 'original');
  }, []);
  // Starts the slow style request during the first render, before the lazily loaded map engine
  // arrives. A state initializer is used because it runs exactly once per mount, during render,
  // which is earlier than an effect; prefetchBasemap ignores repeat calls (as in Strict Mode).
  useState(() => prefetchBasemap(basemapId));
  const [basemapState, setBasemapState] = useState<BasemapState>({ kind: 'loading' });
  const onBasemapState = useCallback((state: BasemapState) => setBasemapState(state), []);

  const [history, dispatch] = useReducer(locationsReducer, undefined, () =>
    initialState(loadLocations() ?? undefined),
  );
  const locations = history.present.locations;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [addMode, setAddMode] = useState(false);
  const controller = useRef<MapController | null>(null);
  const [saved, setSaved] = useState(true);

  useEffect(() => setSaved(saveLocations(history.present)), [history.present]);
  useEffect(() => {
    if (selectedId && !locations.some((location) => location.id === selectedId))
      setSelectedId(null);
  }, [locations, selectedId]);
  useEffect(() => {
    if (addMode && locations.length >= MAX_LOCATIONS) setAddMode(false);
  }, [addMode, locations.length]);

  const add = useCallback((lng: number, lat: number) => {
    const id = crypto.randomUUID();
    dispatch({ type: 'add', id, lng, lat });
    setSelectedId(id);
    setNotice(null);
  }, []);
  const undo = useCallback(() => {
    dispatch({ type: 'undo' });
    setNotice(null);
  }, []);
  const redo = useCallback(() => {
    dispatch({ type: 'redo' });
    setNotice(null);
  }, []);
  const toggleAddMode = useCallback(() => {
    setAddMode((on) => {
      if (!on && isNarrow())
        document.querySelector('.map-area')?.scrollIntoView({ block: 'nearest' });
      return !on;
    });
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && addMode) {
        setAddMode(false);
        return;
      }
      if (!(event.ctrlKey || event.metaKey) || isTextField(event.target)) return;
      const key = event.key.toLowerCase();
      if (key === 'z' && !event.shiftKey) undo();
      else if ((key === 'z' && event.shiftKey) || key === 'y') redo();
      else return;
      event.preventDefault();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [addMode, undo, redo]);

  const glyphs = useMemo(() => localGlyphsUrl(), []);
  const overlays = useMemo(
    () => locationsOverlay(locations, selectedId, glyphs),
    [locations, selectedId, glyphs],
  );
  const interaction = useMemo<LocationInteraction>(
    () => ({
      items: locations,
      selectedId,
      addMode,
      onAdd: add,
      onSelect: setSelectedId,
      onMove: (id, lng, lat) => dispatch({ type: 'move', id, lng, lat }),
    }),
    [locations, selectedId, addMode, add],
  );

  const shownNotice: Notice | null = addMode
    ? { text: 'Click the map to add a location. Press Esc to stop.' }
    : notice;

  return (
    <div className="app">
      <a className="skip-link" href="#panel">
        Skip to locations
      </a>
      <header className="app-header">
        <h1>FLM Walkshed Index</h1>
        <p className="app-tag">Development prototype</p>
      </header>
      <main className="app-body">
        <aside id="panel" className="panel" aria-label="Locations and map options" tabIndex={-1}>
          <LocationsPanel
            locations={locations}
            selectedId={selectedId}
            addMode={addMode}
            undoChange={undoChange(history)}
            redoChange={redoChange(history)}
            onToggleAddMode={toggleAddMode}
            onAddAtCentre={() => {
              const centre = controller.current?.center();
              if (centre) add(centre.lng, centre.lat);
            }}
            onSelect={setSelectedId}
            onZoomTo={(location: Location) => controller.current?.flyTo(location.lng, location.lat)}
            onEdit={(id, name, lng, lat) => dispatch({ type: 'edit', id, name, lng, lat })}
            onRemove={(id) => dispatch({ type: 'remove', id })}
            onUndo={undo}
            onRedo={redo}
            onClear={() => {
              const count = locations.length;
              dispatch({ type: 'clear' });
              setAddMode(false);
              setNotice({
                text: `Cleared ${count} ${count === 1 ? 'location' : 'locations'}.`,
                undo: true,
              });
            }}
          />
          {!saved && (
            <p className="hint panel-content">
              Browser storage is unavailable; locations will not be kept after reload.
            </p>
          )}
          {/* Narrow screens stack the panel above the map, so the options start collapsed there. */}
          <details className="panel-options" open={startOpen}>
            <summary>Map options</summary>
            <fieldset className="basemap-choice">
              <legend>Basemap style</legend>
              {BASEMAPS.map((basemap) => (
                <label key={basemap.id} className="radio">
                  <input
                    type="radio"
                    name="basemap"
                    value={basemap.id}
                    checked={basemap.id === basemapId}
                    onChange={() => chooseBasemap(basemap.id)}
                  />
                  <span>{basemap.label}</span>
                </label>
              ))}
            </fieldset>
            <div className="panel-content">
              <label className="check">
                <input
                  type="checkbox"
                  checked={labels === 'walkshed'}
                  onChange={(event) => chooseLabels(event.currentTarget.checked)}
                />
                <span>Walkshed labels</span>
              </label>
            </div>
          </details>
          <p className="build panel-content">Build {__APP_COMMIT__}</p>
        </aside>
        {/* MapLibre labels its canvas as the "Map" region, so this wrapper adds no landmark. */}
        <div className="map-area" data-basemap={basemapId} data-basemap-state={basemapState.kind}>
          <Suspense fallback={null}>
            <MapView
              basemapId={basemapId}
              labels={labels}
              overlays={overlays}
              onBasemapState={onBasemapState}
              locations={interaction}
              controller={controller}
            />
          </Suspense>
          <div
            role="status"
            className="map-status"
            data-kind={shownNotice ? 'notice' : basemapState.kind}
          >
            {shownNotice ? (
              <>
                {shownNotice.text}
                {shownNotice.undo && (
                  <button type="button" className="notice-action" onClick={undo}>
                    Undo
                  </button>
                )}
              </>
            ) : (
              statusMessage(basemapId, basemapState)
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

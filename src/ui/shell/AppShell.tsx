import { lazy, Suspense, useCallback, useState } from 'react';
import type { BasemapId } from '../../adapters/basemaps/basemap';
import {
  BASEMAPS,
  basemapById,
  basemapFromAddress,
  basemapParam,
  labelsFromAddress,
  prefetchBasemap,
} from '../../adapters/basemaps/registry';
import { NO_OVERLAYS } from '../map/compose-style';
import type { BasemapState } from '../map/MapView';

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
      return `${state.failedTiles} basemap ${state.failedTiles === 1 ? 'tile' : 'tiles'} did not load. Stations and walksheds still display.`;
    case 'unavailable':
      return `Basemap unavailable (${state.reason}). Stations and walksheds still display.`;
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

export function AppShell() {
  const [startOpen] = useState(() => !window.matchMedia(NARROW_QUERY).matches);
  // Starts from the address (e.g. ?basemap=dark) so a chosen look can be shared as a link.
  const [basemapId, setBasemapId] = useState(() => basemapFromAddress(window.location.search));
  const [labels, setLabels] = useState(() => labelsFromAddress(window.location.search));
  const chooseBasemap = useCallback((id: BasemapId) => {
    setBasemapId(id);
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

  return (
    <div className="app">
      <a className="skip-link" href="#panel">
        Skip to map options
      </a>
      <header className="app-header">
        <h1>FLM Walkshed Index</h1>
        <p className="app-tag">Development prototype</p>
      </header>
      <main className="app-body">
        <aside id="panel" className="panel" aria-label="Map options" tabIndex={-1}>
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
                  <span>
                    <span className="radio-label">{basemap.label}</span>
                    <span className="radio-description">{basemap.description}</span>
                  </span>
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
                <span>
                  <span className="radio-label">Walkshed labels</span>
                  <span className="radio-description">
                    Street and trail names from zoom 14, bolder major roads, fewer repeats and
                    regional names hidden when zoomed in. Clear to compare with the state style's
                    labels.
                  </span>
                </span>
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
              overlays={NO_OVERLAYS}
              onBasemapState={onBasemapState}
            />
          </Suspense>
          <p role="status" className="map-status" data-kind={basemapState.kind}>
            {statusMessage(basemapId, basemapState)}
          </p>
        </div>
      </main>
    </div>
  );
}

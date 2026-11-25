import { lazy, Suspense, useCallback, useMemo, useState } from 'react';
import type { BasemapId } from '../../adapters/basemaps/basemap';
import { BASEMAPS, basemapById, DEFAULT_BASEMAP_ID } from '../../adapters/basemaps/registry';
import { FIXTURE_WALKSHEDS } from '../map/fixtures';
import type { BasemapState } from '../map/MapView';
import { buildOverlays, WALKSHED_STYLE } from '../map/overlays';
import { PanelSection } from './PanelSection';

// The map engine is the largest dependency; loading it separately lets the panel render first.
const MapView = lazy(() =>
  import('../map/MapView').then((module) => ({ default: module.MapView })),
);

// Matches the stacked layout breakpoint in styles.css.
const NARROW_QUERY = '(max-width: 48rem)';

function statusMessage(id: BasemapId, state: BasemapState): string {
  const basemap = basemapById(id);
  switch (state.kind) {
    case 'loading':
      return id === 'oit-raster'
        ? 'Loading basemap images. The state map server can take up to a minute in dense areas.'
        : 'Loading basemap.';
    case 'ready':
      return id === 'none' ? 'No basemap selected.' : `Basemap loaded: ${basemap.label}.`;
    case 'partial':
      return `${state.failedTiles} basemap ${state.failedTiles === 1 ? 'tile' : 'tiles'} did not load. Stations and walksheds still display.`;
    case 'unavailable':
      return `Basemap unavailable (${state.reason}). Stations and walksheds still display. Choose another basemap under Map display.`;
  }
}

export function AppShell() {
  // Narrow screens stack the panel above the map, so it starts closed to keep the map in view.
  const [panelOpen, setPanelOpen] = useState(() => !window.matchMedia(NARROW_QUERY).matches);
  const [basemapId, setBasemapId] = useState<BasemapId>(DEFAULT_BASEMAP_ID);
  const [basemapState, setBasemapState] = useState<BasemapState>({ kind: 'loading' });
  const [fixturesVisible, setFixturesVisible] = useState(true);
  const overlays = useMemo(() => buildOverlays({ fixturesVisible }), [fixturesVisible]);
  const onBasemapState = useCallback((state: BasemapState) => setBasemapState(state), []);
  const host = basemapById(basemapId).host;

  return (
    <div className="app">
      <a className="skip-link" href="#panel">
        Skip to analysis panel
      </a>
      <header className="app-header">
        <h1>FLM Walkshed Index</h1>
        <p className="app-tag">Development prototype</p>
      </header>
      <main className="app-body" data-panel={panelOpen ? 'open' : 'closed'}>
        <aside id="panel" className="panel" aria-labelledby="panel-title" tabIndex={-1}>
          <div className="panel-head">
            <h2 id="panel-title">Analysis</h2>
            <button
              type="button"
              className="panel-toggle"
              aria-expanded={panelOpen}
              aria-controls="panel-content"
              onClick={() => setPanelOpen((open) => !open)}
            >
              {panelOpen ? 'Hide panel' : 'Show panel'}
            </button>
          </div>
          <div id="panel-content" className="panel-content" hidden={!panelOpen}>
            <PanelSection title="Stations" status="Not yet available">
              Add stations by clicking the map, entering latitude and longitude, or importing a
              file. Stations will also be listed here for keyboard and screen-reader access.
            </PanelSection>
            <PanelSection title="Walksheds" status="Not yet available">
              <p>Walkshed generation will run only when you request it.</p>
              <label className="check">
                <input
                  type="checkbox"
                  checked={fixturesVisible}
                  onChange={(event) => setFixturesVisible(event.target.checked)}
                />
                Show illustrative fixture shapes
              </label>
              <ul className="legend" aria-label="Fixture shapes">
                {FIXTURE_WALKSHEDS.map((walkshed) => (
                  <li key={walkshed.id}>
                    <span
                      className="swatch"
                      data-dashed={WALKSHED_STYLE[walkshed.id].dashed}
                      style={{ borderColor: WALKSHED_STYLE[walkshed.id].color }}
                      aria-hidden="true"
                    />
                    {walkshed.label} ({WALKSHED_STYLE[walkshed.id].dashed ? 'dashed' : 'solid'}{' '}
                    outline)
                  </li>
                ))}
              </ul>
              <p className="note">
                These are fixed example shapes for testing map display. They are not walkshed
                analysis results.
              </p>
            </PanelSection>
            <PanelSection title="Index analysis" status="Not yet available">
              Demographic, safety, transit and access indicators for each station.
            </PanelSection>
            <PanelSection title="Results and exports" status="Not yet available">
              Station tables, maps and spatial files.
            </PanelSection>
            <PanelSection title="Map display">
              <fieldset className="basemap-choice">
                <legend>Basemap</legend>
                {BASEMAPS.map((basemap) => (
                  <label key={basemap.id} className="radio">
                    <input
                      type="radio"
                      name="basemap"
                      value={basemap.id}
                      checked={basemapId === basemap.id}
                      onChange={() => setBasemapId(basemap.id)}
                    />
                    <span>
                      <span className="radio-label">{basemap.label}</span>
                      <span className="radio-description">{basemap.description}</span>
                    </span>
                  </label>
                ))}
              </fieldset>
              <p className="note">
                {host ? `Basemap requests go to ${host}.` : 'No basemap requests are made.'} To move
                the map with a keyboard, select it and use the arrow keys; use + and − to zoom.
              </p>
            </PanelSection>
            <p className="build">Build {__APP_COMMIT__}</p>
          </div>
        </aside>
        {/* MapLibre labels its canvas as the "Map" region, so this wrapper adds no landmark. */}
        <div className="map-area" data-basemap={basemapId} data-basemap-state={basemapState.kind}>
          <Suspense fallback={null}>
            <MapView basemapId={basemapId} overlays={overlays} onBasemapState={onBasemapState} />
          </Suspense>
          <p role="status" className="map-status" data-kind={basemapState.kind}>
            {statusMessage(basemapId, basemapState)}
          </p>
        </div>
      </main>
    </div>
  );
}

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { CACHED_BASEMAP_HOST } from './adapters/basemaps/registry';
import { App } from './ui/App';
import './ui/styles.css';

const root = document.getElementById('root');
if (!root) throw new Error('Application root element is missing.');

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// Caches basemap responses between visits (see public/sw.js). Development builds skip it so
// edits and network stubs are never hidden behind cached responses.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  const url = `${import.meta.env.BASE_URL}sw.js?host=${encodeURIComponent(CACHED_BASEMAP_HOST)}`;
  navigator.serviceWorker
    .register(url, { scope: import.meta.env.BASE_URL })
    .catch((error: unknown) => console.warn('Basemap cache unavailable', error));
}

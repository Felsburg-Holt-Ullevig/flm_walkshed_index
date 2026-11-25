/*
 * Basemap cache. The state tile service marks every response `max-age=0, must-revalidate`, so
 * without this a return visit waits on a round trip for the style, sprites and every tile. Basemap
 * responses are answered from this cache at once and refreshed from the network in the
 * background (stale-while-revalidate); the next visit sees the refreshed copy.
 *
 * Only GET requests to the basemap host given at registration (`?host=`) are handled. Everything
 * else, including the application's own files, goes to the network as usual.
 */
const CACHE_PREFIX = 'basemap-';
const CACHE_NAME = `${CACHE_PREFIX}v1`;
// Roughly 10-30 MB of vector tiles; the oldest entries are removed beyond this.
const MAX_ENTRIES = 3000;
// Entries older than this are not served; they are fetched again as on a first visit.
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
const STORED_AT = 'x-basemap-cached-at';

const basemapHost = new URL(self.location.href).searchParams.get('host');

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      for (const name of await caches.keys())
        if (name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME) await caches.delete(name);
      await self.clients.claim();
    })(),
  );
});

async function store(cache, request, response) {
  if (response.status !== 200 || response.type === 'opaque') return;
  const headers = new Headers(response.headers);
  headers.set(STORED_AT, String(Date.now()));
  const body = await response.blob();
  await cache.delete(request);
  await cache.put(request, new Response(body, { status: 200, headers }));
}

async function trim(cache) {
  const keys = await cache.keys();
  for (const key of keys.slice(0, Math.max(0, keys.length - MAX_ENTRIES))) await cache.delete(key);
}

async function refresh(cache, request) {
  const response = await fetch(request);
  await store(cache, request, response.clone());
  await trim(cache);
  return response;
}

async function respond(event) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(event.request);
  const fresh = cached && Date.now() - Number(cached.headers.get(STORED_AT)) < MAX_AGE_MS;
  if (fresh) {
    event.waitUntil(refresh(cache, event.request).catch(() => {}));
    return cached;
  }
  try {
    return await refresh(cache, event.request);
  } catch (error) {
    // Offline or the service failed: an expired copy is better than no basemap.
    if (cached) return cached;
    throw error;
  }
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET' || !basemapHost) return;
  if (new URL(request.url).host !== basemapHost) return;
  event.respondWith(respond(event));
});

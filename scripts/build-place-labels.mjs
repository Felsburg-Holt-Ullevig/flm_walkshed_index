/**
 * Builds public/data/place-labels.geojson: one label point per Colorado municipality,
 * census-designated place and Denver statistical neighbourhood, with the attributes the label
 * hierarchy needs. Sources and licences are recorded in public/data/README.md.
 *
 * Usage: node scripts/build-place-labels.mjs
 */
import { writeFile } from 'node:fs/promises';

const TIGER =
  'https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Census2020/MapServer';
const INCORPORATED = 26;
const CENSUS_DESIGNATED = 28;
const DENVER_NEIGHBORHOODS =
  'https://services1.arcgis.com/zdB7qR0BtYrg0Xpl/arcgis/rest/services/ODC_ADMN_NEIGHBORHOOD_A/FeatureServer/13';
const GNIS = 'https://carto.nationalmap.gov/arcgis/rest/services/geonames/MapServer/3';
const OUTPUT = 'public/data/place-labels.geojson';

/**
 * Each label has a `kind` (municipality, community for a census-designated place, or
 * neighborhood) and a population `tier`: 1 for 100,000 or more, 2 for 25,000 or more, 3 otherwise.
 * Kind sets the lettering; tier sets size and the zoom at which the label appears.
 */
function tier(population) {
  if (population >= 100_000) return 1;
  if (population >= 25_000) return 2;
  return 3;
}

async function getJson(url, attempts = 4) {
  let response;
  for (let attempt = 1; ; attempt++) {
    try {
      response = await fetch(url);
      break;
    } catch (error) {
      // The census server intermittently refuses connections; wait and retry.
      if (attempt >= attempts) throw error;
      await new Promise((resolve) => setTimeout(resolve, 2000 * attempt));
    }
  }
  if (!response.ok) throw Error(`HTTP ${response.status} for ${url}`);
  const body = await response.json();
  if (body.error) throw Error(`${url}: ${JSON.stringify(body.error)}`);
  return body;
}

async function tigerPlaces(layer) {
  const fields = 'GEOID,BASENAME,LSADC,POP100,INTPTLAT,INTPTLON';
  const body = await getJson(
    `${TIGER}/${layer}/query?where=STATE%3D%2708%27&outFields=${fields}&returnGeometry=false&f=json`,
  );
  if (body.exceededTransferLimit) throw Error(`TIGER layer ${layer} returned a partial result`);
  return body.features.map((feature) => feature.attributes);
}

/**
 * USGS GNIS populated-place points. The Census internal point is only guaranteed to fall inside a
 * place, which for large or irregular cities can be far from the centre (Denver's lies near the
 * airport arm, Aurora's on its eastern plains). GNIS records the conventional location of each
 * place, usually its historic centre; its first point is the primary one.
 */
async function gnisPlaces() {
  const places = [];
  for (let offset = 0; ; offset += 1000) {
    const body = await getJson(
      `${GNIS}/query?where=state_alpha%3D%27CO%27&outFields=gaz_name&returnGeometry=true&outSR=4326&f=json&resultOffset=${offset}&resultRecordCount=1000&orderByFields=OBJECTID`,
    );
    for (const { attributes, geometry } of body.features) {
      const first = geometry?.points?.[0] ?? (geometry ? [geometry.x, geometry.y] : null);
      if (first) places.push({ name: attributes.gaz_name, lon: first[0], lat: first[1] });
    }
    if (!body.exceededTransferLimit) return places;
  }
}

const gnis = Object.groupBy(await gnisPlaces(), (place) => place.name.toLowerCase());
/** Furthest a GNIS point may be from the Census point and still be taken as the same place. */
const MAX_MATCH_KM = 40;
const km = (a, b) => Math.hypot((a.lon - b.lon) * 85.3, (a.lat - b.lat) * 111.0); // degrees to km at 39.5°N
let fromGnis = 0;

/** The GNIS point for a Census place with the same name, nearest the Census point; else that point. */
function labelPoint(place) {
  const census = { lon: Number(place.INTPTLON), lat: Number(place.INTPTLAT) };
  const candidates = gnis[place.BASENAME.toLowerCase()] ?? [];
  let best = null;
  for (const candidate of candidates)
    if (
      km(candidate, census) <= MAX_MATCH_KM &&
      (!best || km(candidate, census) < km(best, census))
    )
      best = candidate;
  if (best) fromGnis++;
  return best ?? census;
}

const round = (value) => Math.round(Number(value) * 1e5) / 1e5;
const point = (lon, lat, properties) => ({
  type: 'Feature',
  geometry: { type: 'Point', coordinates: [round(lon), round(lat)] },
  properties,
});

const features = [];
for (const place of await tigerPlaces(INCORPORATED)) {
  const { lon, lat } = labelPoint(place);
  features.push(
    point(lon, lat, {
      name: place.BASENAME,
      kind: 'municipality',
      tier: tier(place.POP100),
      population: place.POP100,
      source: `census:${place.GEOID}`,
    }),
  );
}
for (const place of await tigerPlaces(CENSUS_DESIGNATED)) {
  const { lon, lat } = labelPoint(place);
  features.push(
    point(lon, lat, {
      name: place.BASENAME,
      kind: 'community',
      tier: tier(place.POP100),
      population: place.POP100,
      source: `census:${place.GEOID}`,
    }),
  );
}

const neighborhoods = await getJson(
  `${DENVER_NEIGHBORHOODS}/query?where=1%3D1&outFields=NBHD_ID,NBHD_NAME&returnGeometry=false&returnCentroid=true&outSR=4326&f=json`,
);
for (const { attributes, centroid } of neighborhoods.features) {
  if (!centroid) throw Error(`Neighbourhood ${attributes.NBHD_NAME} has no label point`);
  features.push(
    point(centroid.x, centroid.y, {
      name: attributes.NBHD_NAME,
      kind: 'neighborhood',
      tier: 3,
      source: `denver:${attributes.NBHD_ID}`,
    }),
  );
}

// Larger places first, so ties in collision placement favour them.
features.sort((a, b) => (b.properties.population ?? 0) - (a.properties.population ?? 0));
const counts = Object.groupBy(
  features,
  ({ properties }) => `${properties.kind} tier ${properties.tier}`,
);
await writeFile(OUTPUT, `${JSON.stringify({ type: 'FeatureCollection', features })}\n`);
console.log(
  `Wrote ${features.length} labels to ${OUTPUT} (${fromGnis} Census places at GNIS points):`,
  Object.entries(counts)
    .map(([group, list]) => `${group}: ${list.length}`)
    .join(', '),
);

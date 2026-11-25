/**
 * Fixed example shapes used to test how overlapping walksheds display over a basemap. They are
 * hand-drawn outlines near Denver Union Station, not network walksheds or analysis results, and
 * the interface labels them as illustrative.
 */
export interface FixtureWalkshed {
  id: 'A' | 'B';
  label: string;
  station: [number, number];
  /** Closed exterior ring, longitude/latitude in degrees (WGS 84). */
  ring: [number, number][];
}

// Irregular outlines are generated deterministically so the shapes do not look like buffers.
function outline(
  center: [number, number],
  radiusDeg: number,
  wobble: number[],
): [number, number][] {
  const [lon, lat] = center;
  const lonScale = 1 / Math.cos((lat * Math.PI) / 180);
  const points: [number, number][] = [];
  const steps = 64;
  for (let i = 0; i < steps; i++) {
    const t = (i / steps) * 2 * Math.PI;
    const r =
      radiusDeg *
      wobble.reduce((sum, amplitude, k) => sum + amplitude * Math.sin((k + 2) * t + k), 1);
    points.push([
      Number((lon + r * lonScale * Math.cos(t)).toFixed(6)),
      Number((lat + r * Math.sin(t)).toFixed(6)),
    ]);
  }
  points.push(points[0] as [number, number]);
  return points;
}

const STATION_A: [number, number] = [-105.0045, 39.753];
const STATION_B: [number, number] = [-104.9958, 39.754];

export const FIXTURE_WALKSHEDS: readonly FixtureWalkshed[] = [
  {
    id: 'A',
    label: 'Illustrative fixture A',
    station: STATION_A,
    ring: outline(STATION_A, 0.0058, [0.12, -0.06, 0.04]),
  },
  {
    id: 'B',
    label: 'Illustrative fixture B',
    station: STATION_B,
    ring: outline(STATION_B, 0.0052, [-0.09, 0.08, -0.05]),
  },
];

/** View that frames both fixtures. */
export const FIXTURE_VIEW = { center: [-105.0, 39.7535] as [number, number], zoom: 14 };

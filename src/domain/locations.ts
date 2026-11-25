/** User-placed locations with undo history. Pure: no React, DOM, map or storage access. */

export const MAX_LOCATIONS = 100;
export const MAX_HISTORY = 50;

/** Matches the map's movement limits (Colorado with a margin). */
export const LOCATION_BOUNDS = { west: -112.5, south: 34.5, east: -97.5, north: 43.5 } as const;

export interface Location {
  id: string;
  name: string;
  /** WGS 84 decimal degrees. */
  lng: number;
  lat: number;
}

export interface LocationSet {
  locations: Location[];
  /** Number used for the next default name; never reused, so names stay distinct. */
  nextNumber: number;
}

interface HistoryEntry {
  set: LocationSet;
  /** The change between this entry and the next state, e.g. "delete Location 2". */
  change: string;
}

export interface LocationsState {
  present: LocationSet;
  past: HistoryEntry[];
  future: HistoryEntry[];
}

export type LocationsAction =
  | { type: 'add'; id: string; lng: number; lat: number }
  | { type: 'move'; id: string; lng: number; lat: number }
  | { type: 'edit'; id: string; name: string; lng: number; lat: number }
  | { type: 'remove'; id: string }
  | { type: 'clear' }
  | { type: 'undo' }
  | { type: 'redo' };

export const EMPTY_SET: LocationSet = { locations: [], nextNumber: 1 };

export function initialState(set: LocationSet = EMPTY_SET): LocationsState {
  return { present: set, past: [], future: [] };
}

export function inBounds(lng: number, lat: number): boolean {
  return (
    Number.isFinite(lng) &&
    Number.isFinite(lat) &&
    lng >= LOCATION_BOUNDS.west &&
    lng <= LOCATION_BOUNDS.east &&
    lat >= LOCATION_BOUNDS.south &&
    lat <= LOCATION_BOUNDS.north
  );
}

function commit(state: LocationsState, set: LocationSet, change: string): LocationsState {
  const past = [...state.past, { set: state.present, change }].slice(-MAX_HISTORY);
  return { present: set, past, future: [] };
}

function nameOf(set: LocationSet, id: string): string | undefined {
  return set.locations.find((location) => location.id === id)?.name;
}

export function locationsReducer(state: LocationsState, action: LocationsAction): LocationsState {
  const { present } = state;
  switch (action.type) {
    case 'add': {
      if (present.locations.length >= MAX_LOCATIONS || !inBounds(action.lng, action.lat))
        return state;
      if (nameOf(present, action.id) !== undefined) return state;
      const name = `Location ${present.nextNumber}`;
      return commit(
        state,
        {
          locations: [
            ...present.locations,
            { id: action.id, name, lng: action.lng, lat: action.lat },
          ],
          nextNumber: present.nextNumber + 1,
        },
        `add ${name}`,
      );
    }
    case 'move': {
      const name = nameOf(present, action.id);
      if (name === undefined || !inBounds(action.lng, action.lat)) return state;
      return commit(
        state,
        {
          ...present,
          locations: present.locations.map((location) =>
            location.id === action.id
              ? { ...location, lng: action.lng, lat: action.lat }
              : location,
          ),
        },
        `move ${name}`,
      );
    }
    case 'edit': {
      const name = nameOf(present, action.id);
      const next = action.name.trim();
      if (name === undefined || next === '' || !inBounds(action.lng, action.lat)) return state;
      const current = present.locations.find((l) => l.id === action.id);
      if (current?.name === next && current.lng === action.lng && current.lat === action.lat)
        return state;
      return commit(
        state,
        {
          ...present,
          locations: present.locations.map((location) =>
            location.id === action.id
              ? { ...location, name: next, lng: action.lng, lat: action.lat }
              : location,
          ),
        },
        `edit ${name}`,
      );
    }
    case 'remove': {
      const name = nameOf(present, action.id);
      if (name === undefined) return state;
      return commit(
        state,
        { ...present, locations: present.locations.filter((l) => l.id !== action.id) },
        `delete ${name}`,
      );
    }
    case 'clear':
      if (present.locations.length === 0) return state;
      return commit(state, { ...present, locations: [] }, 'clear all locations');
    case 'undo': {
      const entry = state.past.at(-1);
      if (!entry) return state;
      return {
        present: entry.set,
        past: state.past.slice(0, -1),
        future: [{ set: present, change: entry.change }, ...state.future],
      };
    }
    case 'redo': {
      const entry = state.future[0];
      if (!entry) return state;
      return {
        present: entry.set,
        past: [...state.past, { set: present, change: entry.change }],
        future: state.future.slice(1),
      };
    }
  }
}

export const undoChange = (state: LocationsState) => state.past.at(-1)?.change;
export const redoChange = (state: LocationsState) => state.future[0]?.change;

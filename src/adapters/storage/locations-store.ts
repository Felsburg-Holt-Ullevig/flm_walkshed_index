import { inBounds, type LocationSet, MAX_LOCATIONS } from '../../domain/locations';

/** Browser storage for the user's locations. Undo history is not kept across reloads. */
export const LOCATIONS_STORAGE_KEY = 'flm-walkshed-index:locations';
export const LOCATIONS_FORMAT_VERSION = 1;

const MAX_NAME_LENGTH = 200;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Validates a stored document; returns null for anything unreadable or of another version. */
export function parseStoredLocations(text: string | null): LocationSet | null {
  if (text === null) return null;
  let doc: unknown;
  try {
    doc = JSON.parse(text);
  } catch {
    return null;
  }
  if (!isRecord(doc) || doc.version !== LOCATIONS_FORMAT_VERSION) return null;
  const { locations, nextNumber } = doc;
  if (!Array.isArray(locations) || locations.length > MAX_LOCATIONS) return null;
  if (typeof nextNumber !== 'number' || !Number.isSafeInteger(nextNumber) || nextNumber < 1)
    return null;
  const ids = new Set<string>();
  const result: LocationSet = { locations: [], nextNumber };
  for (const item of locations) {
    if (!isRecord(item)) return null;
    const { id, name, lng, lat } = item;
    if (typeof id !== 'string' || id === '' || ids.has(id)) return null;
    if (typeof name !== 'string' || name.trim() === '' || name.length > MAX_NAME_LENGTH)
      return null;
    if (typeof lng !== 'number' || typeof lat !== 'number' || !inBounds(lng, lat)) return null;
    ids.add(id);
    result.locations.push({ id, name, lng, lat });
  }
  return result;
}

export function serializeLocations(set: LocationSet): string {
  return JSON.stringify({ version: LOCATIONS_FORMAT_VERSION, ...set });
}

// Storage can be unavailable (private browsing, blocked site data); the app then works unsaved.
export function loadLocations(
  storage: Storage | undefined = globalThis.localStorage,
): LocationSet | null {
  try {
    return parseStoredLocations(storage?.getItem(LOCATIONS_STORAGE_KEY) ?? null);
  } catch {
    return null;
  }
}

export function saveLocations(
  set: LocationSet,
  storage: Storage | undefined = globalThis.localStorage,
): boolean {
  try {
    storage?.setItem(LOCATIONS_STORAGE_KEY, serializeLocations(set));
    return storage !== undefined;
  } catch {
    return false;
  }
}

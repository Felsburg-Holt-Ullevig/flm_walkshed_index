import { describe, expect, it } from 'vitest';
import {
  LOCATIONS_STORAGE_KEY,
  loadLocations,
  parseStoredLocations,
  saveLocations,
  serializeLocations,
} from './locations-store';

const SET = { locations: [{ id: 'a', name: 'Union', lng: -105, lat: 39.75 }], nextNumber: 2 };

function memoryStorage(): Storage {
  const items = new Map<string, string>();
  return {
    getItem: (key) => items.get(key) ?? null,
    setItem: (key, value) => void items.set(key, value),
    removeItem: (key) => void items.delete(key),
    clear: () => items.clear(),
    key: () => null,
    get length() {
      return items.size;
    },
  };
}

describe('locations store', () => {
  it('round-trips a location set', () => {
    const storage = memoryStorage();
    expect(saveLocations(SET, storage)).toBe(true);
    expect(loadLocations(storage)).toEqual(SET);
  });

  const bad: [string, unknown][] = [
    ['another version', { ...SET, version: 2 }],
    ['a bad next number', { version: 1, ...SET, nextNumber: 0 }],
    ['duplicate IDs', { version: 1, ...SET, locations: [SET.locations[0], SET.locations[0]] }],
    ['a blank name', { version: 1, ...SET, locations: [{ ...SET.locations[0], name: ' ' }] }],
    [
      'a position outside the map area',
      { version: 1, ...SET, locations: [{ ...SET.locations[0], lng: 0 }] },
    ],
    [
      'too many locations',
      {
        version: 1,
        ...SET,
        locations: Array.from({ length: 101 }, (_, i) => ({ ...SET.locations[0], id: `${i}` })),
      },
    ],
  ];
  for (const [name, doc] of bad)
    it(`rejects ${name}`, () => expect(parseStoredLocations(JSON.stringify(doc))).toBeNull());

  it('rejects text that is not JSON and treats a missing entry as empty', () => {
    expect(parseStoredLocations('{')).toBeNull();
    expect(parseStoredLocations(null)).toBeNull();
  });

  it('reports unavailable storage instead of throwing', () => {
    const broken = {
      ...memoryStorage(),
      setItem: () => {
        throw new Error('quota');
      },
      getItem: () => {
        throw new Error('denied');
      },
    };
    expect(saveLocations(SET, broken)).toBe(false);
    expect(loadLocations(broken)).toBeNull();
  });

  it('writes under a versioned key', () => {
    const storage = memoryStorage();
    saveLocations(SET, storage);
    expect(storage.getItem(LOCATIONS_STORAGE_KEY)).toBe(serializeLocations(SET));
  });
});

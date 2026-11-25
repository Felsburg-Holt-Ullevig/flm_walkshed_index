import { describe, expect, it } from 'vitest';
import {
  initialState,
  type LocationsAction,
  type LocationsState,
  locationsReducer,
  MAX_HISTORY,
  MAX_LOCATIONS,
  redoChange,
  undoChange,
} from './locations';

const run = (actions: LocationsAction[], state: LocationsState = initialState()) =>
  actions.reduce(locationsReducer, state);
const add = (id: string, lng = -105, lat = 39.75): LocationsAction => ({
  type: 'add',
  id,
  lng,
  lat,
});

describe('locationsReducer', () => {
  it('names new locations with numbers that are never reused', () => {
    const state = run([add('a'), add('b'), { type: 'remove', id: 'a' }, add('c')]);
    expect(state.present.locations.map((l) => l.name)).toEqual(['Location 2', 'Location 3']);
  });

  it('rejects additions beyond the limit, outside the map area or with a duplicate ID', () => {
    let state = initialState();
    for (let i = 0; i < MAX_LOCATIONS + 1; i++) state = locationsReducer(state, add(`p${i}`));
    expect(state.present.locations).toHaveLength(MAX_LOCATIONS);
    expect(run([add('x', -120, 39)]).present.locations).toHaveLength(0);
    expect(run([add('x'), add('x')]).present.locations).toHaveLength(1);
  });

  it('undoes and redoes each change and describes it', () => {
    let state = run([add('a'), { type: 'move', id: 'a', lng: -104.9, lat: 39.7 }]);
    expect(undoChange(state)).toBe('move Location 1');
    state = locationsReducer(state, { type: 'undo' });
    expect(state.present.locations[0]?.lng).toBe(-105);
    expect(redoChange(state)).toBe('move Location 1');
    state = locationsReducer(state, { type: 'redo' });
    expect(state.present.locations[0]?.lng).toBe(-104.9);
  });

  it('restores everything cleared in one undo step', () => {
    let state = run([add('a'), add('b'), { type: 'clear' }]);
    expect(state.present.locations).toHaveLength(0);
    state = locationsReducer(state, { type: 'undo' });
    expect(state.present.locations).toHaveLength(2);
  });

  it('discards redo history after a new change', () => {
    const state = run([add('a'), { type: 'undo' }, add('b')]);
    expect(redoChange(state)).toBeUndefined();
  });

  it('edits name and position as one step and ignores unchanged edits', () => {
    let state = run([add('a')]);
    const before = state;
    state = locationsReducer(state, {
      type: 'edit',
      id: 'a',
      name: 'Location 1',
      lng: -105,
      lat: 39.75,
    });
    expect(state).toBe(before);
    state = locationsReducer(state, {
      type: 'edit',
      id: 'a',
      name: ' Union ',
      lng: -105.1,
      lat: 39.7,
    });
    expect(state.present.locations[0]).toMatchObject({ name: 'Union', lng: -105.1, lat: 39.7 });
    expect(undoChange(state)).toBe('edit Location 1');
    expect(locationsReducer(state, { type: 'edit', id: 'a', name: '', lng: -105, lat: 39 })).toBe(
      state,
    );
  });

  it('keeps a bounded history', () => {
    let state = initialState();
    for (let i = 0; i < MAX_HISTORY + 10; i++) state = locationsReducer(state, add(`p${i}`));
    expect(state.past).toHaveLength(MAX_HISTORY);
  });
});

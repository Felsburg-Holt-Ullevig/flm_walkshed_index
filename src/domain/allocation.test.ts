import { expect, it } from 'vitest';
import { allocate, allocateUnique, allocationWeight, householdShare } from './allocation';

const row = (
  id: string,
  area: number,
  intersection: number,
  counts: Record<string, number | null>,
) => ({
  id,
  sourceAreaSqft: area,
  intersectionAreaSqft: intersection,
  representativeCovered: false,
  counts,
});
it('matches A01, A05, A06 and A07 literal area allocations', () => {
  for (const [area, intersection, count, expected] of [
    [10000, 3000, 100, 30],
    [10000, 2500, 100, 25],
    [1000000, 10000, 1000, 10],
    [14600, 4800, 146, 48],
  ]) {
    const r = row('u', area ?? 0, intersection ?? 0, { pop: count ?? 0 });
    expect(allocate([r], ['pop'], 'uniform_area').totals.pop?.total).toBeCloseTo(expected ?? 0, 9);
    expect(allocate([r], ['pop'], 'representative_point').totals.pop?.total).toBe(0);
  }
});
it('matches A02 unique coverage rather than summed station counts', () => {
  expect(
    allocate([row('u', 10000, 3000, { housing: 40 })], ['housing'], 'uniform_area').totals.housing
      ?.total,
  ).toBe(12);
  const station = [row('u', 10000, 6000, { pop: 100 })];
  expect(allocate(station, ['pop'], 'uniform_area').totals.pop?.total).toBe(60);
  expect(
    allocateUnique(
      [row('u', 10000, 10000, { pop: 100 })],
      ['pop'],
      'uniform_area',
      ['A', 'B'],
      'geometric_union_before_intersection',
    ).totals.pop?.total,
  ).toBe(100);
});
it('matches A03 paired weighted rate and A04 zero/missing distinctions', () => {
  const rows = [row('a', 100, 50, { n: 10, d: 100 }), row('b', 100, 100, { n: 20, d: 100 })];
  expect(householdShare(rows, 'n', 'd', 'uniform_area').percent).toBeCloseTo(16.6666667, 6);
  expect(householdShare([row('a', 1, 1, { n: 0, d: 10 })], 'n', 'd', 'uniform_area').percent).toBe(
    0,
  );
  expect(householdShare([row('a', 1, 1, { n: 0, d: 0 })], 'n', 'd', 'uniform_area').reason).toBe(
    'zero_denominator',
  );
  expect(householdShare([row('a', 1, 1, { n: 0, d: null })], 'n', 'd', 'uniform_area').reason).toBe(
    'missing_pairs',
  );
  expect(
    allocate([row('a', 1, 0.5, { pop: null })], ['pop'], 'uniform_area').totals.pop,
  ).toMatchObject({ total: null, knownSubtotal: 0, missingUnits: 1, missingIntersectionSqft: 0.5 });
});
it('preserves point-boundary membership, missing coverage and rejects invalid inputs', () => {
  const r = { ...row('u', 1, 0, { pop: 5 }), representativeCovered: true };
  expect(allocate([r], ['pop'], 'representative_point').totals.pop?.total).toBe(5);
  expect(() => allocate([r, r], ['pop'], 'uniform_area')).toThrow();
  expect(() => allocate([row('u', 0, 0, { pop: 1 })], ['pop'], 'uniform_area')).toThrow();
  expect(() => allocate([row('u', 1, 2, { pop: 1 })], ['pop'], 'uniform_area')).toThrow();
  expect(() => allocate([row('u', 1, 1, { pop: -1 })], ['pop'], 'uniform_area')).toThrow();
  expect(() => allocate([row('u', 1, 1, {})], ['pop'], 'uniform_area')).toThrow();
  expect(allocationWeight(row('u', 1, 1 + 5e-13, {}), 'uniform_area').clamped).toBe(true);
  expect(householdShare([row('u', 1, 1, { n: 2, d: 1 })], 'n', 'd', 'uniform_area').reason).toBe(
    'numerator_exceeds_denominator',
  );
});

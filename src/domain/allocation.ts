/** Experimental arithmetic; geometry and source-format interpretation belong to adapters. */
export interface AllocationRow {
  id: string;
  sourceAreaSqft: number;
  intersectionAreaSqft: number;
  representativeCovered: boolean;
  counts: Record<string, number | null>;
}

export type AllocationMethod = 'uniform_area' | 'representative_point';
export const ALLOCATION_VERSION = 'allocation-comparison-1';
const WEIGHT_TOLERANCE = 1e-12;

function nonnegative(value: number) {
  if (!Number.isFinite(value) || value < 0) throw Error('invalid_nonnegative_number');
}

export function allocationWeight(row: AllocationRow, method: AllocationMethod) {
  nonnegative(row.sourceAreaSqft);
  nonnegative(row.intersectionAreaSqft);
  if (row.sourceAreaSqft === 0) throw Error('zero_source_area');
  if (typeof row.representativeCovered !== 'boolean') throw Error('invalid_point_coverage');
  const raw = row.intersectionAreaSqft / row.sourceAreaSqft;
  if (raw > 1 + WEIGHT_TOLERANCE) throw Error('intersection_exceeds_source');
  if (method !== 'uniform_area' && method !== 'representative_point')
    throw Error('unsupported_allocation_method');
  return {
    weight: method === 'uniform_area' ? Math.min(1, raw) : Number(row.representativeCovered),
    clamped: raw > 1,
  };
}

function validateRows(rows: readonly AllocationRow[], variables: readonly string[]) {
  if (!variables.length || new Set(variables).size !== variables.length)
    throw Error('invalid_variables');
  const ids = new Set<string>();
  for (const row of rows) {
    if (!row.id || ids.has(row.id)) throw Error('duplicate_or_missing_unit');
    ids.add(row.id);
    for (const variable of variables) {
      const count = row.counts[variable];
      if (count === undefined) throw Error('absent_count_field');
      if (count !== null) nonnegative(count);
    }
  }
}

export function allocate(
  rows: readonly AllocationRow[],
  variables: readonly string[],
  method: AllocationMethod,
) {
  validateRows(rows, variables);
  const ordered = [...rows].sort((a, b) => a.id.localeCompare(b.id));
  const weights = ordered.map((row) => allocationWeight(row, method));
  const totals: Record<
    string,
    {
      total: number | null;
      knownSubtotal: number;
      missingUnits: number;
      missingIntersectionSqft: number;
      relevantUnits: number;
      complete: boolean;
    }
  > = {};
  for (const variable of variables) {
    let knownSubtotal = 0;
    let missingUnits = 0;
    let missingIntersectionSqft = 0;
    let relevantUnits = 0;
    ordered.forEach((row, index) => {
      const weight = weights[index]?.weight ?? 0;
      // A missing covered unit is reported even when its representative point is outside.
      const relevant = row.intersectionAreaSqft > 0 || row.representativeCovered;
      if (!relevant) return;
      relevantUnits++;
      const count = row.counts[variable];
      if (count === null) {
        missingUnits++;
        missingIntersectionSqft += row.intersectionAreaSqft;
      } else if (count !== undefined) knownSubtotal += count * weight;
    });
    if (!Number.isFinite(knownSubtotal) || !Number.isFinite(missingIntersectionSqft))
      throw Error('aggregate_overflow');
    totals[variable] = {
      total: missingUnits ? null : knownSubtotal,
      knownSubtotal,
      missingUnits,
      missingIntersectionSqft,
      relevantUnits,
      complete: missingUnits === 0,
    };
  }
  return {
    method,
    methodVersion: ALLOCATION_VERSION,
    derivedUncertainty: 'not_quantified' as const,
    clampedWeights: weights.filter((weight) => weight.clamped).length,
    totals,
  };
}

export function householdShare(
  rows: readonly AllocationRow[],
  numerator: string,
  denominator: string,
  method: AllocationMethod,
) {
  validateRows(rows, [numerator, denominator]);
  let n = 0;
  let d = 0;
  let missingPairs = 0;
  let inconsistentPairs = 0;
  let pairedUnits = 0;
  for (const row of [...rows].sort((a, b) => a.id.localeCompare(b.id))) {
    const { weight } = allocationWeight(row, method);
    if (row.intersectionAreaSqft === 0 && !row.representativeCovered) continue;
    const a = row.counts[numerator];
    const b = row.counts[denominator];
    if (a === null || b === null || a === undefined || b === undefined) {
      missingPairs++;
      continue;
    }
    pairedUnits++;
    if (a > b) inconsistentPairs++;
    n += a * weight;
    d += b * weight;
  }
  if (!Number.isFinite(n) || !Number.isFinite(d)) throw Error('aggregate_overflow');
  const reason = missingPairs
    ? 'missing_pairs'
    : inconsistentPairs
      ? 'numerator_exceeds_denominator'
      : d === 0
        ? 'zero_denominator'
        : null;
  return {
    percent: reason ? null : (n / d) * 100,
    reason,
    knownPairedNumerator: n,
    knownPairedDenominator: d,
    pairedUnits,
    missingPairs,
    inconsistentPairs,
    derivedUncertainty: 'not_quantified' as const,
  };
}

/** Require geometry already unioned by an adapter; never sum per-station allocations. */
export function allocateUnique(
  rows: readonly AllocationRow[],
  variables: readonly string[],
  method: AllocationMethod,
  stationIds: readonly string[],
  operation: 'geometric_union_before_intersection',
) {
  if (
    operation !== 'geometric_union_before_intersection' ||
    !stationIds.length ||
    stationIds.some((id) => !id) ||
    new Set(stationIds).size !== stationIds.length
  )
    throw Error('invalid_union_provenance');
  return { stationIds: [...stationIds].sort(), ...allocate(rows, variables, method) };
}

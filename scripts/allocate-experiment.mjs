import { readFileSync, writeFileSync } from 'node:fs';
import Ajv from 'ajv';
import { allocateUnique, householdShare } from '../src/domain/allocation.ts';

// Local execution adapter. The imported calculations are the same pure domain source used by the app.
const input = process.argv[2];
const output = process.argv[3];
if (!input || !output)
  throw Error('Usage: node scripts/allocate-experiment.mjs weights.json totals.json');
const raw = readFileSync(input, 'utf8');
if (Buffer.byteLength(raw) > 32 * 1024 * 1024) throw Error('weights_exceed_32_MiB');
const weights = JSON.parse(raw);
const schema = JSON.parse(
  readFileSync('contracts/allocation-experiment/v1/weights.schema.json', 'utf8'),
);
const validate = new Ajv({ strict: true, strictNumbers: true }).compile(schema);
if (!validate(weights)) throw Error(`invalid_weights: ${JSON.stringify(validate.errors)}`);
const ids = new Set();
const results = weights.sets.map((set) => {
  if (ids.has(set.id)) throw Error('duplicate_allocation_set');
  ids.add(set.id);
  return {
    id: set.id,
    comparisons: ['uniform_area', 'representative_point'].map((method) => ({
      ...allocateUnique(set.rows, set.variables, method, set.stationIds, set.operation),
      householdShare: set.variables.includes('B08201_002')
        ? householdShare(set.rows, 'B08201_002', 'B08201_001', method)
        : null,
    })),
  };
});
writeFileSync(
  output,
  `${JSON.stringify(
    {
      version: 'allocation-results-1',
      polygonId: weights.polygonId,
      sourceReleaseId: weights.sourceReleaseId,
      coverage: weights.coverage,
      results,
    },
    null,
    2,
  )}\n`,
  { flag: 'wx' },
);

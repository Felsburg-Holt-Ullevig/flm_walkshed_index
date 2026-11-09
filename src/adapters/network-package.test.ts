import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';
import { semanticEncode, sha256, strictJson, validateSchema } from './network-package';

const fixture = 'pipeline/fixtures/network-package-v1/';
it('rejects duplicate keys, unsafe numbers and invalid JSON', () => {
  for (const input of ['{"a":1,"a":2}', '9007199254740992', '{"a":NaN}', '[1,]', '{} garbage'])
    expect(() => strictJson(input)).toThrow();
});
it('validates the shared structural authority and rejects extra fields', () => {
  const nodes = JSON.parse(readFileSync(`${fixture}nodes.json`, 'utf8'));
  validateSchema('nodes', nodes);
  expect(() => validateSchema('nodes', { ...nodes, extra: 1 })).toThrow();
});
it('reproduces the Python semantic hash', async () => {
  const manifest = JSON.parse(readFileSync(`${fixture}manifest.example.json`, 'utf8'));
  const projection = {
    semantic_version: 'flm-graph-semantic-1',
    identity: manifest.identity,
    coverage: manifest.coverage,
    diagnostics: manifest.diagnostics,
    ...Object.fromEntries(
      ['nodes', 'segments', 'arcs'].map((name) => [
        name,
        JSON.parse(readFileSync(`${fixture}${name}.json`, 'utf8'))[name],
      ]),
    ),
  };
  expect(await sha256(new TextEncoder().encode(JSON.stringify(semanticEncode(projection))))).toBe(
    manifest.graph_id,
  );
  expect(semanticEncode(-0)).toEqual(semanticEncode(0));
});

it('rejects the same structural negative corpus as Python', () => {
  const cases = JSON.parse(readFileSync(`${fixture}structural-negative-corpus.json`, 'utf8')) as {
    schema: string;
    field: string;
    value: unknown;
  }[];
  for (const item of cases) {
    const value = JSON.parse(readFileSync(`${fixture}${item.schema}.json`, 'utf8'));
    value[item.field] = item.value;
    expect(() => validateSchema(item.schema, value)).toThrow();
  }
});

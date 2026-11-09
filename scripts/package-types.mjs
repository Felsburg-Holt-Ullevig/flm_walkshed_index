import { execFileSync } from 'node:child_process';
import { readFile, writeFile } from 'node:fs/promises';
import { compileFromFile } from 'json-schema-to-typescript';

for (const name of ['manifest', 'nodes', 'segments', 'arcs', 'inventory']) {
  const path = `src/adapters/generated/${name}.ts`;
  const source = await compileFromFile(`contracts/network-package/v1/${name}.schema.json`, {
    cwd: 'contracts/network-package/v1',
  });
  const formatted = execFileSync(
    process.execPath,
    ['node_modules/@biomejs/biome/bin/biome', 'format', '--stdin-file-path', path],
    { input: source, encoding: 'utf8' },
  );
  if (process.argv.includes('--check')) {
    if ((await readFile(path, 'utf8')) !== formatted)
      throw Error(`Stale schema-derived types: ${path}`);
  } else await writeFile(path, formatted);
}

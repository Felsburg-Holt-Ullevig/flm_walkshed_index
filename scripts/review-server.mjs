import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { extname, resolve } from 'node:path';

const root = resolve('dist');
createServer(async (request, response) => {
  try {
    const pathname = new URL(request.url, 'http://localhost').pathname;
    const fixture = pathname.match(
      /\/__network-fixture__\/(manifest|nodes|segments|arcs|inventory)\.json$/,
    );
    const relative = pathname.replace(/^\/review\//, '/');
    const target = fixture
      ? resolve(
          'data/generated/prototype/network-packages/synthetic-f01-task52-20261104-e',
          `${fixture[1]}.json`,
        )
      : resolve(root, relative === '/' ? 'index.html' : `.${relative}`);
    if (!fixture && !target.startsWith(`${root}\\`) && !target.startsWith(`${root}/`))
      throw Error('path');
    const bytes = await readFile(target);
    response.setHeader(
      'Content-Type',
      {
        '.html': 'text/html',
        '.js': 'text/javascript',
        '.css': 'text/css',
        '.json': 'application/json',
      }[extname(target)] ?? 'application/octet-stream',
    );
    response.end(bytes);
  } catch {
    response.statusCode = 404;
    response.end('Not found');
  }
}).listen(4174, '127.0.0.1');

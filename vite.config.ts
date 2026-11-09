import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// GITHUB_SHA is set by GitHub Actions; local builds are labeled 'local'.
const commit = (process.env.GITHUB_SHA ?? 'local').slice(0, 7);

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'local-synthetic-package',
      apply: 'serve',
      configureServer(server) {
        server.middlewares.use(async (request, response, next) => {
          const match = request.url?.match(
            /\/__network-fixture__\/(manifest|nodes|segments|arcs|inventory)\.json$/,
          );
          if (!match) return next();
          try {
            const bytes = await readFile(
              resolve(
                'data/generated/prototype/network-packages/synthetic-f01-task52-20261104-e',
                `${match[1]}.json`,
              ),
            );
            response.setHeader('Content-Type', 'application/json');
            response.end(bytes);
          } catch {
            response.statusCode = 404;
            response.end('Synthetic package unavailable');
          }
        });
      },
    },
  ],
  // Relative asset paths work at a domain root or in any subdirectory.
  // Set BASE_PATH only for a host that requires an absolute base.
  base: process.env.BASE_PATH ?? './',
  define: { __APP_COMMIT__: JSON.stringify(commit) },
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true },
  build: { sourcemap: false },
});

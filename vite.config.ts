import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// GITHUB_SHA is set by GitHub Actions; local builds are labeled 'local'.
const commit = (process.env.GITHUB_SHA ?? 'local').slice(0, 7);

export default defineConfig({
  plugins: [react()],
  // Relative asset paths work at a domain root or in any subdirectory.
  // Set BASE_PATH only for a host that requires an absolute base.
  base: process.env.BASE_PATH ?? './',
  define: { __APP_COMMIT__: JSON.stringify(commit) },
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true },
  build: { sourcemap: false },
});

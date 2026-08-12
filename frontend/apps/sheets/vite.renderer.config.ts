import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Web SaaS build of the sheets renderer. The Python backend (:8585) is reached
// same-origin via the dev proxy so the index.html CSP (connect-src 'self') holds.
const BACKEND = process.env.VITE_BACKEND_URL || 'http://localhost:8585'

const shim = (p: string) => fileURLToPath(new URL(`src/renderer/shims/${p}`, import.meta.url))

export default defineConfig(({ command }) => ({
  root: 'src/renderer',
  // prod: served by nginx under /sheets/ so asset URLs don't collide with docs at /
  base: command === 'build' ? '/sheets/' : '/',
  plugins: [react()],
  // The xlsx gateway was written for Electron's node main process. Only the
  // client-run planner (xlsx-gateway) is reached on web; its node builtins map
  // to browser shims. The fs/os save path is served by the backend /sheets API.
  resolve: {
    alias: {
      'node:crypto': shim('node-crypto.ts'),
      'node:path': shim('node-path.ts'),
      'node:os': shim('node-os.ts'),
      'node:fs/promises': shim('node-empty.ts'),
    },
  },
  server: {
    port: Number(process.env.SHEETS_DEV_PORT) || 3589,
    strictPort: true,
    proxy: {
      // `/ai` also matches source modules under src/renderer/ai/ (e.g. /ai/AiPanel.tsx);
      // only proxy extension-less API paths (/ai/stream …), let vite serve the rest.
      '/ai': {
        target: BACKEND,
        changeOrigin: true,
        bypass: (req) => (/\.\w+$/.test((req.url ?? '').split('?')[0]) ? req.url : undefined),
      },
      '/auth': { target: BACKEND, changeOrigin: true },
      '/documents': { target: BACKEND, changeOrigin: true },
      '/projects': { target: BACKEND, changeOrigin: true },
      '/gallery': { target: BACKEND, changeOrigin: true },
      '/skills': { target: BACKEND, changeOrigin: true },
      '/sheets': { target: BACKEND, changeOrigin: true },
      '/files': { target: BACKEND, changeOrigin: true },
    },
  },
}))

import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Web SaaS build of the slides renderer. The Python backend (:8585) is reached
// same-origin via the dev proxy so the index.html CSP (connect-src 'self') holds.
const BACKEND = process.env.VITE_BACKEND_URL || 'http://localhost:8585'

const shim = (p: string) => fileURLToPath(new URL(`src/renderer/shims/${p}`, import.meta.url))

export default defineConfig(({ command }) => ({
  root: 'src/renderer',
  // prod: served by nginx under /slides/ so asset URLs don't collide with docs at /
  base: command === 'build' ? '/slides/' : '/',
  plugins: [react()],
  // pptx-engine was written for Electron's node main process; these are the only
  // node builtins it reaches. Map them to browser shims (Buffer polyfilled in
  // web-adapter). See src/renderer/shims/.
  resolve: {
    alias: {
      'node:crypto': shim('node-crypto.ts'),
      'node:zlib': shim('node-zlib.ts'),
      'node:fs': shim('node-empty.ts'),
      'node:stream/promises': shim('node-empty.ts'),
    },
  },
  server: {
    port: Number(process.env.SLIDES_DEV_PORT) || 3586,
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
      '/files': { target: BACKEND, changeOrigin: true },
    },
  },
}))

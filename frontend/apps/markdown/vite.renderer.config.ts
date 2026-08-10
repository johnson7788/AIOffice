import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Web SaaS build of the markdown renderer. Backend (:8585) reached same-origin
// via the dev proxy (prod: nginx serves this under /markdown/ and proxies the
// API prefixes).
const BACKEND = process.env.VITE_BACKEND_URL || 'http://localhost:8585'

export default defineConfig(({ command }) => ({
  root: 'src/renderer',
  base: command === 'build' ? '/markdown/' : '/',
  plugins: [react()],
  server: {
    port: Number(process.env.MD_DEV_PORT) || 3588,
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
      '/files': { target: BACKEND, changeOrigin: true },
    },
  },
}))

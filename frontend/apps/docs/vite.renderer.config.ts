import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Web SaaS build of the docs renderer. The Python backend (:8585) is reached
// same-origin via the dev proxy so the index.html CSP (connect-src 'self') holds.
const BACKEND = process.env.VITE_BACKEND_URL || 'http://localhost:8585'

export default defineConfig({
  root: 'src/renderer',
  plugins: [react()],
  server: {
    port: Number(process.env.DOCS_DEV_PORT) || 3585,
    strictPort: true,
    proxy: {
      '/ai': { target: BACKEND, changeOrigin: true },
      '/documents': { target: BACKEND, changeOrigin: true },
      '/files': { target: BACKEND, changeOrigin: true },
    },
  },
})

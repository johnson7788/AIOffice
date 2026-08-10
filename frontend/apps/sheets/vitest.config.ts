import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'

const shim = (p: string) => fileURLToPath(new URL(`src/renderer/shims/${p}`, import.meta.url))

export default defineConfig({
  resolve: {
    alias: {
      'node:crypto': shim('node-crypto.ts'),
      'node:path': shim('node-path.ts'),
      'node:os': shim('node-os.ts'),
      'node:fs/promises': shim('node-empty.ts'),
    },
  },
  test: {
    include: ['tests/**/*.test.ts'],
    environment: 'jsdom',
    testTimeout: 20000,
  },
})

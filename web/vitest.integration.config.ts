import { defineConfig } from 'vitest/config'
import path from 'path'

export default defineConfig({
  test: {
    globals: true,
    setupFiles: ['./src/test/integration/setup.ts'],
    globalSetup: ['./src/test/integration/globalSetup.ts'],
    include: ['src/test/integration/**/*.{test,spec}.ts'],
    testTimeout: 30000,
    hookTimeout: 120000, // Longer timeout for server startup
    // Run integration tests sequentially to avoid race conditions
    pool: 'forks',
    poolOptions: {
      forks: {
        singleFork: true,
      },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})

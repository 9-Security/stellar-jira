import { defineConfig } from 'vitest/config';
import path from 'node:path';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['tests/**/*.test.ts'],
    setupFiles: ['tests/setup.ts'],
    testTimeout: 30_000,
    hookTimeout: 60_000,
    fileParallelism: false,
    env: {
      DATABASE_URL:
        process.env.DATABASE_URL && process.env.CI
          ? process.env.DATABASE_URL
          : 'postgresql://crm:crm@localhost:5432/crm_test',
    },
  },
  resolve: {
    alias: {
      '@crm/shared': path.resolve(__dirname, 'packages/shared/src/index.ts'),
      '@crm/db': path.resolve(__dirname, 'packages/db/src/index.ts'),
    },
  },
});

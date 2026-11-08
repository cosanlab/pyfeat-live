import { defineConfig } from 'vitest/config';

// Only pure-TS lib modules (Studio engine, fex helpers) are unit tested. Svelte components
// stay on `pnpm check` + in-app browser verification.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/lib/**/*.test.ts'],
    passWithNoTests: true,
  },
});

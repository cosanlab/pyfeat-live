import { defineConfig } from 'vitest/config';

// Only the pure-TS Studio engine modules are unit tested. Svelte components
// stay on `pnpm check` + in-app browser verification.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/lib/studio/**/*.test.ts'],
    passWithNoTests: true,
  },
});

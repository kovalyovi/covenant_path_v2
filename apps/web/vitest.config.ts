import { defineConfig, mergeConfig } from 'vitest/config';
import viteConfig from './vite.config';

// Test config kept separate from vite.config.ts so the production `tsc -b` build never type-checks
// vitest-only fields. Reuses the app's Vite plugins (React) for accurate JSX/TS transforms.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      css: false,
      // Unit tests live under src/ only — keeps vitest away from the Playwright specs in e2e/
      // (their default include pattern would otherwise pick up e2e/*.spec.ts).
      include: ['src/**/*.{test,spec}.{ts,tsx}'],
    },
  }),
);

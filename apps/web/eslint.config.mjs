import next from "eslint-config-next";

// TypeScript itself reports unused values and types; the base rule would double-report type-only names.
const config = [
  ...next,
  { ignores: [".next/**", "node_modules/**", "playwright-report/**", "test-results/**", "screenshots.mjs", "*.config.mjs"] },
];

export default config;

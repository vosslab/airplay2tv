// @ts-check
import eslint from "@eslint/js";
import tseslint from "typescript-eslint";
import globals from "globals";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Avoid Node-version coupling: import.meta.dirname needs Node >=20.11.
// Use fileURLToPath + path.dirname to stay compatible with Node 18 LTS.
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export default tseslint.config(
  eslint.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,
  {
    // TypeScript source files (.ts/.tsx/.mts/.cts) -- full type-checked ruleset.
    // project list pins both tsconfigs so .ts files under src/, tests/, and tools/
    // all have type info available to typescript-eslint.
    files: ["**/*.{ts,tsx,mts,cts}"],
    languageOptions: {
      parserOptions: {
        project: ["./tsconfig.json", "./tsconfig.lint.json"],
        tsconfigRootDir: __dirname,
      },
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unused-vars": "error",
      "@typescript-eslint/explicit-function-return-type": "error",
      "@typescript-eslint/no-floating-promises": "error",
      "no-var": "error",
      "prefer-const": "error",
      "no-implicit-coercion": "warn",
      eqeqeq: "error",
      "no-throw-literal": "error",
      "no-console": "warn",
    },
  },
  {
    // Plain JS / MJS / CJS files (eslint.config.js, tests/playwright/*.mjs helpers,
    // tools/*.mjs CLI utilities). These are intentionally NOT in any tsconfig project,
    // so typescript-eslint's type-checked rules would error on them. disableTypeChecked
    // turns those rules off while keeping the recommended non-typed rules active.
    files: ["**/*.{js,mjs,cjs}"],
    ...tseslint.configs.disableTypeChecked,
    languageOptions: {
      globals: { ...globals.node },
    },
  },
  {
    ignores: ["dist/**", "node_modules/**"],
  },
);

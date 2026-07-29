import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

const eslintConfig = [
  {
    ignores: [
      ".next/**",
      "out/**",
      "build/**",
      "node_modules/**",
      "dist/**",
      "**/dist/**",
      "packages/**",
      "next-env.d.ts",
      // Generated API client — never hand-edited, do not lint.
      "src/api/client/**",
    ],
  },
  ...nextCoreWebVitals,
  ...nextTypescript,

  // ── Strict project rules ──────────────────────────────────────────────────
  // We deliberately treat real bug-catchers as errors instead of relaxing them
  // away. The previous config disabled all of these "to unblock CI"; that is
  // exactly how an error-swallowing catch hid a real bug.
  {
    files: ["**/*.{ts,tsx,mjs}"],
    rules: {
      // Correctness / bug-catchers
      "no-empty": ["error", { allowEmptyCatch: false }], // no silent `catch {}`
      "no-console": ["error", { allow: ["warn", "error"] }], // keep error/warn, ban stray logs
      eqeqeq: ["error", "always", { null: "ignore" }],
      "no-var": "error",
      "prefer-const": "error",
      "no-throw-literal": "error",
      "no-unneeded-ternary": "error",
      "object-shorthand": ["error", "properties"],

      // TypeScript
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrors: "all",
          caughtErrorsIgnorePattern: "^_",
        },
      ],
      "@typescript-eslint/no-non-null-assertion": "error",
      "@typescript-eslint/no-unused-expressions": [
        "error",
        { allowShortCircuit: true, allowTernary: true },
      ],
      "@typescript-eslint/ban-ts-comment": [
        "error",
        { "ts-expect-error": "allow-with-description", "ts-ignore": true },
      ],

      // React
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",

      // Non-bug noise — visible but non-blocking. The React Compiler rules
      // (react-hooks v6) are advisory for a codebase not authored for it, and
      // <img> vs next/Image is a perf nudge, not a correctness bug. Ratchet to
      // error later if we adopt them.
      "@next/next/no-img-element": "warn",
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/purity": "off",
      "react-hooks/immutability": "off",
      "react-hooks/use-memo": "off",
      "react-hooks/refs": "off",
      "react-hooks/preserve-manual-memoization": "off",
    },
  },

  // ── Carve-outs ────────────────────────────────────────────────────────────
  // Type declaration files legitimately model external/any-shaped payloads.
  {
    files: ["src/types/**/*.{ts,tsx}", "**/*.d.ts"],
    rules: {
      "@typescript-eslint/no-explicit-any": "off",
    },
  },
  // Config / CJS loaders may use require and console.
  {
    files: ["*.config.{ts,js,mjs}", "tailwind.config.ts", "*.cjs", "eslint.config.mjs"],
    rules: {
      "@typescript-eslint/no-require-imports": "off",
      "no-console": "off",
    },
  },
  // Test/script scaffolding may log freely.
  {
    files: ["**/__tests__/**", "tests/**", "**/*.test.{ts,tsx}", "scripts/**"],
    rules: {
      "no-console": "off",
    },
  },
];

export default eslintConfig;

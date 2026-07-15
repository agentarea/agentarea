import { defineConfig } from "@hey-api/openapi-ts";

// Generates type-safe artifacts from the committed OpenAPI spec:
//   - types.gen.ts : TS types for every schema (request/response contracts)
//   - zod.gen.ts   : runtime Zod schemas mirroring those contracts
// Source of truth is the backend spec; never hand-edit the generated output.
// Regenerate with: pnpm generate:client
export default defineConfig({
  input: "./src/api/openapi.json",
  output: {
    path: "./src/api/client",
    postProcess: ["prettier"],
  },
  plugins: [
    {
      name: "@hey-api/client-next",
      baseUrl: false,
      runtimeConfigPath: "./src/api/client-runtime",
    },
    "@hey-api/sdk",
    "@hey-api/typescript",
    "zod",
  ],
});

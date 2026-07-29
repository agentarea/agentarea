import { defineConfig } from "@hey-api/openapi-ts";

// Generates the runtime-agnostic (fetch) flavor of the AgentArea API client.
// Source of truth is the SAME spec the webapp commits — no second curl, no drift.
// The webapp keeps its own Next-flavor generation under src/api/client untouched.
// Regenerate with: pnpm run generate
export default defineConfig({
  input: "../../src/api/openapi.json",
  output: {
    path: "./src/generated",
  },
  // No zod plugin: the CLI consumes typed request/response contracts, not
  // runtime schemas, and hey-api 0.99 emits zod v4 syntax the workspace's
  // zod v3 can't run. Add it back here if a consumer needs runtime validation.
  plugins: [
    { name: "@hey-api/client-fetch", baseUrl: false },
    "@hey-api/sdk",
    "@hey-api/typescript",
  ],
});

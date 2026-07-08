import { expect, test } from "@playwright/test";
import { z } from "zod";
import { requirementTitle } from "./requirements";
import {
  aiSkipReason,
  aiSpecsEnabled,
  baseURL,
  withAuthedStagehand,
} from "./helpers/stagehand";

/**
 * FR-08 - OpenAPI tool connection setup, driven through the real UI by an LLM
 * (Stagehand). A fresh user registers an OpenAPI spec by URL, the app discovers
 * its operations, and we assert the discovered tools / created connection show
 * up.
 *
 * Uses a small, stable public OpenAPI document by default; override with
 * TEST_OPENAPI_SPEC_URL to point at a fixture served by the real stack.
 */
test.describe("FR-08 OpenAPI tool connection (AI-driven)", () => {
  test.skip(!aiSpecsEnabled, aiSkipReason);

  test(
    requirementTitle(
      "FR-08",
      "a user registers an OpenAPI spec and discovers its tools"
    ),
    async () => {
      await withAuthedStagehand("ai-openapi", async ({ stagehand, page }) => {
        await page.goto(`${baseURL}/connections`);
        expect(page.url()).not.toMatch(/\/auth\/login/);

        const specUrl =
          process.env.TEST_OPENAPI_SPEC_URL ??
          "https://petstore3.swagger.io/api/v3/openapi.json";

        await stagehand.act("start adding a new OpenAPI tool connection");
        await stagehand.act(`enter "${specUrl}" as the OpenAPI specification URL`);
        await stagehand.act("trigger discovery / preview of the operations in the spec");

        const result = await stagehand.extract(
          "After importing the OpenAPI spec, how many operations/tools were discovered and are they listed on the page?",
          z.object({
            toolsDiscovered: z.boolean(),
            operationCount: z.number().optional(),
          })
        );

        expect(result.toolsDiscovered).toBe(true);
      });
    }
  );
});

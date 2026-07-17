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
 * FR-04 - Provider configs and model instances, driven through the real UI by
 * an LLM (Stagehand). This is the "configure an API" user journey: a fresh user
 * lands in the app, opens the model providers screen, adds a provider with a
 * key, and we assert the provider is persisted and visible.
 *
 * The act() steps are intentionally described the way a user would phrase the
 * goal, not as DOM selectors - that is what makes this resilient to UI churn
 * (and, deliberately, less deterministic than hand-written selectors).
 */
test.describe("FR-04 provider config (AI-driven)", () => {
  test.skip(!aiSpecsEnabled, aiSkipReason);

  test(
    requirementTitle(
      "FR-04",
      "a user configures an LLM provider through the UI"
    ),
    async () => {
      await withAuthedStagehand("ai-provider", async ({ stagehand, page }) => {
        await page.goto(`${baseURL}/models`);

        // Sanity: we are authenticated and on the models surface.
        expect(page.url()).not.toMatch(/\/auth\/login/);

        await stagehand.act(
          "open the form or dialog to add a new LLM provider configuration"
        );

        const apiKey = process.env.TEST_PROVIDER_API_KEY ?? "sk-test-fake-key-1234567890";
        await stagehand.act(
          `choose OpenAI as the provider and enter "${apiKey}" as the API key`
        );
        await stagehand.act("submit the provider configuration form");

        const result = await stagehand.extract(
          "Is there a saved OpenAI provider configuration now visible in the list of configured providers?",
          z.object({
            providerVisible: z.boolean(),
            providerName: z.string().optional(),
          })
        );

        expect(result.providerVisible).toBe(true);
      });
    }
  );
});

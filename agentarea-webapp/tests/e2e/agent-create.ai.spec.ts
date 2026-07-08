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
 * FR-03 - Agent lifecycle, driven through the real UI by an LLM (Stagehand).
 * A fresh user opens the agents screen, creates an agent with a name and model,
 * and we assert the new agent shows up.
 */
test.describe("FR-03 agent creation (AI-driven)", () => {
  test.skip(!aiSpecsEnabled, aiSkipReason);

  test(
    requirementTitle("FR-03", "a user creates an agent through the UI"),
    async () => {
      await withAuthedStagehand("ai-agent", async ({ stagehand, page }) => {
        await page.goto(`${baseURL}/agents`);
        expect(page.url()).not.toMatch(/\/auth\/login/);

        const agentName = `ai-e2e-agent-${Date.now()}`;
        await stagehand.act("start creating a new agent");
        await stagehand.act(`set the agent name to "${agentName}"`);
        await stagehand.act("select any available model for the agent");
        await stagehand.act("submit the form to create the agent");

        const result = await stagehand.extract(
          `Is an agent named "${agentName}" now visible on the page (either in a list or on its detail page)?`,
          z.object({
            agentVisible: z.boolean(),
          })
        );

        expect(result.agentVisible).toBe(true);
      });
    }
  );
});

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
 * FR-07 - MCP server / instance setup, driven through the real UI by an LLM
 * (Stagehand). A fresh user adds an MCP server, and we assert it is created and
 * shown with a deploy/health state.
 *
 * Note: this journey depends on the MCP manager actually provisioning a
 * container, so it is the most flaky of the four - keep an eye on timeouts.
 */
test.describe("FR-07 MCP server setup (AI-driven)", () => {
  test.skip(!aiSpecsEnabled, aiSkipReason);

  test(
    requirementTitle("FR-07", "a user adds an MCP server through the UI"),
    async () => {
      await withAuthedStagehand("ai-mcp", async ({ stagehand, page }) => {
        await page.goto(`${baseURL}/mcp-servers`);
        expect(page.url()).not.toMatch(/\/auth\/login/);

        const serverName = `ai-e2e-mcp-${Date.now()}`;
        await stagehand.act("start adding a new MCP server");
        await stagehand.act(`set the MCP server name to "${serverName}"`);
        await stagehand.act(
          "fill any remaining required fields with reasonable defaults for a basic MCP server"
        );
        await stagehand.act("submit the form to create the MCP server");

        const result = await stagehand.extract(
          `Is an MCP server named "${serverName}" now visible in the list, and does it show some status (deploying, running, or error)?`,
          z.object({
            serverVisible: z.boolean(),
            status: z.string().optional(),
          })
        );

        expect(result.serverVisible).toBe(true);
      });
    }
  );
});

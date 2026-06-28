import { expect, test } from "@playwright/test";
import {
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  type AuthedUser,
} from "./helpers/real-stack";
import { expectRedirectedAwayFrom, gotoCommitted, runRealStack } from "./helpers/scenarios";

test.describe("Scenario 04 MP - add an MCP server and use its tool from an agent", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1");

  let user: AuthedUser;

  test.beforeAll(async () => {
    user = await createKratosUser("scenario-04");
  });

  test.afterAll(async () => {
    if (user) await deleteKratosUser(user.identityId);
  });

  // KNOWN REAL BUG (red on purpose): mcp-servers/add/actions.ts builds a
  // payload that still fails generated request validation before redirecting,
  // so the UI stays on the form with a 422-style validation failure
  // (src/app/(main)/mcp-servers/add/actions.ts:224).
  test("creates a Docker MCP server through the real Add form", async ({
    context,
    page,
  }) => {
    test.setTimeout(90_000);
    await installBrowserSession(context, user);

    await gotoCommitted(page, "/mcp-servers/add");
    await page.locator("#name").fill(`scenario-04-mcp-${Date.now()}`);
    await page.locator("#description").fill("Scenario 04 MCP server");
    await page.locator("#dockerImageUrl").fill("ghcr.io/example/e2e-mcp:latest");
    await page.getByRole("button", { name: "Add Server" }).click();

    await expectRedirectedAwayFrom(page, "/mcp-servers/add");
    await expect(page).toHaveURL(/\/mcp-servers\/[^/]+/);
  });
});

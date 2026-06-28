import { expect, test } from "@playwright/test";
import {
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  type AuthedUser,
} from "./helpers/real-stack";
import {
  deleteAgent,
  deleteMcpServer,
  gotoCommitted,
  runRealStack,
  seedAgent,
  seedMcpServer,
} from "./helpers/scenarios";

test.describe("Scenario 14 MP - inspect the network topology", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1");

  let user: AuthedUser;
  let agent: { id: string; name: string } | undefined;
  let mcp: { id: string; name: string } | undefined;

  test.beforeAll(async ({ request }) => {
    user = await createKratosUser("scenario-14");
    agent = await seedAgent(request, user, "scenario-14-agent");
    mcp = await seedMcpServer(request, user, "scenario-14-mcp");
  });

  test.afterAll(async ({ request }) => {
    await deleteAgent(request, user, agent?.id);
    await deleteMcpServer(request, user, mcp?.id);
    if (user) await deleteKratosUser(user.identityId);
  });

  test("views access/dataflow topology, opens a node drawer, and reloads scope", async ({
    context,
    page,
  }) => {
    test.setTimeout(90_000);
    await installBrowserSession(context, user);

    await gotoCommitted(page, "/network");
    await expect(page.getByText(/Access Graph|Data Flow|Organization/i)).toBeVisible();
    await page.getByRole("button", { name: /access graph/i }).click();
    await expect(page.getByText(/workspace|private zone|egress|no egress/i)).toBeVisible({
      timeout: 15_000,
    });
    await page.getByRole("button", { name: /data flow/i }).click();
    await page.getByText(agent!.name, { exact: false }).click();
    await expect(page.getByText(/details|relationships|agent|status/i)).toBeVisible({
      timeout: 15_000,
    });
    await gotoCommitted(page, "/dashboard");
    await gotoCommitted(page, "/network");
    await expect(page.getByText(agent!.name, { exact: false })).toBeVisible({
      timeout: 15_000,
    });
  });
});

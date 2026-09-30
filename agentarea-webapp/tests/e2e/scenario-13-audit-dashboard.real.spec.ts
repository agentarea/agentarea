import { expect, test } from "@playwright/test";
import {
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  type AuthedUser,
} from "./helpers/real-stack";
import {
  deleteAgent,
  gotoCommitted,
  runRealStack,
  seedAgent,
} from "./helpers/scenarios";

test.describe("Scenario 13 MP - inspect audit and dashboard activity", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1");

  let user: AuthedUser;
  let agent: { id: string; name: string } | undefined;

  test.beforeAll(async ({ request }) => {
    user = await createKratosUser("scenario-13");
    agent = await seedAgent(request, user, "scenario-13-agent");
  });

  test.afterAll(async ({ request }) => {
    await deleteAgent(request, user, agent?.id);
    if (user) await deleteKratosUser(user.identityId);
  });

  test("checks durable audit activity and dashboard summary", async ({
    context,
    page,
  }) => {
    test.setTimeout(90_000);
    await installBrowserSession(context, user);

    // Outcome: the audit log records a real governance event (seedAgent creates
    // the agent -> an `agent.create` event), and it is DURABLE: still present
    // after a reload (not stream-only). This is the actual FR being verified.
    // The log shows the verb and resource type; the raw action is the title.
    const agentCreated = page
      .getByRole("row")
      .filter({ hasText: agent?.name ?? "" })
      .getByTitle("agent.create", { exact: true });
    await gotoCommitted(page, "/settings/audit");
    await expect(agentCreated).toBeVisible({ timeout: 15_000 });
    await page.reload({ waitUntil: "commit" });
    await expect(agentCreated).toBeVisible({ timeout: 15_000 });

    await gotoCommitted(page, "/dashboard");
    await expect(page.getByText("Dashboard").first()).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText(/^\$[\d,.]+$/).first()).toBeVisible({
      timeout: 15_000,
    });
    await gotoCommitted(page, "/settings/audit");
    await expect(agentCreated).toBeVisible({ timeout: 15_000 });
  });
});

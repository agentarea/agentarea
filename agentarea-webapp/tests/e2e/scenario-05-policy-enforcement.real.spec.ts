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
  deletePolicy,
  gotoCommitted,
  runRealStack,
  seedAgent,
  seedMcpServer,
} from "./helpers/scenarios";

test.describe("Scenario 05 MP - create a policy and verify enforcement", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1");

  let user: AuthedUser;
  let agent: { id: string; name: string } | undefined;
  let mcp: { id: string; name: string } | undefined;
  let policyId: string | undefined;

  test.beforeAll(async ({ request }) => {
    user = await createKratosUser("scenario-05");
    agent = await seedAgent(request, user, "scenario-05-agent");
    mcp = await seedMcpServer(request, user, "scenario-05-mcp");
  });

  test.afterAll(async ({ request }) => {
    await deletePolicy(request, user, policyId);
    await deleteAgent(request, user, agent?.id);
    await deleteMcpServer(request, user, mcp?.id);
    if (user) await deleteKratosUser(user.identityId);
  });

  // BLOCKED-RUNTIME: this verifies UI policy authoring and persistence. Actual
  // runtime enforcement during LLM/tool execution is out of local scope.
  test("authors a budget policy in the UI and verifies it persists in the policy list", async ({
    context,
    page,
  }) => {
    test.setTimeout(90_000);
    await installBrowserSession(context, user);

    const amount = "17.13";

    await gotoCommitted(page, "/policies/new");
    await expect(page.getByText("Policy Control Plane")).toBeVisible();
    await page.getByLabel("Amount").fill(amount);
    await page.getByRole("button", { name: "Create rule" }).click();

    await expect
      .poll(() => new URL(page.url()).pathname, { timeout: 30_000 })
      .toBe("/policies");

    await page.reload({ waitUntil: "commit" });
    await expect(page.getByText("Monthly budget")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText("$17.13")).toBeVisible();

    await page.getByText("Monthly budget").click();
    await expect
      .poll(() => new URL(page.url()).pathname, { timeout: 15_000 })
      .toMatch(/^\/policies\/[^/]+$/);
    policyId = new URL(page.url()).pathname.split("/").pop();
    // Detail view may format the amount without a leading "$" - match the value.
    await expect(page.getByText(/17\.13/).first()).toBeVisible({ timeout: 15_000 });
  });
});

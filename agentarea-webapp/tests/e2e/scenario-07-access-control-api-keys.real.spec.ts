import { expect, test } from "@playwright/test";
import {
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  uniqueLabel,
  type AuthedUser,
} from "./helpers/real-stack";
import {
  deleteAgent,
  gotoCommitted,
  runRealStack,
  seedAgent,
} from "./helpers/scenarios";

test.describe("Scenario 07 MP - workspace access control, grants, and API keys", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1");

  let owner: AuthedUser;
  let invited: AuthedUser;
  let agent: { id: string; name: string } | undefined;

  test.beforeAll(async ({ request }) => {
    owner = await createKratosUser("scenario-07-owner");
    invited = await createKratosUser("scenario-07-invited");
    agent = await seedAgent(request, owner, "scenario-07-agent");
  });

  test.afterAll(async ({ request }) => {
    await deleteAgent(request, owner, agent?.id);
    if (owner) await deleteKratosUser(owner.identityId);
    if (invited) await deleteKratosUser(invited.identityId);
  });

  // BLOCKED-RUNTIME: member invite and API key creation are verified through
  // the UI. Tool grant execution and multi-workspace switching require runtime
  // authorization setup outside this local test.
  test("invites a member through the UI and creates a persisted API key", async ({
    context,
    page,
  }) => {
    test.setTimeout(90_000);
    await installBrowserSession(context, owner);

    await gotoCommitted(page, "/agents");
    await expect(page.getByText(agent!.name, { exact: false })).toBeVisible();

    await gotoCommitted(page, "/members");
    await page.getByRole("button", { name: /invite/i }).click();
    await page.getByLabel(/email/i).fill(invited.email);
    await page.getByRole("button", { name: /create|invite/i }).last().click();
    await expect(page.getByText(/invite|invitation|copy/i)).toBeVisible({
      timeout: 15_000,
    });

    const keyName = uniqueLabel("scenario-07-key");

    await gotoCommitted(page, "/admin/api-keys");
    await page.getByRole("button", { name: /create key/i }).click();
    await page.getByLabel(/name/i).fill(keyName);
    await page.getByLabel(/expires/i).fill("7");
    await page.getByRole("button", { name: /^create$/i }).click();

    await expect(page.getByText(/created|copy|token/i)).toBeVisible({
      timeout: 15_000,
    });
    await gotoCommitted(page, "/admin/api-keys");
    await expect(page.getByText(keyName, { exact: false })).toBeVisible({
      timeout: 15_000,
    });
  });
});

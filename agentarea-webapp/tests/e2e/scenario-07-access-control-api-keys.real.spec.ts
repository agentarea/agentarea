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
  let agent: { id: string; name: string } | undefined;

  test.beforeAll(async ({ request }) => {
    owner = await createKratosUser("scenario-07-owner");
    agent = await seedAgent(request, owner, "scenario-07-agent");
  });

  test.afterAll(async ({ request }) => {
    await deleteAgent(request, owner, agent?.id);
    if (owner) await deleteKratosUser(owner.identityId);
  });

  // Scope note: this verifies the concretely creatable access-control surface -
  // a scoped API key created through the UI that persists in the list. Member
  // invitation, tool-grant enforcement and cross-workspace isolation are
  // runtime/multi-user concerns out of scope for a single local stand.
  test("creates a scoped API key through the UI and it persists in the list", async ({
    context,
    page,
  }) => {
    test.setTimeout(90_000);
    await installBrowserSession(context, owner);

    const keyName = uniqueLabel("scenario-07-key");

    await gotoCommitted(page, "/admin/api-keys");
    await page.locator('[data-test="create-api-key-button"]').click();

    // Dialog form (stable ids; submit button is bound to the form by id).
    await page.locator("#api-key-name").fill(keyName);
    await page.locator("#api-key-expiry").fill("7");
    await page.locator('button[form="api-key-form"]').click();

    // FUNCTIONAL OUTCOME: the new key is listed by its name (a fresh user has
    // exactly this one), and survives a reload (persisted, not just the toast).
    await expect(
      page.getByText(keyName, { exact: false }),
      "new API key should appear in the list"
    ).toBeVisible({ timeout: 15_000 });

    await page.reload({ waitUntil: "commit" });
    await expect(
      page.getByText(keyName, { exact: false }),
      "API key should persist after reload"
    ).toBeVisible({ timeout: 15_000 });
  });
});

import { expect, test } from "@playwright/test";
import {
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  type AuthedUser,
} from "./helpers/real-stack";
import { gotoCommitted, runRealStack } from "./helpers/scenarios";

test.describe("Scenario 12 MP - view wallet, spend, and budget tracking", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1");

  let user: AuthedUser;

  test.beforeAll(async () => {
    user = await createKratosUser("scenario-12");
  });

  test.afterAll(async () => {
    if (user) await deleteKratosUser(user.identityId);
  });

  test("reviews budgets and billing without enterprise-only setup", async ({
    context,
    page,
  }) => {
    test.setTimeout(90_000);
    await installBrowserSession(context, user);

    // Outcome: the budget control plane renders its spend/cap panel (the monthly
    // cap input is a stable, unique landmark) and survives a reload.
    await gotoCommitted(page, "/budgets");
    await expect(page.locator("#monthly-cap")).toBeVisible({ timeout: 15_000 });
    await page.reload({ waitUntil: "commit" });
    await expect(page.locator("#monthly-cap")).toBeVisible({ timeout: 15_000 });

    // Core spend tracking does not require enterprise billing setup: the billing
    // settings page is reachable (settings nav landmark) without gating.
    await gotoCommitted(page, "/settings/billing");
    await expect(page.getByText("Billing").first()).toBeVisible({ timeout: 15_000 });
    await gotoCommitted(page, "/budgets");
    await expect(page.locator("#monthly-cap")).toBeVisible({ timeout: 15_000 });
  });
});

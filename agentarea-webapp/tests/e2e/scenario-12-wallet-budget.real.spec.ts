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

    await gotoCommitted(page, "/budgets");
    await expect(page.getByText(/month outlook|monthly cap|today/i)).toBeVisible({
      timeout: 15_000,
    });
    const budgetText = await page.locator("body").innerText();
    await page.reload({ waitUntil: "commit" });
    await expect(page.locator("body")).toContainText("Monthly cap", {
      timeout: 15_000,
    });

    await gotoCommitted(page, "/settings/billing");
    await expect(
      page.getByText(/billing|usage|current plan|enterprise/i)
    ).toBeVisible({ timeout: 15_000 });
    await gotoCommitted(page, "/budgets");
    await expect(page.locator("body")).toContainText(budgetText.slice(0, 30));
  });
});

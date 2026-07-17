import { expect, test } from "@playwright/test";
import {
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  type AuthedUser,
} from "./helpers/real-stack";
import { gotoCommitted, runRealStack } from "./helpers/scenarios";

test.describe("Scenario 15 MP - install an agent from the registry", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1");

  let user: AuthedUser;

  test.beforeAll(async () => {
    user = await createKratosUser("scenario-15");
  });

  test.afterAll(async () => {
    if (user) await deleteKratosUser(user.identityId);
  });

  test("browses Explore for an installable agent and verifies it appears in Agents", async ({
    context,
    page,
  }) => {
    test.setTimeout(90_000);
    await installBrowserSession(context, user);

    await gotoCommitted(page, "/explore?type=agents");
    const firstAgentCard = page.getByRole("button").filter({
      hasText: /agent|assistant|support|research|sales/i,
    }).first();
    await expect(firstAgentCard).toBeVisible({ timeout: 15_000 });
    const installedName = (await firstAgentCard.innerText()).split("\n")[0].trim();

    await firstAgentCard.click();
    await expect(
      page.getByRole("button", { name: /add to workspace/i })
    ).toBeVisible({
      timeout: 15_000,
    });
    await page.getByRole("button", { name: /add to workspace/i }).click();
    await expect(
      page.getByText(/added to your workspace|install failed/i)
    ).toBeVisible({ timeout: 25_000 });

    await gotoCommitted(page, "/agents");
    await expect(page.getByText(installedName, { exact: false })).toBeVisible({
      timeout: 15_000,
    });
  });
});

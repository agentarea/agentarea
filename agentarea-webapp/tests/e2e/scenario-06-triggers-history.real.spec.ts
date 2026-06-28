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
  deleteTrigger,
  expectRedirectedAwayFrom,
  gotoCommitted,
  runRealStack,
  seedAgent,
} from "./helpers/scenarios";

test.describe("Scenario 06 MP - create cron and webhook triggers", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1");

  let user: AuthedUser;
  let agent: { id: string; name: string } | undefined;
  let triggerId: string | undefined;

  test.beforeAll(async ({ request }) => {
    user = await createKratosUser("scenario-06");
    agent = await seedAgent(request, user, "scenario-06-agent");
  });

  test.afterAll(async ({ request }) => {
    await deleteTrigger(request, user, triggerId);
    await deleteAgent(request, user, agent?.id);
    if (user) await deleteKratosUser(user.identityId);
  });

  test("creates a cron trigger through the UI and opens trigger history detail", async ({
    context,
    page,
  }) => {
    test.setTimeout(90_000);
    await installBrowserSession(context, user);

    const name = uniqueLabel("scenario-06-cron");

    await gotoCommitted(page, "/triggers/create");
    await page.getByText("Cron", { exact: false }).click();
    await page.locator("#name").fill(name);
    await page.getByRole("combobox").first().click();
    await page.getByRole("option", { name: new RegExp(agent!.name) }).click();
    await page.getByPlaceholder("0 9 * * 1-5").fill("*/30 * * * *");
    await page
      .getByPlaceholder("Text to pass into each task created by this trigger")
      .fill("Cron trigger scenario task");
    await page.getByRole("button", { name: /create|save/i }).click();

    await expectRedirectedAwayFrom(page, "/triggers/create");
    await gotoCommitted(page, "/triggers");
    await page.reload({ waitUntil: "commit" });
    await expect(page.getByText(name, { exact: false })).toBeVisible({
      timeout: 15_000,
    });

    await page.getByText(name, { exact: false }).click();
    await expect
      .poll(() => new URL(page.url()).pathname, { timeout: 15_000 })
      .toMatch(/^\/triggers\/[^/]+$/);
    triggerId = new URL(page.url()).pathname.split("/").pop();
    await expect(page.getByText(agent!.name, { exact: false })).toBeVisible();
  });
});

import { expect, test } from "@playwright/test";
import {
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  type AuthedUser,
} from "./helpers/real-stack";
import { deleteAgent, gotoCommitted, runRealStack, seedAgent } from "./helpers/scenarios";

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

    await gotoCommitted(page, "/settings/audit");
    await expect(
      page.getByText(/action|resource|actor|no events|enterprise/i)
    ).toBeVisible({ timeout: 15_000 });
    const auditText = (await page.locator("body").innerText()).slice(0, 80);
    await page.reload({ waitUntil: "commit" });
    await expect(page.locator("body")).toContainText(auditText.slice(0, 30), {
      timeout: 15_000,
    });

    await gotoCommitted(page, "/dashboard");
    await expect(page.getByText(/spend|activity|agents|blockers/i)).toBeVisible({
      timeout: 15_000,
    });
    await gotoCommitted(page, "/settings/audit");
    await expect(page.locator("body")).toContainText(auditText.slice(0, 30));
  });
});

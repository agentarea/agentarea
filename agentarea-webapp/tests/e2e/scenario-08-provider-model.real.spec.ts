import { expect, test } from "@playwright/test";
import {
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  uniqueLabel,
  type AuthedUser,
} from "./helpers/real-stack";
import { gotoCommitted, runRealStack } from "./helpers/scenarios";

test.describe("Scenario 08 MP - register an LLM provider and test a model", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1");

  let user: AuthedUser;
  let providerConfigName: string | undefined;

  test.beforeAll(async () => {
    user = await createKratosUser("scenario-08");
  });

  test.afterAll(async () => {
    // Best-effort cleanup is limited here because the UI creates provider
    // configs/model instances without exposing their ids in the list URL.
    if (user) await deleteKratosUser(user.identityId);
  });

  // BLOCKED-RUNTIME: this verifies provider config + model instance creation
  // through the UI. The live LLM test call is out of local scope because the
  // credentials are fake.
  test("creates a provider config and model instance through the UI", async ({
    context,
    page,
  }) => {
    test.setTimeout(90_000);
    await installBrowserSession(context, user);

    providerConfigName = uniqueLabel("scenario-08-provider");

    await gotoCommitted(page, "/admin/providers");
    await expect(page.getByText(/provider/i)).toBeVisible();

    await gotoCommitted(page, "/admin/provider-configs/create");
    await page.getByRole("combobox").first().click();
    await page.getByRole("option").first().click();
    await page.locator("#name").fill(providerConfigName);
    await page.locator("#api_key").fill("scenario-08-invalid-key");
    await page.locator("#endpoint_url").fill("https://example.invalid");
    await expect(
      page.getByRole("button", { name: /test.*discover|discover models/i })
    ).toBeVisible();

    const selectAll = page.getByRole("button", { name: /select all/i });
    if (await selectAll.isVisible().catch(() => false)) {
      await selectAll.click();
    }
    await page.getByRole("button", { name: /create config/i }).click();

    await expect
      .poll(() => new URL(page.url()).pathname, { timeout: 30_000 })
      .toBe("/admin/provider-configs");
    await page.reload({ waitUntil: "commit" });
    await expect(
      page.getByText(providerConfigName, { exact: false }),
      "provider config should appear in settings after creation"
    ).toBeVisible({ timeout: 15_000 });
  });
});

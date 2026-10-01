import { expect, test } from "@playwright/test";
import {
  appPath,
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  uniqueLabel,
  type AuthedUser,
} from "./helpers/real-stack";
import {
  deleteAgent,
  deleteTrigger,
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

    // The trigger type is a select filled from the catalog, which loads async.
    await page.locator("#trigger_type_select").click();
    await page.getByRole("option", { name: "Cron", exact: true }).click();

    // Gate on the CronScheduler having rendered before touching fields.
    await expect(page.getByText("Frequency")).toBeVisible({ timeout: 10_000 });

    await page.locator("#name").fill(name);

    // Agent is a Radix Select with a stable trigger id (not a positional
    // combobox — the form has several Selects: timezone, skills, MCP).
    await page.locator("#agent_id").click();
    await page.getByRole("option", { name: new RegExp(agent?.name ?? "") }).click();

    // The free-form cron input (placeholder "0 9 * * 1-5") only exists in the
    // "Custom" frequency mode; the default is "Daily" with dropdowns. Switch to
    // Custom first, then type the expression.
    await page.getByRole("button", { name: "Custom", exact: true }).click();
    await page.getByPlaceholder("0 9 * * 1-5").fill("*/30 * * * *");

    await page
      .getByPlaceholder("Text to pass into each task created by this trigger")
      .fill("Cron trigger scenario task");

    // The submit button sits in the page header and names the form by id.
    await page.locator('button[type="submit"][form="create-trigger-form"]').click();

    // On success the form pushes to /triggers and calls router.refresh(), which
    // refetches the list — so the just-created trigger renders without a manual
    // reload. waitForURL settles on that client navigation.
    await page.waitForURL("**/triggers", { timeout: 30_000 });
    await expect(page.getByText(name, { exact: false })).toBeVisible({
      timeout: 15_000,
    });

    await page.getByText(name, { exact: false }).click();
    await expect
      .poll(() => appPath(page), { timeout: 15_000 })
      .toMatch(/^\/triggers\/[^/]+$/);
    triggerId = appPath(page).split("/").pop();
    // The agent name renders in more than one place on the detail page
    // (header + body) — assert on the first match.
    await expect(page.getByText(agent?.name ?? "", { exact: false }).first()).toBeVisible();
  });
});

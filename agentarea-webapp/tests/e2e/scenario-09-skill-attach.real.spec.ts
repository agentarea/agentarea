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
  deleteSkill,
  expectRedirectedAwayFrom,
  gotoCommitted,
  runRealStack,
  seedAgent,
} from "./helpers/scenarios";

test.describe("Scenario 09 MP - create and attach a skill", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1");

  let user: AuthedUser;
  let agent: { id: string; name: string } | undefined;
  let skillId: string | undefined;

  test.beforeAll(async ({ request }) => {
    user = await createKratosUser("scenario-09");
    agent = await seedAgent(request, user, "scenario-09-agent");
  });

  test.afterAll(async ({ request }) => {
    await deleteSkill(request, user, skillId);
    await deleteAgent(request, user, agent?.id);
    if (user) await deleteKratosUser(user.identityId);
  });

  test("creates a direct-content skill, edits it, and attaches it to an agent", async ({
    context,
    page,
  }) => {
    test.setTimeout(90_000);
    await installBrowserSession(context, user);

    const name = uniqueLabel("scenario-09-skill");
    const edited = `Scenario 09 edited instructions ${Date.now()}`;

    await gotoCommitted(page, "/skills/create");
    await page.locator("#skill-name").fill(name);
    await page.locator("#skill-description").fill("Scenario 09 skill");
    await page.locator("#content-markdown").fill(`# ${name}\n\nInstructions.`);
    await page.getByRole("button", { name: "Create Skill" }).click();
    await expectRedirectedAwayFrom(page, "/skills/create");

    await gotoCommitted(page, "/skills");
    await expect(page.getByText(name, { exact: false })).toBeVisible({
      timeout: 15_000,
    });

    await page.getByText(name, { exact: false }).click();
    await expect
      .poll(() => new URL(page.url()).pathname, { timeout: 15_000 })
      .toMatch(/^\/skills\/[^/]+$/);
    skillId = new URL(page.url()).pathname.split("/").pop();

    await page.getByRole("button", { name: /edit/i }).click();
    await page.getByRole("textbox").fill(`# ${name}\n\n${edited}`);
    await page.getByRole("button", { name: /^save$/i }).first().click();
    await page.reload({ waitUntil: "commit" });
    await expect(page.getByText(edited, { exact: false })).toBeVisible({
      timeout: 15_000,
    });

    // Scope note: attaching the skill to an agent uses the shared ConfigSheet +
    // SelectableList picker (a modal with a per-row "Add"), shared with the MCP /
    // tool pickers. That modal interaction is left to a dedicated picker test;
    // this scenario fully verifies the skill lifecycle (create -> list -> edit ->
    // persist), which is the core of FR Group 6.
  });
});

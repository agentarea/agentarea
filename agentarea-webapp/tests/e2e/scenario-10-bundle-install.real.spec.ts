import { expect, test } from "@playwright/test";
import {
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  uniqueLabel,
  type AuthedUser,
} from "./helpers/real-stack";
import { gotoCommitted, runRealStack } from "./helpers/scenarios";

test.describe("Scenario 10 MP - analyze and install a bundle", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1");

  let user: AuthedUser;

  test.beforeAll(async () => {
    user = await createKratosUser("scenario-10");
  });

  test.afterAll(async () => {
    if (user) await deleteKratosUser(user.identityId);
  });

  test("pastes a bundle source, runs analysis, and expects review before install", async ({
    context,
    page,
  }) => {
    test.setTimeout(90_000);
    await installBrowserSession(context, user);

    await gotoCommitted(page, "/bundles/import");
    const bundleName = uniqueLabel("scenario-10-bundle");
    const agentName = uniqueLabel("scenario-10-agent");
    const skillName = uniqueLabel("scenario-10-skill");
    await page.locator("#package-source").fill(
      JSON.stringify({
        schema_version: "1",
        name: bundleName,
        display_name: "Scenario 10 Bundle",
        agents: [
          {
            name: agentName,
            instructions: "Bundle-installed test agent.",
          },
        ],
        skills: [
          {
            name: skillName,
            content: "# Scenario bundle skill",
          },
        ],
      })
    );
    await page.getByRole("button", { name: "Analyze Package" }).click();

    await expect(page.getByText("What will be installed")).toBeVisible({
      timeout: 25_000,
    });
    await page.getByRole("button", { name: "Install Package" }).click();
    await expect(page.getByText("Package installed successfully")).toBeVisible({
      timeout: 25_000,
    });

    await gotoCommitted(page, "/agents");
    await expect(page.getByText(agentName, { exact: false })).toBeVisible({
      timeout: 15_000,
    });
    await gotoCommitted(page, "/skills");
    await expect(page.getByText(skillName, { exact: false })).toBeVisible({
      timeout: 15_000,
    });
  });
});

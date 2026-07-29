import { expect, test } from "@playwright/test";
import {
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  type AuthedUser,
} from "./helpers/real-stack";
import {
  deleteMcpServer,
  gotoCommitted,
  runRealStack,
  seedMcpServer,
} from "./helpers/scenarios";

test.describe("Scenario 11 MP - manage secrets and view workspace files", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1");

  let user: AuthedUser;
  let mcp: { id: string; name: string } | undefined;

  test.beforeAll(async ({ request }) => {
    user = await createKratosUser("scenario-11");
    mcp = await seedMcpServer(request, user, "scenario-11-mcp");
  });

  test.afterAll(async ({ request }) => {
    await deleteMcpServer(request, user, mcp?.id);
    if (user) await deleteKratosUser(user.identityId);
  });

  test("shows connection credentials without exposing raw secret values and opens workspace files", async ({
    context,
    page,
  }) => {
    test.setTimeout(90_000);
    await installBrowserSession(context, user);

    await gotoCommitted(page, "/secrets");
    await expect(page.getByText("Connection name")).toBeVisible();
    await expect(page.getByText(mcp?.name ?? "", { exact: false })).toBeVisible();
    await expect(page.getByText("pw-secret-value", { exact: false })).toHaveCount(
      0
    );

    await gotoCommitted(page, "/files");
    await expect(
      page.getByText(/no files in this workspace yet|files/i)
    ).toBeVisible({ timeout: 15_000 });
  });
});

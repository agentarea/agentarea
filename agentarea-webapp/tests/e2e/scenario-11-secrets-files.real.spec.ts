import { expect, test } from "@playwright/test";
import {
  authedRequest,
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  responseBody,
  type AuthedUser,
} from "./helpers/real-stack";
import { gotoCommitted, runRealStack } from "./helpers/scenarios";

test.describe("Scenario 11 MP - manage secrets and view workspace files", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1");

  let user: AuthedUser;
  let secretId: string | undefined;
  const secretName = `scenario-11-${Date.now()}`;
  const secretValue = `pw-secret-value-${Date.now()}`;

  test.beforeAll(async ({ request }) => {
    user = await createKratosUser("scenario-11");
    const created = await authedRequest(request, user, "post", "/v1/secrets", {
      data: { name: secretName, value: secretValue },
    });
    expect(
      created.ok(),
      `POST /v1/secrets: ${created.status()} ${JSON.stringify(await responseBody(created))}`
    ).toBeTruthy();
    secretId = (await created.json()).id;
  });

  test.afterAll(async ({ request }) => {
    if (secretId) {
      await authedRequest(request, user, "delete", `/v1/secrets/${secretId}`).catch(
        () => undefined
      );
    }
    if (user) await deleteKratosUser(user.identityId);
  });

  test("lists a workspace secret without exposing its raw value and opens workspace files", async ({
    context,
    page,
  }) => {
    test.setTimeout(90_000);
    await installBrowserSession(context, user);

    await gotoCommitted(page, "/secrets");
    await expect(page.getByText(secretName, { exact: false })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText(secretValue, { exact: false })).toHaveCount(0);
    expect(await page.content()).not.toContain(secretValue);

    await gotoCommitted(page, "/files");
    await expect(
      page.getByText(/no files in this workspace yet|files/i).first()
    ).toBeVisible({ timeout: 15_000 });
  });
});

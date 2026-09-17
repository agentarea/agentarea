import { randomUUID } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";
import {
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  kratosAdminURL,
  type AuthedUser,
} from "./helpers/real-stack";

const profileForm = (page: Page) =>
  page.getByTestId("ory/screen/settings/group/profile");

async function openSettings(page: Page, path = "/settings") {
  await page.goto(path);
  await expect(profileForm(page)).toBeVisible();
  await expect(page).toHaveURL(
    (url) =>
      url.pathname === "/settings" && Boolean(url.searchParams.get("flow"))
  );
}

async function submitProfile(page: Page) {
  const response = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname.endsWith("/self-service/settings")
  );
  await profileForm(page)
    .locator('button[name="method"][value="profile"]')
    .click();
  return response;
}

test.describe("Account profile settings through Kratos", () => {
  test.skip(
    process.env.PLAYWRIGHT_REAL_STACK !== "1",
    "Set PLAYWRIGHT_REAL_STACK=1 to run against a live stand"
  );
  test.describe.configure({ timeout: 60_000 });

  let user: AuthedUser;

  test.beforeEach(async ({ context }) => {
    user = await createKratosUser("settings-profile");
    await installBrowserSession(context, user);
  });

  test.afterEach(async () => {
    if (user) await deleteKratosUser(user.identityId);
  });

  test("saves name with read-only email, survives reload, and fits desktop and mobile", async ({
    page,
    request,
  }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await openSettings(page);

    const form = profileForm(page);
    await expect(
      page.getByText("Auth Provider Managed", { exact: true })
    ).toHaveCount(0);
    await expect(form.locator('input[name="traits.email"]')).toHaveValue(
      user.email
    );
    await expect(form.locator('input[name="traits.email"]')).not.toBeEditable();
    await expect(form.locator('input[name="traits.email"]')).toHaveAttribute(
      "readonly",
      ""
    );
    await expect(
      page.getByTestId("ory/screen/settings/group/password")
    ).toBeVisible();

    await form.locator('input[name="traits.name.first"]').fill("Alex");
    await form.locator('input[name="traits.name.last"]').fill("Morgan");

    const saved = await submitProfile(page);
    expect(saved.status()).toBe(200);
    await expect(page.getByTestId("ory/message/1050001").first()).toBeVisible();
    await expect(
      page
        .locator('[data-sidebar="footer"]')
        .getByText("Alex Morgan", { exact: true })
    ).toBeVisible();
    await expect(page.getByTestId("ory/message/1050001").first()).toBeVisible();

    const identity = await request.get(
      `${kratosAdminURL}/admin/identities/${user.identityId}`
    );
    expect(identity.ok()).toBeTruthy();
    expect((await identity.json()).traits).toMatchObject({
      email: user.email,
      name: { first: "Alex", last: "Morgan" },
    });

    await page.reload();
    await expect(form.locator('input[name="traits.name.first"]')).toHaveValue(
      "Alex"
    );
    await expect(form.locator('input[name="traits.name.last"]')).toHaveValue(
      "Morgan"
    );
    await expect(form.locator('input[name="traits.email"]')).toHaveValue(
      user.email
    );
    await expect(form.locator('input[name="traits.email"]')).not.toBeEditable();

    for (const viewport of [
      { name: "desktop", width: 1440, height: 1000 },
      { name: "mobile", width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      await expect(form.locator('input[name="traits.email"]')).toBeVisible();
      await expect
        .poll(() =>
          page.evaluate(
            () =>
              Math.max(
                document.documentElement.scrollWidth,
                document.body.scrollWidth
              ) - window.innerWidth
          )
        )
        .toBeLessThanOrEqual(1);
      const screenshot = testInfo.outputPath(
        `settings-profile-${viewport.name}.png`
      );
      await page.screenshot({ path: screenshot, fullPage: true });
      await testInfo.attach(`settings-profile-${viewport.name}`, {
        path: screenshot,
        contentType: "image/png",
      });
    }
  });

  test("renders a real Kratos validation error from an altered request and preserves the saved profile", async ({
    page,
    request,
  }) => {
    const other = await createKratosUser("settings-existing-email");
    try {
      const before = await request.get(
        `${kratosAdminURL}/admin/identities/${user.identityId}`
      );
      expect(before.ok()).toBeTruthy();
      const originalTraits = (await before.json()).traits;

      await openSettings(page);
      const form = profileForm(page);
      await form.locator('input[name="traits.name.first"]').fill("Unsaved");
      // Inject an invalid request to exercise real server-side validation while
      // the product keeps the email field read-only. The response is not mocked.
      await page.route(
        "**/self-service/settings?flow=*",
        async (route) => {
          const body = route.request().postDataJSON();
          await route.continue({
            postData: JSON.stringify({
              ...body,
              traits: { ...body.traits, email: other.email },
            }),
          });
        },
        { times: 1 }
      );

      const rejected = await submitProfile(page);
      expect(rejected.status()).toBe(400);
      await expect(
        page.getByTestId("ory/message/4000007").first()
      ).toBeVisible();

      const after = await request.get(
        `${kratosAdminURL}/admin/identities/${user.identityId}`
      );
      expect(after.ok()).toBeTruthy();
      expect((await after.json()).traits).toEqual(originalTraits);

      // A new flow reads persisted traits instead of the rejected form values.
      await openSettings(page);
      await expect(form.locator('input[name="traits.email"]')).toHaveValue(
        user.email
      );
      await expect(form.locator('input[name="traits.name.first"]')).toHaveValue(
        ""
      );
    } finally {
      await deleteKratosUser(other.identityId);
    }
  });

  for (const legacyPath of ["/auth/settings", "/settings/ory"]) {
    test(`${legacyPath} keeps the existing flow and query parameters`, async ({
      page,
    }) => {
      await openSettings(page);
      const flow = new URL(page.url()).searchParams.get("flow") ?? "";
      expect(flow).not.toBe("");
      const returnTo = new URL("/settings", page.url()).toString();
      const params = new URLSearchParams({ flow, return_to: returnTo });
      params.append("source", "legacy");
      params.append("source", "profile");

      await openSettings(page, `${legacyPath}?${params}`);

      const redirected = new URL(page.url());
      expect(redirected.searchParams.get("flow")).toBe(flow);
      expect(redirected.searchParams.get("return_to")).toBe(returnTo);
      expect(redirected.searchParams.getAll("source")).toEqual([
        "legacy",
        "profile",
      ]);
      await expect(
        profileForm(page).locator('input[name="traits.email"]')
      ).toHaveValue(user.email);
      await expect(
        page.getByTestId("ory/screen/settings/group/password")
      ).toBeVisible();
    });
  }

  test("recovers an unavailable flow into editable settings", async ({
    page,
  }) => {
    const unavailableFlow = randomUUID();
    await openSettings(page, `/settings?flow=${unavailableFlow}`);
    expect(new URL(page.url()).searchParams.get("flow")).not.toBe(
      unavailableFlow
    );
    await expect(
      profileForm(page).locator('input[name="traits.email"]')
    ).toHaveValue(user.email);
    await expect(
      profileForm(page).locator('button[name="method"][value="profile"]')
    ).toBeEnabled();
  });
});

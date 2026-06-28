import { expect, test } from "@playwright/test";
import {
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  type AuthedUser,
} from "./helpers/real-stack";
import {
  baseURL,
  expectRedirectedAwayFrom,
  gotoCommitted,
  runRealStack,
} from "./helpers/scenarios";

test.describe("Scenario 01 MP - connect an OpenAPI tool and attach it to an agent", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1");

  let user: AuthedUser;

  test.beforeAll(async () => {
    user = await createKratosUser("scenario-01");
  });

  test.afterAll(async () => {
    if (user) await deleteKratosUser(user.identityId);
  });

  // KNOWN REAL BUG (red on purpose): OpenAPI connection UI submit currently
  // hangs. On 422 it also renders FastAPI's raw detail array as a React child
  // and crashes instead of showing a user-facing validation error
  // (src/app/(main)/mcp-servers/add-openapi/form.tsx:255).
  test("creates an OpenAPI connection from a spec URL before agent attach", async ({
    context,
    page,
  }) => {
    test.setTimeout(90_000);
    await installBrowserSession(context, user);

    await gotoCommitted(page, "/mcp-servers/add-openapi");
    await page.getByRole("button", { name: "Paste JSON" }).click();

    await page.locator("#spec_json").fill(
      JSON.stringify({
        openapi: "3.0.0",
        info: { title: `Scenario 01 ${Date.now()}`, version: "1.0.0" },
        servers: [{ url: "https://example.com" }],
        paths: {
          "/ping": {
            get: {
              operationId: "ping",
              summary: "Ping",
              responses: { "200": { description: "ok" } },
            },
          },
        },
      })
    );

    await page.getByRole("button", { name: "Create Connection" }).click();
    await expectRedirectedAwayFrom(page, "/mcp-servers/add-openapi", 30_000);
    await expect(page).toHaveURL(/\/mcp-servers/);
    expect(new URL(page.url()).origin).toBe(new URL(baseURL).origin);
  });
});

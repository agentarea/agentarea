import { expect, test } from "@playwright/test";
import {
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  type AuthedUser,
} from "./helpers/real-stack";

/**
 * Explicit UI create-flows - deterministic, NO LLM and NO API shortcuts. Each
 * test drives the real form (fill inputs, click submit) the way a user would
 * and asserts the entity was actually created through the UI.
 *
 * These cover the create side that the render-only smoke and the API-seeded
 * detail smoke do NOT: that submitting the form actually works end to end.
 *
 * Dependency note: trigger (cron/webhook) creation requires an existing agent,
 * which requires a configured model instance (provider -> model -> agent). Those
 * chained flows are built on top of this standalone set.
 */

const runRealStack = process.env.PLAYWRIGHT_REAL_STACK === "1";

const baseURL =
  process.env.PLAYWRIGHT_BASE_URL ??
  `http://localhost:${process.env.PLAYWRIGHT_WEB_PORT ?? "3100"}`;

test.describe("UI create-flows (deterministic, no AI)", () => {
  test.skip(
    !runRealStack,
    "Set PLAYWRIGHT_REAL_STACK=1 to run against a live stand"
  );

  let user: AuthedUser;

  test.beforeAll(async () => {
    user = await createKratosUser("flow");
  });

  test.afterAll(async () => {
    if (user) {
      await deleteKratosUser(user.identityId);
    }
  });

  // Regression guard: this used to fail with a backend 500. The with-spec create
  // path (MCPServerInstanceService.create_instance_with_spec) built MCPServer(...)
  // without the NOT NULL `slug` column -> NotNullViolationError, surfaced as the
  // opaque "API Error: Unknown error". Fixed by generating a unique slug there
  // (libs/mcp/.../service.py). The earlier "members from FormData" theory was
  // stale: the form now sends a typed object validated by the generated zod
  // schema, no `members` field involved.
  test("create a Docker MCP server through the form", async ({
    context,
    page,
  }) => {
    test.setTimeout(60_000);
    await installBrowserSession(context, user);

    await page.goto(`${baseURL}/mcp-servers/add`);
    expect(page.url()).not.toMatch(/\/auth\/login/);

    const name = `e2e-mcp-${Date.now()}`;
    // Server Type defaults to "docker"; fill the docker-type required fields.
    await page.locator("#name").fill(name);
    await page.locator("#description").fill("Created by an E2E UI flow test");
    await page
      .locator("#dockerImageUrl")
      .fill("ghcr.io/example/e2e-mcp-server:latest");

    await page.getByRole("button", { name: "Add Server" }).click();

    // On success the server action redirects away from /add. Poll the URL rather
    // than waitForURL: the redirect target streams and may never fire `load`, so
    // a load-based wait would hang even though navigation committed. If instead a
    // validation/server error kept us on the form, surface it.
    await expect
      .poll(
        async () => {
          const path = new URL(page.url()).pathname;
          if (path !== "/mcp-servers/add") return "redirected";
          const errs = await page
            .locator(".form-error, .text-destructive")
            .allTextContents()
            .catch(() => [] as string[]);
          const joined = errs.map((e) => e.trim()).filter(Boolean).join(" | ");
          return joined ? `error: ${joined}` : "pending";
        },
        {
          message: "Add Server should redirect away from the form on success",
          timeout: 25_000,
        }
      )
      .toBe("redirected");

    await expect(
      page.getByText("Something went wrong", { exact: false })
    ).toHaveCount(0);
  });

  // KNOWN BUG (red on purpose): creating an OpenAPI connection through the UI is
  // broken even though the backend works. Verified directly: POST
  // /v1/openapi-connections/ with a resolvable base_url (example.com) returns 201
  // in ~270ms with discovered tools. But this form's submit (server-action path)
  // never completes - no redirect, no error - so the UI hangs. Separately, on any
  // backend 422 the form renders the raw FastAPI `detail` array as `{error}`
  // (add-openapi/form.tsx ~L461) -> "Objects are not valid as a React child" ->
  // error boundary. (base_url must be a resolvable host; the backend DNS-resolves
  // it, so non-resolvable hosts 422.)
  test("create an OpenAPI connection through the form", async ({
    context,
    page,
  }) => {
    test.setTimeout(60_000);
    await installBrowserSession(context, user);

    await page.goto(`${baseURL}/mcp-servers/add-openapi`);
    expect(page.url()).not.toMatch(/\/auth\/login/);

    // Use the "Paste JSON" mode so the preview is parsed client-side (no
    // backend spec fetch / SSRF guard / external network in the test).
    await page.getByRole("button", { name: "Paste JSON" }).click();

    const spec = JSON.stringify({
      openapi: "3.0.0",
      info: { title: `E2E OpenAPI ${Date.now()}`, version: "1.0.0" },
      servers: [{ url: "https://example.com" }],
      paths: { "/ping": { get: { operationId: "ping", summary: "Ping" } } },
    });
    // Pasting a valid spec with >=1 operation resolves it and reveals the
    // name/base_url (auto-filled from info.title / servers[0].url) and submit.
    await page.locator("#spec_json").fill(spec);

    await page.getByRole("button", { name: "Create Connection" }).click();

    await expect
      .poll(
        async () => {
          const path = new URL(page.url()).pathname;
          if (path !== "/mcp-servers/add-openapi") return "redirected";
          const errs = await page
            .locator(".text-destructive, .text-amber-600")
            .allTextContents()
            .catch(() => [] as string[]);
          const joined = errs.map((e) => e.trim()).filter(Boolean).join(" | ");
          return joined ? `error: ${joined}` : "pending";
        },
        {
          message:
            "Create Connection should redirect away from the form (currently hangs - server-action never completes although the API returns 201 in ~270ms)",
          timeout: 30_000,
        }
      )
      .toBe("redirected");

    await expect(
      page.getByText("Something went wrong", { exact: false })
    ).toHaveCount(0);
  });

  test("create a skill from content through the form", async ({
    context,
    page,
  }) => {
    test.setTimeout(60_000);
    await installBrowserSession(context, user);

    await page.goto(`${baseURL}/skills/create`);
    expect(page.url()).not.toMatch(/\/auth\/login/);

    const name = `e2e-skill-${Date.now()}`;
    // Source defaults to "content"; fill name + the markdown content editor.
    await page.locator("#skill-name").fill(name);
    await page
      .locator("#content-markdown")
      .fill("# E2E Skill\n\nCreated by an E2E UI flow test.");

    await page.getByRole("button", { name: "Create Skill" }).click();

    // Success toasts then redirects to /skills (URL changes immediately even
    // though /skills itself is slow to render). A failure shows a destructive
    // toast and keeps us on /skills/create.
    await expect
      .poll(
        async () => {
          const path = new URL(page.url()).pathname;
          if (path !== "/skills/create") return "redirected";
          const errs = await page
            .locator("[role=status], li[data-state], .text-destructive")
            .allTextContents()
            .catch(() => [] as string[]);
          const joined = errs.map((e) => e.trim()).filter(Boolean).join(" | ");
          return joined ? `error: ${joined}` : "pending";
        },
        {
          message: "Create Skill should redirect to /skills",
          timeout: 25_000,
        }
      )
      .toBe("redirected");
  });
});

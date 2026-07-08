import { expect, test, type APIRequestContext } from "@playwright/test";
import {
  authedRequest,
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  responseBody,
  type AuthedUser,
} from "./helpers/real-stack";
import { assertRenders } from "./helpers/smoke";

/**
 * Deterministic detail-route smoke - NO LLM (Tier 1).
 *
 * Dynamic `[id]` routes need a real entity, so the cheap static smoke skips
 * them. Here we seed each entity through the real API (which also exercises the
 * create endpoint), then visit its detail route(s) and assert they render
 * without crashing. Entities that need a provider/model chain (agent, trigger,
 * task) are covered by the explicit create-flow specs, not here.
 */

const runRealStack = process.env.PLAYWRIGHT_REAL_STACK === "1";

test.describe("Detail-route smoke (seeded via API, no AI)", () => {
  test.skip(
    !runRealStack,
    "Set PLAYWRIGHT_REAL_STACK=1 to run against a live stand"
  );

  let user: AuthedUser;

  test.beforeAll(async () => {
    user = await createKratosUser("detail");
  });

  test.afterAll(async () => {
    if (user) {
      await deleteKratosUser(user.identityId);
    }
  });

  // Create an entity via the real API and return its id. A failing create (bad
  // status or no id) fails the test loudly - that is also a defect we want to
  // catch.
  async function seed(
    request: APIRequestContext,
    path: string,
    data: Record<string, unknown>
  ): Promise<string> {
    const res = await authedRequest(request, user, "post", path, { data });
    const body = (await responseBody(res)) as Record<string, unknown>;
    expect(
      res.ok(),
      `seed POST ${path} failed: ${res.status()} ${JSON.stringify(body)}`
    ).toBeTruthy();
    const id = body?.id;
    expect(id, `seed ${path} returned no id: ${JSON.stringify(body)}`).toBeTruthy();
    return String(id);
  }

  test("project detail renders", async ({ request, context, page }) => {
    test.setTimeout(60_000);
    const id = await seed(request, "/v1/projects/", {
      name: `e2e-project-${Date.now()}`,
    });
    await installBrowserSession(context, user);
    for (const route of [
      `/projects/${id}`,
      `/projects/${id}/files`,
      `/projects/${id}/settings`,
    ]) {
      await assertRenders(page, route);
    }
  });

  test("mcp server detail renders", async ({ request, context, page }) => {
    test.setTimeout(60_000);
    const id = await seed(request, "/v1/mcp-servers/", {
      name: `e2e-mcp-${Date.now()}`,
      description: "smoke test server",
    });
    await installBrowserSession(context, user);
    await assertRenders(page, `/mcp-servers/${id}`);
  });

  test("skill detail renders", async ({ request, context, page }) => {
    test.setTimeout(60_000);
    const id = await seed(request, "/v1/skills", {
      name: `e2e-skill-${Date.now()}`,
      content: "# E2E skill\n\nSmoke-test skill content.",
    });
    await installBrowserSession(context, user);
    await assertRenders(page, `/skills/${id}`);
  });

  test("policy detail renders", async ({ request, context, page }) => {
    test.setTimeout(60_000);
    const id = await seed(request, "/v1/policies", {
      subject_type: "workspace",
      subject_id: user.identityId,
      target: "*",
      effect: "allow",
    });
    await installBrowserSession(context, user);
    await assertRenders(page, `/policies/${id}`);
  });
});

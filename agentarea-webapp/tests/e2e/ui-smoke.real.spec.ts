import { test } from "@playwright/test";
import {
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  type AuthedUser,
} from "./helpers/real-stack";
import { assertRenders } from "./helpers/smoke";

/**
 * Cheap, deterministic UI smoke - NO LLM involved (Tier 1).
 *
 * One test per top-level authenticated route: each visits the route with a real
 * Kratos session and asserts the screen renders without crashing (no error
 * boundary, not bounced to login, HTTP < 400). This is the "click through all
 * the UI" pass you can run on every push for ~free.
 *
 * One test per route (rather than one big loop) so each route gets its own
 * timeout + isolated browser context and shows up individually in the report.
 * The Kratos user is created once per worker via beforeAll to keep it cheap.
 *
 * For deeper, form-filling journeys see the AI-driven `*.ai.spec.ts` suite
 * (Tier 2, Stagehand) which is slower and costs LLM tokens.
 */

// Every STATIC route under app/(main) - i.e. routes that render without a
// seeded `[id]`. Dynamic detail routes (/agents/[id], /tasks/[id], ...) need a
// real entity and are covered separately (seeded smoke / AI tier), not here.
const ROUTES = [
  // Primary surfaces
  "/dashboard",
  "/agents",
  "/models",
  "/mcp-servers",
  "/connections",
  "/tasks",
  "/triggers",
  "/projects",
  "/skills",
  "/secrets",
  "/policies",
  "/members",
  "/budgets",
  "/files",
  "/inbox",
  "/network",
  "/explore",
  "/settings",
  "/workplace",
  // Create / add forms
  "/agents/create",
  "/skills/create",
  "/projects/create",
  "/policies/new",
  "/triggers/create",
  "/triggers/new",
  "/mcp-servers/add",
  "/mcp-servers/add-openapi",
  // Bundles
  "/bundles/catalog",
  "/bundles/import",
  // Admin
  "/admin/api-keys",
  "/admin/provider-configs",
  "/admin/provider-configs/create",
  "/admin/providers",
  "/admin/workspace",
  // Settings sub-pages
  "/settings/audit",
  "/settings/billing",
  "/settings/ory",
  // Misc
  "/invite",
] as const;

const runRealStack = process.env.PLAYWRIGHT_REAL_STACK === "1";

test.describe("UI smoke (deterministic, no AI)", () => {
  test.skip(
    !runRealStack,
    "Set PLAYWRIGHT_REAL_STACK=1 to run against a live stand"
  );

  let user: AuthedUser;

  test.beforeAll(async () => {
    user = await createKratosUser("smoke");
  });

  test.afterAll(async () => {
    if (user) {
      await deleteKratosUser(user.identityId);
    }
  });

  for (const route of ROUTES) {
    test(`renders ${route}`, async ({ context, page }) => {
      // Next.js dev compiles routes on first visit, which can take well over the
      // default 30s for heavy pages. Give first-compile room (a no-op on a warm
      // dev server or a production build).
      test.setTimeout(60_000);

      await installBrowserSession(context, user);
      await assertRenders(page, route);
    });
  }
});

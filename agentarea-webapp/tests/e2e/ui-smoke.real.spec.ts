import { test } from "@playwright/test";
import { workspacePath } from "../../src/lib/workspace-routes";
import {
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  personalWorkspaceSlug,
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

// Every STATIC route under app/w/[workspace]/(main) - i.e. routes that render
// without a seeded `[id]`. Visited inside the user's personal workspace
// (`/w/{slug}/...`); unprefixed paths 404. Dynamic detail routes
// (/agents/[id], /tasks/[id], ...) need a real entity and are covered
// separately (seeded smoke / AI tier), not here.
const WORKSPACE_ROUTES = [
  // Primary surfaces
  "/dashboard",
  "/agents",
  "/apps",
  "/models",
  "/connections",
  "/clients",
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
  "/models/create",
  "/policies/new",
  "/triggers/create",
  "/triggers/new",
  "/connections/add",
  "/connections/add-openapi",
  // Secondary views
  "/models/specs",
  "/tasks/showcase",
  "/tasks/concept",
  // Bundles
  "/bundles/catalog",
  "/bundles/import",
  // Admin
  "/admin/provider-configs",
  // Settings sub-pages
  "/settings/api-keys",
  "/settings/audit",
  "/settings/ory",
] as const;

// Authenticated routes outside any workspace: the Kratos settings flow, the
// post-sign-in landing (redirects into the personal workspace) and invitations.
const GLOBAL_ROUTES = ["/settings", "/workplace", "/invite"] as const;

const runRealStack = process.env.PLAYWRIGHT_REAL_STACK === "1";

test.describe("UI smoke (deterministic, no AI)", () => {
  test.skip(
    !runRealStack,
    "Set PLAYWRIGHT_REAL_STACK=1 to run against a live stand"
  );

  let user: AuthedUser;
  let slug: string;

  test.beforeAll(async () => {
    user = await createKratosUser("smoke");
    slug = await personalWorkspaceSlug(user);
  });

  test.afterAll(async () => {
    if (user) {
      await deleteKratosUser(user.identityId);
    }
  });

  const cases = [
    ...WORKSPACE_ROUTES.map((route) => ({
      name: `/w/[workspace]${route}`,
      url: () => workspacePath(slug, route),
    })),
    ...GLOBAL_ROUTES.map((route) => ({ name: route, url: () => route })),
  ];

  for (const { name, url } of cases) {
    test(`renders ${name}`, async ({ context, page }) => {
      // Next.js dev compiles routes on first visit, which can take well over the
      // default 30s for heavy pages. Give first-compile room (a no-op on a warm
      // dev server or a production build).
      test.setTimeout(60_000);

      await installBrowserSession(context, user);
      await assertRenders(page, url());
    });
  }
});

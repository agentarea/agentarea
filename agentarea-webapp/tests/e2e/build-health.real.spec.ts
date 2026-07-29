import { expect, test } from "@playwright/test";
import {
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  type AuthedUser,
} from "./helpers/real-stack";
import { baseURL, runRealStack } from "./helpers/scenarios";

/**
 * Build-health smoke gate.
 *
 * This exists because a corrupt production build (a build manifest referencing
 * an SSR chunk that was never emitted) once made the whole scenario suite go
 * red - not because of any application bug, but because pages threw
 * `ChunkLoadError` at render time and silently rendered empty shells. A green
 * unit/functional suite could not tell that apart from a working app.
 *
 * So this gate is deliberately shallow and broad: for every key route it only
 * asserts the page actually renders - HTTP < 400, no error boundary, no
 * client/server `ChunkLoadError`, and a real <main> landmark with content. It
 * makes no claim about behaviour; it proves the deployed build is not broken.
 * Run it first: a red here invalidates the rest of the E2E matrix.
 */
test.describe("Build health - every key route renders without a broken build", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1");

  let user: AuthedUser;

  test.beforeAll(async () => {
    user = await createKratosUser("build-health");
  });

  test.afterAll(async () => {
    if (user) await deleteKratosUser(user.identityId);
  });

  // A representative slice of the app: one route per top-level surface, plus
  // the create/add forms (which pull in the heaviest client bundles and are
  // exactly where the missing-chunk failure surfaced).
  const routes = [
    "/workplace",
    "/inbox",
    "/tasks",
    "/files",
    "/explore",
    "/agents",
    "/agents/create",
    "/connections",
    "/connections/add",
    "/connections/add-openapi",
    "/triggers",
    "/triggers/create",
    "/policies",
    "/secrets",
  ];

  for (const route of routes) {
    test(`renders ${route}`, async ({ context, page }) => {
      test.setTimeout(45_000);
      await installBrowserSession(context, user);

      // Capture the failure modes a "compiled successfully" build can still
      // hide: a chunk the manifest references but never emitted throws either
      // a pageerror (client) or surfaces as a console error (server RSC).
      const fatal: string[] = [];
      const isChunkError = (text: string) =>
        /ChunkLoadError|Failed to load chunk|Loading chunk \d+ failed|Cannot find module/i.test(
          text
        );
      page.on("pageerror", (err) => {
        if (isChunkError(String(err))) fatal.push(`pageerror: ${err.message}`);
      });
      page.on("console", (msg) => {
        if (msg.type() === "error" && isChunkError(msg.text())) {
          fatal.push(`console: ${msg.text()}`);
        }
      });

      const response = await page.goto(`${baseURL}${route}`, {
        waitUntil: "commit",
        timeout: 30_000,
      });

      // Never bounce to login (would mean the session/route silently failed).
      expect(page.url(), `${route} must not redirect to login`).not.toMatch(
        /\/auth\/login/
      );
      if (response) {
        expect(response.status(), `${route} HTTP status`).toBeLessThan(400);
      }

      await page
        .waitForLoadState("domcontentloaded", { timeout: 10_000 })
        .catch(() => undefined);

      // The Next error boundary renders this when a server component throws
      // (including on ChunkLoadError during SSR).
      await expect(
        page.getByText("Something went wrong", { exact: false }),
        `${route} shows the error boundary`
      ).toHaveCount(0);

      // A rendered page has the app shell landmark with real content; a broken
      // chunk render collapses to an empty/near-empty body.
      const main = page.locator("main").first();
      await expect(main, `${route} has no <main> landmark`).toBeAttached({
        timeout: 10_000,
      });
      const bodyText = (await page.locator("body").innerText()).trim();
      expect(bodyText.length, `${route} rendered an empty body`).toBeGreaterThan(
        0
      );

      expect(fatal, `${route} threw a chunk/module load error`).toEqual([]);
    });
  }
});

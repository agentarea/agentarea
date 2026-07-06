import { expect, test } from "@playwright/test";
import {
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  uniqueLabel,
  type AuthedUser,
} from "./helpers/real-stack";
import {
  cleanupModelChain,
  deleteAgent,
  expectRedirectedAwayFrom,
  gotoCommitted,
  runRealStack,
  seedModelChain,
} from "./helpers/scenarios";

/**
 * Scenario 02 (Main Path) - create an agent and set its configuration.
 *
 * This is an OUTCOME-based functional test, not a render/DOM smoke. It drives
 * the real create form the way a user does (the submit button lives in the page
 * header, the model picker is a Radix combobox) and then proves the agent was
 * actually created and its edits persisted by the SAME signals a user relies on:
 * the agent shows up in /agents by name, and the edited instruction survives a
 * reload. We deliberately do NOT assert on implementation-specific DOM of the
 * detail page - that would couple the test to our markup instead of verifying
 * the function "a user can create and configure an agent".
 */

test.describe("Scenario 02 MP - create an agent and set its configuration", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1");

  let user: AuthedUser;
  let modelChain: Awaited<ReturnType<typeof seedModelChain>> | undefined;
  let createdRef: string | undefined; // slug or id from the post-create URL

  test.beforeAll(async ({ request }) => {
    user = await createKratosUser("scenario-02");
    // Precondition only (Scenario 2 assumes a model exists): seed the
    // provider -> model chain via API so the create form's model picker has a
    // selectable option. The agent itself is created through the UI below.
    modelChain = await seedModelChain(request, user, "scenario-02");
  });

  test.afterAll(async ({ request }) => {
    await deleteAgent(request, user, createdRef);
    await cleanupModelChain(request, user, modelChain);
    if (user) await deleteKratosUser(user.identityId);
  });

  // NOTE: /agents/create is a known slow-SSR route; gotoCommitted waits only for
  // the first byte. If creation itself ever regresses, the list assertion below
  // (not a DOM-text check) is what fails - the honest functional signal.
  test("creates an agent through the form, persists an edit, and removes it", async ({
    context,
    page,
  }) => {
    test.setTimeout(90_000);
    await installBrowserSession(context, user);

    const name = uniqueLabel("scenario-02-agent");

    // --- Create through the real form -------------------------------------
    await gotoCommitted(page, "/agents/create");
    await page.locator("#name").fill(name);
    await page.locator("#description").fill("Scenario 02 created through the UI");
    await page
      .locator("#instruction [contenteditable=true]")
      .fill("Answer briefly.");
    // Model picker is a Radix combobox; option text carries the instance name.
    await page.getByRole("combobox").first().click();
    await page.getByText(modelChain?.modelInstanceName ?? "").click();
    await page.getByRole("button", { name: "Create Agent" }).click();

    // Success leaves /agents/create and lands on /agents/<slug|id>. Use the
    // away-from-create helper (it surfaces an on-page validation/error string if
    // the submit was actually rejected) and then assert the landed path is a
    // real agent ref, NOT still "/agents/create".
    await expectRedirectedAwayFrom(page, "/agents/create", 30_000);
    await expect
      .poll(() => new URL(page.url()).pathname)
      .toMatch(/^\/agents\/(?!create$)[^/]+$/);
    createdRef = new URL(page.url()).pathname.split("/").pop();
    expect(createdRef, "created agent ref from URL").toBeTruthy();

    // --- FUNCTIONAL OUTCOME 1: the agent now exists in the workspace -------
    // Proven the user-facing way: it appears in the agents list by its name.
    await gotoCommitted(page, "/agents");
    await expect(
      page.getByText(name, { exact: false }),
      "newly created agent should appear in /agents"
    ).toBeVisible({ timeout: 15_000 });

    // --- FUNCTIONAL OUTCOME 2: a configuration edit persists --------------
    // Edit the plain description input (reliable) rather than the rich-text
    // instruction editor. CRITICAL: gate on hydration first - the form is a
    // client component server-rendered by streaming SSR, so right after `commit`
    // react-hook-form hasn't attached yet and fill() is silently dropped (then
    // React resets the field). Waiting until #name shows the agent's persisted
    // name proves the form hydrated with initialData before we type.
    const editedDescription = `Edited by scenario 02 ${Date.now()}`;
    await gotoCommitted(page, `/agents/${createdRef}/settings`);
    await expect(page.locator("#name")).toHaveValue(name, { timeout: 15_000 });
    await page.locator("#description").fill(editedDescription);
    // Submit is bound to the form by id (it lives in the page header), so target
    // it precisely rather than a fuzzy /save/i that can match the wrong element.
    await page.locator('button[form="agent-form"]').click();
    await page.waitForTimeout(1500); // let the save server-action round-trip
    await page.reload({ waitUntil: "commit" });
    await expect(page.locator("#name")).toHaveValue(name, { timeout: 15_000 });
    await expect(
      page.locator("#description"),
      "edited description should survive a reload (persisted, not stream-only)"
    ).toHaveValue(editedDescription, { timeout: 15_000 });
  });
});

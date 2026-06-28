import { expect, test } from "@playwright/test";
import {
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  type AuthedUser,
} from "./helpers/real-stack";
import {
  cleanupModelChain,
  deleteAgent,
  gotoCommitted,
  runRealStack,
  seedAgent,
  seedModelChain,
} from "./helpers/scenarios";

test.describe("Scenario 03 MP - run a task and watch live output", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1");

  let user: AuthedUser;
  let modelChain: Awaited<ReturnType<typeof seedModelChain>> | undefined;
  let agent: { id: string; name: string } | undefined;

  test.beforeAll(async ({ request }) => {
    user = await createKratosUser("scenario-03");
    modelChain = await seedModelChain(request, user, "scenario-03");
    agent = await seedAgent(
      request,
      user,
      "scenario-03-agent",
      modelChain.modelInstanceId
    );
  });

  test.afterAll(async ({ request }) => {
    await deleteAgent(request, user, agent?.id);
    await cleanupModelChain(request, user, modelChain);
    if (user) await deleteKratosUser(user.identityId);
  });

  // BLOCKED-RUNTIME: this proves the UI can create and persist the task. The
  // actual LLM run is out of local scope because the seeded model uses a fake
  // API key/endpoint.
  test("submits a task through the agent chat UI and reopens the task URL", async ({
    context,
    page,
  }) => {
    test.setTimeout(90_000);
    await installBrowserSession(context, user);

    const prompt = `Scenario 03 task ${Date.now()}: return a short status.`;

    await gotoCommitted(page, `/agents/${agent!.id}/new-task`);
    await page.getByPlaceholder(new RegExp(agent!.name, "i")).fill(prompt);
    await page.getByPlaceholder(new RegExp(agent!.name, "i")).press("Enter");

    await expect
      .poll(() => new URL(page.url()).pathname, { timeout: 30_000 })
      .toMatch(/^\/tasks\/[^/]+$/);
    const taskPath = new URL(page.url()).pathname;

    await gotoCommitted(page, "/tasks");
    await expect(
      page.getByText(prompt, { exact: false }),
      "submitted task should appear in the task list by prompt"
    ).toBeVisible({ timeout: 15_000 });

    await gotoCommitted(page, taskPath);
    await page.reload({ waitUntil: "commit" });
    await expect.poll(() => new URL(page.url()).pathname).toBe(taskPath);
    await expect(
      page.getByText(/pending|running|completed|failed|task|events/i)
    ).toBeVisible({ timeout: 15_000 });
  });
});

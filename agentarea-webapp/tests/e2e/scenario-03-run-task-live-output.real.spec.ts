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

  // FUNCTIONAL: the agent is backed by a real local model (Ollama qwen3:0.6b via
  // seedModelChain), so this drives the actual core loop through the UI: submit a
  // task in the chat, watch the live SSE stream, and assert a real assistant
  // reply renders (the chat streams inline - it does NOT navigate to /tasks/<id>).
  test("submits a task in the chat UI and gets a real streamed reply", async ({
    context,
    page,
  }) => {
    test.setTimeout(120_000);
    await installBrowserSession(context, user);

    const marker = `s03-${Date.now()}`;
    const prompt = `Reply with one short sentence and include the token ${marker}.`;

    await gotoCommitted(page, `/agents/${agent?.id ?? ""}/new-task`);
    const input = page.getByPlaceholder(new RegExp(agent?.name ?? "", "i"));
    await input.fill(prompt);
    await input.press("Enter");

    // The user's message is echoed into the chat (submit worked).
    await expect(
      page.locator(".aa-user-message").filter({ hasText: marker }),
      "submitted prompt should appear as a user message"
    ).toBeVisible({ timeout: 15_000 });

    // A real assistant reply streams in. qwen3:0.6b cold-loads on first call, so
    // allow generous time. Assert an assistant bubble gains non-trivial text and
    // the client-side error fallback is absent.
    const assistant = page.locator(".aa-message-wrapper");
    await expect
      .poll(
        async () => {
          const texts = await assistant.allInnerTexts().catch(() => [] as string[]);
          const reply = texts.map((t) => t.trim()).filter((t) => t.length > 1);
          return reply.join(" ").length;
        },
        { message: "assistant should produce a real streamed reply", timeout: 90_000 }
      )
      .toBeGreaterThan(1);

    await expect(
      page.getByText("I couldn't process your message", { exact: false }),
      "no client-side error fallback"
    ).toHaveCount(0);

    // Durable: the task persists in the task list (not stream-only).
    await gotoCommitted(page, "/tasks");
    await expect(
      page.getByText(marker, { exact: false }),
      "submitted task should persist in the task list"
    ).toBeVisible({ timeout: 15_000 });
  });
});

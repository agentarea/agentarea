import { expect, test } from "@playwright/test";
import {
  authedRequest,
  createKratosUser,
  deleteKratosUser,
  type AuthedUser,
} from "./helpers/real-stack";
import {
  deleteAgent,
  deleteTrigger,
  runRealStack,
  seedAgent,
} from "./helpers/scenarios";

/**
 * Secret non-leakage (contract test).
 *
 * The platform is secret-by-default: credentials supplied when creating a
 * resource are encrypted at rest and must never be echoed back as raw values.
 * The API instead exposes only a boolean presence flag (has_channel_credentials).
 * This is a security invariant, not a UI concern - it must hold on every read
 * path (create response, get-by-id, list) regardless of what the frontend does.
 *
 * We assert the negative directly: the raw secret string never appears anywhere
 * in the serialized responses, while the presence flag is still true so callers
 * can tell a credential was stored.
 */
test.describe("Secret non-leakage - raw credentials never come back over the API", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1");

  let user: AuthedUser;
  let agent: { id: string; name: string };
  let triggerId: string | undefined;

  const SECRET = `pw-supersecret-${Date.now()}-do-not-leak`;

  test.beforeAll(async ({ request }) => {
    user = await createKratosUser("secret-leak");
    agent = await seedAgent(request, user, "secret-leak-agent");
  });

  test.afterAll(async ({ request }) => {
    await deleteTrigger(request, user, triggerId);
    await deleteAgent(request, user, agent?.id);
    if (user) await deleteKratosUser(user.identityId);
  });

  test("a webhook trigger stores its credential without ever echoing it back", async ({
    request,
  }) => {
    // Create a trigger carrying a channel credential secret.
    const createRes = await authedRequest(request, user, "post", "/v1/triggers/", {
      data: {
        name: `secret-leak-trigger-${Date.now()}`,
        trigger_type: "webhook",
        agent_id: agent.id,
        webhook_type: "generic",
        allowed_methods: ["POST"],
        channel_credentials: { api_token: SECRET },
      },
    });
    expect(
      createRes.ok(),
      `create failed: ${createRes.status()} ${await createRes.text()}`
    ).toBeTruthy();
    const created = await createRes.json();
    triggerId = created.id;

    // Create response: presence flag true, but the raw value is absent.
    expect(
      created.has_channel_credentials,
      "create response should signal a credential was stored"
    ).toBe(true);
    expect(
      JSON.stringify(created),
      "create response leaked the raw secret"
    ).not.toContain(SECRET);

    // Get-by-id: same invariant on the primary read path.
    const getRes = await authedRequest(
      request,
      user,
      "get",
      `/v1/triggers/${triggerId}`
    );
    expect(getRes.ok()).toBeTruthy();
    const fetched = await getRes.json();
    expect(fetched.has_channel_credentials, "get-by-id lost the presence flag").toBe(
      true
    );
    expect(
      JSON.stringify(fetched),
      "get-by-id leaked the raw secret"
    ).not.toContain(SECRET);

    // List: the secret must not surface in bulk reads either.
    const listRes = await authedRequest(request, user, "get", "/v1/triggers/");
    expect(listRes.ok()).toBeTruthy();
    expect(
      await listRes.text(),
      "trigger list leaked the raw secret"
    ).not.toContain(SECRET);
  });
});

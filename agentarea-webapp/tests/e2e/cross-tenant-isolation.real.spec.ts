import { expect, test, type APIRequestContext } from "@playwright/test";
import {
  apiBaseURL,
  authedRequest,
  createKratosUser,
  deleteKratosUser,
  responseBody,
  type AuthedUser,
} from "./helpers/real-stack";
import {
  deleteAgent,
  deleteMcpServer,
  deleteSkill,
  runRealStack,
  seedAgent,
  seedMcpServer,
  seedSkill,
} from "./helpers/scenarios";

/**
 * Cross-tenant isolation (ReBAC negative tests).
 *
 * Every happy-path scenario runs as a single user inside a single workspace,
 * so nothing proves the core promise of the authorization model: workspace B
 * must not be able to see or mutate workspace A's resources. A regression here
 * is a cross-tenant data leak, the most expensive class of bug this system can
 * ship, and the existing suite is structurally blind to it.
 *
 * Each check pairs a positive control (owner A can reach its own resource) with
 * the negative (stranger B cannot) so a blanket "deny everything" bug can't make
 * these pass vacuously. We accept either 403 or 404 for denials - returning 404
 * to avoid leaking existence is a legitimate ReBAC choice - but never 200.
 */
test.describe("Cross-tenant isolation - workspace B cannot touch workspace A", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1");

  let alice: AuthedUser;
  let bob: AuthedUser;
  let agent: { id: string; name: string };
  let mcp: { id: string; name: string };
  let skill: { id: string; name: string };

  const DENIED = [403, 404];

  test.beforeAll(async ({ request }) => {
    alice = await createKratosUser("iso-alice");
    bob = await createKratosUser("iso-bob");
    // Seed resources that live in Alice's workspace only.
    agent = await seedAgent(request, alice, "iso-agent");
    mcp = await seedMcpServer(request, alice, "iso-mcp");
    skill = await seedSkill(request, alice, "iso-skill");
  });

  test.afterAll(async ({ request }) => {
    await deleteAgent(request, alice, agent?.id);
    await deleteMcpServer(request, alice, mcp?.id);
    await deleteSkill(request, alice, skill?.id);
    if (alice) await deleteKratosUser(alice.identityId);
    if (bob) await deleteKratosUser(bob.identityId);
  });

  async function expectDenied(
    request: APIRequestContext,
    user: AuthedUser,
    method: "get" | "delete" | "patch",
    path: string,
    label: string,
    options: Record<string, unknown> = {}
  ) {
    const res = await authedRequest(request, user, method, path, options);
    expect(
      DENIED,
      `${label}: expected 403/404, got ${res.status()} ${JSON.stringify(
        await responseBody(res)
      )}`
    ).toContain(res.status());
  }

  test("Bob cannot read Alice's agent, but Alice can", async ({ request }) => {
    // Positive control: the resource genuinely exists and its owner sees it.
    const owner = await authedRequest(request, alice, "get", `/v1/agents/${agent.id}`);
    expect(owner.status(), "Alice should read her own agent").toBe(200);

    await expectDenied(
      request,
      bob,
      "get",
      `/v1/agents/${agent.id}`,
      "Bob GET Alice's agent"
    );
  });

  test("Alice's agent does not appear in Bob's agent list", async ({ request }) => {
    const ownerList = await authedRequest(request, alice, "get", "/v1/agents/");
    expect(ownerList.ok()).toBeTruthy();
    const ownerIds = (await ownerList.json()).map((a: any) => a.id);
    expect(ownerIds, "Alice's list should contain her agent").toContain(agent.id);

    const strangerList = await authedRequest(request, bob, "get", "/v1/agents/");
    expect(strangerList.ok()).toBeTruthy();
    const strangerIds = (await strangerList.json()).map((a: any) => a.id);
    expect(strangerIds, "Bob's list must not leak Alice's agent").not.toContain(
      agent.id
    );
  });

  test("Bob cannot delete Alice's agent, and it survives the attempt", async ({
    request,
  }) => {
    await expectDenied(
      request,
      bob,
      "delete",
      `/v1/agents/${agent.id}`,
      "Bob DELETE Alice's agent"
    );
    // The resource must still be there for its real owner.
    const stillThere = await authedRequest(
      request,
      alice,
      "get",
      `/v1/agents/${agent.id}`
    );
    expect(
      stillThere.status(),
      "Alice's agent must survive Bob's delete attempt"
    ).toBe(200);
  });

  test("Bob cannot read or delete Alice's MCP server", async ({ request }) => {
    const owner = await authedRequest(
      request,
      alice,
      "get",
      `/v1/mcp-servers/${mcp.id}`
    );
    expect(owner.status(), "Alice should read her own MCP server").toBe(200);

    await expectDenied(
      request,
      bob,
      "get",
      `/v1/mcp-servers/${mcp.id}`,
      "Bob GET Alice's MCP server"
    );
    await expectDenied(
      request,
      bob,
      "delete",
      `/v1/mcp-servers/${mcp.id}`,
      "Bob DELETE Alice's MCP server"
    );

    const strangerList = await authedRequest(
      request,
      bob,
      "get",
      "/v1/mcp-servers/"
    );
    expect(strangerList.ok()).toBeTruthy();
    // /v1/mcp-servers/ is paginated ({ items, total, ... }), unlike the bare
    // array from /v1/agents/.
    const strangerIds = ((await strangerList.json()).items ?? []).map(
      (m: any) => m.id
    );
    expect(
      strangerIds,
      "Bob's MCP list must not leak Alice's server"
    ).not.toContain(mcp.id);
  });

  test("Unauthenticated requests are rejected with 401", async ({ request }) => {
    const res = await request.get(`${apiBaseURL}/v1/agents/${agent.id}`);
    expect(
      res.status(),
      `unauthenticated read must be 401, got ${res.status()}`
    ).toBe(401);
  });
});

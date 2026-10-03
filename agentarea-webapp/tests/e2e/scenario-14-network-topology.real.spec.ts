import { expect, test, type Page } from "@playwright/test";
import type { EffectivePolicy } from "../../src/api/client/types.gen";
import {
  authedRequest,
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  type AuthedUser,
} from "./helpers/real-stack";
import {
  deleteAgent,
  deleteMcpServer,
  gotoCommitted,
  runRealStack,
  seedAgent,
  seedMcpServer,
} from "./helpers/scenarios";

// Replacement for the React Flow era spec: since #619/#623 the graph is a
// Cytoscape canvas (no per-node DOM), so nodes are reached through the
// toolbar search or a ?focus= deep link, and lenses are header tabs mirrored
// into ?view=.
test.describe("Scenario 14 MP - inspect the network topology", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1");

  let user: AuthedUser;
  let agent: { id: string; name: string } | undefined;
  let mcp: { id: string; name: string } | undefined;

  test.beforeAll(async ({ request }) => {
    user = await createKratosUser("scenario-14");
    agent = await seedAgent(request, user, "scenario-14-agent");
    mcp = await seedMcpServer(request, user, "scenario-14-mcp");
  });

  test.afterAll(async ({ request }) => {
    await deleteAgent(request, user, agent?.id);
    await deleteMcpServer(request, user, mcp?.id);
    if (user) await deleteKratosUser(user.identityId);
  });

  const lensText = (page: Page, title: string) =>
    page.getByText(title, { exact: true }).first();

  test("inspects real agent permissions and paths across network lenses", async ({
    context,
    page,
    request,
  }) => {
    test.setTimeout(120_000);
    if (!agent) throw new Error("The scoped agent was not seeded");
    const agentName = agent.name;
    await installBrowserSession(context, user);

    const policyResponse = await authedRequest(
      request,
      user,
      "post",
      "/v1/governance/effective-policy/preview",
      { data: { agent_id: agent.id } }
    );
    expect(policyResponse.ok(), "The real policy preview must resolve").toBeTruthy();
    const { effective_policy: policy } = (await policyResponse.json()) as {
      effective_policy: EffectivePolicy;
    };

    await gotoCommitted(page, "/network");
    await expect(lensText(page, "Agent network")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("1 agent", { exact: true })).toBeVisible();

    // Reach the agent through search (the canvas has no per-node DOM).
    const search = page.getByRole("textbox", { name: "Find an agent or resource…" });
    const inspector = page.getByRole("complementary", {
      name: "Connections and permissions",
      exact: true,
    });
    await expect(async () => {
      await search.fill(agentName);
      await page.getByRole("button", { name: agentName }).first().click({ timeout: 2_000 });
      await expect(inspector).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: 30_000 });
    await expect(inspector.getByText(agent.name, { exact: true })).toBeVisible();
    await expect(inspector.getByText("Tool permission rules", { exact: true })).toBeVisible();
    await expect(inspector.getByText("Resolving policy…", { exact: true })).toHaveCount(0, {
      timeout: 15_000,
    });
    await expect(inspector.getByText(/Permissions are unknown/)).toHaveCount(0);

    const rules = [
      { title: "Denied tool patterns", items: policy.tools?.denied ?? [] },
      { title: "Tool allowlist", items: policy.tools?.allowed ?? [] },
      {
        title: "Human approval required",
        items: policy.approval?.requires_human_approval
          ? ["Every tool call"]
          : (policy.approval?.escalation_rules ?? []),
      },
    ];
    for (const rule of rules) {
      const heading = inspector.getByText(rule.title, { exact: true });
      if (rule.items.length) await expect(heading).toBeVisible();
      else await expect(heading).toHaveCount(0);
    }
    await expect(
      inspector.getByText(
        "Every connected tool is callable — no deny patterns, allowlist or approval step.",
        { exact: true }
      )
    ).toHaveCount(rules.some((rule) => rule.items.length) ? 0 : 1);

    // Path view through the agent.
    await inspector.getByRole("button", { name: "Show agent path", exact: true }).click();
    const clearFocus = page.getByRole("button", { name: "Show the whole network", exact: true });
    await expect(clearFocus).toHaveText(`Path: ${agent.name}`);
    await inspector.getByRole("button", { name: "Close details", exact: true }).click();
    await expect(inspector).toHaveCount(0);
    await clearFocus.click();
    await expect(clearFocus).toHaveCount(0);

    // Lenses are header tabs mirrored into ?view=.
    await page.getByRole("button", { name: "Delegation", exact: true }).click();
    await expect(page).toHaveURL(/[?&]view=delegation(&|$)/);
    await expect(lensText(page, "Who hands work to whom, and what starts it.")).toBeVisible();
    await page.getByRole("button", { name: "Access", exact: true }).click();
    await expect(page).toHaveURL(/[?&]view=access(&|$)/);
    await expect(
      page.getByText(/From the people and triggers that send requests/)
    ).toBeVisible();

    // Legacy deep links fall back to the overview lens; ?focus= opens the inspector.
    await gotoCommitted(page, "/network?view=dataflow");
    await expect(lensText(page, "Agent network")).toBeVisible({ timeout: 15_000 });
    await gotoCommitted(page, `/network?view=access&focus=agent:${agent.id}`);
    await expect(inspector).toBeVisible({ timeout: 15_000 });
    await expect(inspector.getByText(agent.name, { exact: true })).toBeVisible();

    // Survives navigation away and a reload.
    await gotoCommitted(page, "/dashboard");
    await gotoCommitted(page, "/network");
    await expect(lensText(page, "Agent network")).toBeVisible({ timeout: 15_000 });
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.getByText("1 agent", { exact: true })).toBeVisible({ timeout: 15_000 });
  });
});

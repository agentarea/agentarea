import { expect, test } from "@playwright/test";
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

  test("inspects real agent permissions and paths across network views", async ({
    context,
    page,
    request,
  }) => {
    test.setTimeout(120_000);
    if (!agent) throw new Error("The scoped agent was not seeded");
    await installBrowserSession(context, user);

    // Compare the inspector with the same workspace's real effective policy.
    // An unavailable preview must fail this integration test, not pass as empty rules.
    const policyResponse = await authedRequest(
      request,
      user,
      "post",
      "/v1/governance/effective-policy/preview",
      { data: { agent_id: agent.id } }
    );
    expect(
      policyResponse.ok(),
      "The real policy preview must resolve"
    ).toBeTruthy();
    const { effective_policy: policy } = (await policyResponse.json()) as {
      effective_policy: EffectivePolicy;
    };
    expect(policy).toBeTruthy();

    await gotoCommitted(page, "/network");
    const agentNode = page.locator(`.react-flow__node[data-id="${agent.id}"]`);
    const overview = page.getByRole("button", {
      name: "Overview",
      exact: true,
    });
    const allConnections = page.getByRole("button", {
      name: "All connections",
      exact: true,
    });
    await expect(overview).toHaveAttribute("aria-pressed", "true", {
      timeout: 15_000,
    });
    await expect(agentNode).toHaveClass(/react-flow__node-networkAgent/);
    await expect(
      agentNode.getByText(agent.name, { exact: true })
    ).toBeVisible();

    await agentNode
      .getByRole("button", {
        name: `Inspect permissions for ${agent.name}`,
        exact: true,
      })
      .click();
    const inspector = page.getByRole("complementary", {
      name: "Connections and permissions",
      exact: true,
    });
    await expect(inspector).toBeVisible();
    await expect(
      inspector.getByText(agent.name, { exact: true })
    ).toBeVisible();
    await expect(
      inspector.getByText("Tool allowlist", { exact: true })
    ).toBeVisible({
      timeout: 15_000,
    });
    await expect(
      inspector.getByText("Resolving policy…", { exact: true })
    ).toHaveCount(0);
    await expect(inspector.getByText(/Permissions are unknown/)).toHaveCount(0);

    for (const rule of [
      {
        title: "Denied tool patterns",
        items: policy.tools?.denied ?? [],
        empty: "No explicit deny patterns in this preview.",
      },
      {
        title: "Tool allowlist",
        items: policy.tools?.allowed ?? [],
        empty: "No extra allowlist. Only connected tools are candidates.",
      },
      {
        title: "Human approval required",
        items: policy.approval?.requires_human_approval
          ? ["Every tool call"]
          : (policy.approval?.escalation_rules ?? []),
        empty: "No approval requirement in this preview.",
      },
    ]) {
      const ruleHeading = inspector.getByText(rule.title, { exact: true });
      await expect(ruleHeading).toBeVisible();
      const ruleGroup = ruleHeading.locator("..");
      if (rule.items.length) {
        await expect(ruleGroup.getByRole("listitem")).toHaveText(rule.items);
      } else {
        await expect(
          ruleGroup.getByText(rule.empty, { exact: true })
        ).toBeVisible();
      }
    }

    await inspector
      .getByRole("button", { name: "Show agent path", exact: true })
      .click();
    const clearFocus = page.getByRole("button", {
      name: "Show the whole network",
      exact: true,
    });
    await expect(clearFocus).toHaveText(`Path: ${agent.name}`);
    await expect(allConnections).toHaveAttribute("aria-pressed", "true");
    await expect(agentNode).toHaveClass(/react-flow__node-organization/);
    await inspector
      .getByRole("button", { name: "Close details", exact: true })
      .click();
    await expect(inspector).toHaveCount(0);
    await expect(clearFocus).toBeVisible();
    await clearFocus.click();
    await expect(clearFocus).toHaveCount(0);

    await overview.click();
    await expect(overview).toHaveAttribute("aria-pressed", "true");
    await expect(agentNode).toHaveClass(/react-flow__node-networkAgent/);
    await allConnections.click();
    await expect(allConnections).toHaveAttribute("aria-pressed", "true");
    await expect(agentNode).toHaveClass(/react-flow__node-organization/);

    // Existing deep links and alternate lenses remain usable with real scoped data.
    await gotoCommitted(page, "/network?view=dataflow");
    await expect(overview).toHaveAttribute("aria-pressed", "true", {
      timeout: 15_000,
    });
    await expect(agentNode).toHaveClass(/react-flow__node-networkAgent/);
    await page
      .getByRole("button", { name: "Organization", exact: true })
      .click();
    await expect(page).toHaveURL(/\/network\?view=org$/);
    await expect(
      page.getByRole("button", { name: "Full network", exact: true })
    ).toBeVisible();
    await expect(agentNode).toHaveClass(/react-flow__node-organization/);
    await page
      .getByRole("button", { name: "Access Graph", exact: true })
      .click();
    await expect(page).toHaveURL(/\/network\?view=access$/);
    await expect(
      page
        .getByRole("button")
        .filter({ has: page.getByText(agent.name, { exact: true }) })
    ).toBeVisible();

    await gotoCommitted(page, "/dashboard");
    await gotoCommitted(page, "/network");
    await expect(overview).toHaveAttribute("aria-pressed", "true", {
      timeout: 15_000,
    });
    await expect(
      agentNode.getByText(agent.name, { exact: true })
    ).toBeVisible();
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(agentNode).toHaveClass(/react-flow__node-networkAgent/, {
      timeout: 15_000,
    });
    await expect(
      agentNode.getByText(agent.name, { exact: true })
    ).toBeVisible();
  });
});

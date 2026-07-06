import { expect, test } from "@playwright/test";
import {
  apiBaseURL,
  authedRequest,
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  registerUserThroughKratos,
  waitForMailpitMessage,
} from "./helpers/real-stack";
import { requirementTitle } from "./requirements";

const runRealStack = process.env.PLAYWRIGHT_REAL_STACK === "1";

test.describe("real stack smoke", () => {
  test.skip(
    !runRealStack,
    "Set PLAYWRIGHT_REAL_STACK=1 to run against a live stand"
  );

  test(
    requirementTitle(
      "FR-01",
      "API health, OpenAPI, and authenticated agents endpoint are available"
    ),
    async ({ request }) => {
      const user = await createKratosUser("pw-api");
      try {
        const health = await request.get(`${apiBaseURL}/health`);
        expect(health.ok()).toBeTruthy();
        expect((await health.json()).status).toBe("healthy");

        const openapi = await request.get(`${apiBaseURL}/openapi.json`);
        expect(openapi.ok()).toBeTruthy();
        const spec = await openapi.json();
        expect(spec.paths).toHaveProperty("/v1/agents/");
        expect(spec.paths).toHaveProperty("/v1/triggers/");
        expect(spec.paths).toHaveProperty("/v1/mcp-servers/");

        const agents = await authedRequest(request, user, "get", "/v1/agents/");
        expect(agents.ok()).toBeTruthy();
        expect(Array.isArray(await agents.json())).toBeTruthy();
      } finally {
        await deleteKratosUser(user.identityId);
      }
    }
  );

  test(
    requirementTitle(
      "FR-01",
      "authenticated browser shell uses a real Kratos session"
    ),
    async ({ context, page }) => {
      const user = await createKratosUser("pw-ui");
      try {
        await installBrowserSession(context, user);
        await page.goto("/agents");

        await expect(page).not.toHaveURL(/\/auth\/login/);
        await expect(
          page.getByRole("link", { name: /deploy new agent/i })
        ).toBeVisible();
        await expect(
          page.getByRole("link", { name: "Agents", exact: true })
        ).toBeVisible();
      } finally {
        await deleteKratosUser(user.identityId);
      }
    }
  );

  test(
    requirementTitle(
      "FR-02",
      "workspace invitation flow uses real Kratos users and backend auth"
    ),
    async ({ request }) => {
      const alice = await createKratosUser("pw-alice");
      const bob = await createKratosUser("pw-bob");
      try {
        const invitation = await authedRequest(
          request,
          alice,
          "post",
          `/v1/workspaces/${alice.identityId}/invitations`,
          { data: { email: bob.email } }
        );
        expect(invitation.status()).toBe(201);
        const invitePayload = await invitation.json();
        expect(invitePayload.status).toBe("pending");
        expect(invitePayload.token).toEqual(expect.any(String));

        const accepted = await authedRequest(
          request,
          bob,
          "post",
          "/v1/invitations/accept",
          { data: { token: invitePayload.token } }
        );
        expect(accepted.ok()).toBeTruthy();
        const acceptedPayload = await accepted.json();
        expect(acceptedPayload.workspace_id).toBe(alice.identityId);
        expect(acceptedPayload.user_id).toBe(bob.identityId);

        const members = await authedRequest(
          request,
          bob,
          "get",
          `/v1/workspaces/${alice.identityId}/members`
        );
        expect(members.ok()).toBeTruthy();
        const memberPayload = await members.json();
        expect(
          memberPayload.some((member: { user_id: string }) => member.user_id === bob.identityId)
        ).toBe(true);
      } finally {
        await deleteKratosUser(bob.identityId);
        await deleteKratosUser(alice.identityId);
      }
    }
  );

  test(
    requirementTitle(
      "FR-10",
      "Kratos registration email is captured in Mailpit"
    ),
    async () => {
      const registered = await registerUserThroughKratos("pw-mailpit");
      try {
        const message = await waitForMailpitMessage(
          registered.email,
          /verify your email address/i
        );
        expect(message.Subject).toMatch(/verify your email address/i);
        expect(message.Snippet).toContain("verify your account");
      } finally {
        await deleteKratosUser(registered.identityId);
      }
    }
  );
});

import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const { getAuthToken, getRequestWorkspaceSlug } = vi.hoisted(() => ({
  getAuthToken: vi.fn(),
  getRequestWorkspaceSlug: vi.fn(),
}));

vi.mock("server-only", () => ({}));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
vi.mock("@/env", () => ({ env: { API_URL: "https://api.example.test" } }));
vi.mock("@/lib/getAuthToken", () => ({ getAuthToken }));
vi.mock("./getAuthToken", () => ({ getAuthToken }));
vi.mock("@/lib/workspace-context", () => ({ getRequestWorkspaceSlug }));

const INSTANCE_ID = "d50241d7-eafe-4011-8479-b40f7a2aab3c";

describe("hand-rolled fetches in server actions", () => {
  // The module graph is large; a cold import under a parallel run outlasts
  // the default per-test timeout.
  beforeAll(async () => {
    await import("./server-actions");
  }, 30_000);

  beforeEach(() => {
    vi.clearAllMocks();
    getAuthToken.mockResolvedValue("test-token");
    getRequestWorkspaceSlug.mockResolvedValue("aadocs");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(
        async () =>
          new Response("{}", {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
      )
    );
  });

  it.each([
    [
      "OAuth authorize",
      async () =>
        (await import("./server-actions")).oauthAuthorizeAction({
          instance_id: INSTANCE_ID,
        }),
    ],
    [
      "auth probe",
      async () =>
        (await import("./server-actions")).probeInstanceAuthAction(INSTANCE_ID),
    ],
    [
      "connection validation",
      async () =>
        (await import("./server-actions")).validateConnectionAction(
          "https://mcp.linear.app/mcp",
          {}
        ),
    ],
  ])(
    "scopes the %s request to the switched-into workspace",
    async (_name, run) => {
      await run();

      const [url, init] = vi.mocked(fetch).mock.calls[0];
      const headers = new Headers((init as RequestInit | undefined)?.headers);
      expect(headers.get("Authorization")).toBe("Bearer test-token");
      expect(headers.has("x-agentarea-workspace")).toBe(false);
      expect(new URL(String(url)).pathname).toMatch(
        /^\/v1\/workspaces\/aadocs\//
      );
    }
  );
});

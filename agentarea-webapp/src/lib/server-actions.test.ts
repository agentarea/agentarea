import { beforeEach, describe, expect, it, vi } from "vitest";

const { getAuthToken, getActiveWorkspaceSlug } = vi.hoisted(() => ({
  getAuthToken: vi.fn(),
  getActiveWorkspaceSlug: vi.fn(),
}));

vi.mock("server-only", () => ({}));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
vi.mock("@/env", () => ({ env: { API_URL: "https://api.example.test" } }));
vi.mock("@/lib/getAuthToken", () => ({ getAuthToken }));
vi.mock("./getAuthToken", () => ({ getAuthToken }));
vi.mock("@/lib/workspace-context", () => ({ getActiveWorkspaceSlug }));

const INSTANCE_ID = "d50241d7-eafe-4011-8479-b40f7a2aab3c";

describe("hand-rolled fetches in server actions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getAuthToken.mockResolvedValue("test-token");
    getActiveWorkspaceSlug.mockResolvedValue("aadocs");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
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
        (await import("./server-actions")).oauthAuthorizeAction(INSTANCE_ID),
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

      const request = vi.mocked(fetch).mock.calls[0];
      const headers = new Headers(
        (request[1] as RequestInit | undefined)?.headers
      );
      expect(headers.get("Authorization")).toBe("Bearer test-token");
      expect(headers.get("x-agentarea-workspace")).toBe("aadocs");
    }
  );
});

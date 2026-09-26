import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getAgentOverview,
  getDashboard,
  getWorkspaceSettings,
  updateWorkspaceSettings,
} from "./api-dashboard";

const { getAuthToken, getRequestWorkspaceSlug } = vi.hoisted(() => ({
  getAuthToken: vi.fn(),
  getRequestWorkspaceSlug: vi.fn(),
}));

vi.mock("server-only", () => ({}));
vi.mock("@/env", () => ({ env: { API_URL: "https://api.example.test" } }));
vi.mock("./getAuthToken", () => ({ getAuthToken }));
vi.mock("./workspace-context", () => ({ getRequestWorkspaceSlug }));

describe("dashboard API client", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getAuthToken.mockResolvedValue("test-token");
    getRequestWorkspaceSlug.mockResolvedValue("team-workspace");
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

  it("fails before calling the API when Kratos does not issue a token", async () => {
    getAuthToken.mockResolvedValue(null);

    await expect(getDashboard()).rejects.toThrow("No auth token available");
    expect(fetch).not.toHaveBeenCalled();
    expect(getRequestWorkspaceSlug).not.toHaveBeenCalled();
  });

  it.each([
    ["dashboard", () => getDashboard()],
    ["workspace settings", () => getWorkspaceSettings()],
    ["agent overview", () => getAgentOverview("agent/id")],
    ["workspace settings update", () => updateWorkspaceSettings(25)],
  ])(
    "scopes the %s request to the active workspace",
    async (_name, request) => {
      await request();

      const [url, init] = vi.mocked(fetch).mock.calls[0];
      const headers = new Headers(init?.headers);
      expect(headers.get("Authorization")).toBe("Bearer test-token");
      expect(headers.has("X-AgentArea-Workspace")).toBe(false);
      expect(String(url)).toMatch(
        /^https:\/\/api\.example\.test\/v1\/workspaces\/team-workspace\//
      );
    }
  );
});

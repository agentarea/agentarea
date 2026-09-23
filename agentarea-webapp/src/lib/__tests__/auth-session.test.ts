import { describe, expect, it } from "vitest";
import {
  hasLiveSession,
  isProtectedRoute,
  loginRedirectPath,
} from "../auth-session";

describe("isProtectedRoute", () => {
  it.each([
    ["/agents", true],
    ["/agents/123", true],
    ["/dashboard", true],
    ["/budgets", true],
    ["/members", true],
    ["/", false],
    ["/auth/login", false],
    ["/error", false],
    ["/500/details", false],
    ["/agentsfoo", true],
    ["/settings/profile", true],
  ])("marks %s as %s", (pathname, expected) => {
    expect(isProtectedRoute(pathname)).toBe(expected);
  });
});

describe("loginRedirectPath", () => {
  it("carries the requested page so a deep link survives sign-in", () => {
    expect(loginRedirectPath("/invite", "?token=abc123")).toBe(
      "/auth/login?return_to=%2Finvite%3Ftoken%3Dabc123"
    );
  });

  it("keeps the return target relative so it works on any public host", () => {
    const returnTo = new URLSearchParams(
      loginRedirectPath("/members", "").split("?")[1]
    ).get("return_to");
    expect(returnTo).toBe("/members");
  });

  it("sends the landing page to a bare login", () => {
    expect(loginRedirectPath("/", "")).toBe("/auth/login");
  });

  it("never returns to an auth page, which would loop", () => {
    expect(loginRedirectPath("/auth/login", "?flow=1")).toBe("/auth/login");
  });

  it("refuses a target that would leave this origin", () => {
    expect(loginRedirectPath("//evil.example.com/steal", "")).toBe(
      "/auth/login"
    );
    expect(loginRedirectPath("/\\evil.example.com", "")).toBe("/auth/login");
  });
});

// --- hasLiveSession ---
const ORY = "http://ory.internal";

function mockFetch(
  result: { ok: boolean; status: number; json: () => Promise<unknown> } | Error,
  calls: { count: number }
): typeof fetch {
  return (async () => {
    calls.count += 1;
    if (result instanceof Error) {
      throw result;
    }
    return result as unknown as Response;
  }) as unknown as typeof fetch;
}

describe("hasLiveSession", () => {
  it("returns false without a cookie and does not fetch", async () => {
    const calls = { count: 0 };
    const fetchImpl = mockFetch(
      { ok: true, status: 200, json: async () => ({ tokenized: "jwt" }) },
      calls
    );
    const result = await hasLiveSession(null, { orySdkUrl: ORY, fetchImpl });

    expect(result).toBe(false);
    expect(calls.count).toBe(0);
  });

  it("returns true for a live tokenized session", async () => {
    const calls = { count: 0 };
    const fetchImpl = mockFetch(
      { ok: true, status: 200, json: async () => ({ tokenized: "jwt" }) },
      calls
    );
    const result = await hasLiveSession("ory_kratos_session=abc", {
      orySdkUrl: ORY,
      fetchImpl,
    });
    expect(result).toBe(true);
  });

  it("returns false when a successful response has no token", async () => {
    const calls = { count: 0 };
    const fetchImpl = mockFetch(
      { ok: true, status: 200, json: async () => ({}) },
      calls
    );
    const result = await hasLiveSession("ory_kratos_session=abc", {
      orySdkUrl: ORY,
      fetchImpl,
    });
    expect(result).toBe(false);
  });

  it("returns false for an unauthorized response", async () => {
    const calls = { count: 0 };
    const fetchImpl = mockFetch(
      { ok: false, status: 401, json: async () => ({}) },
      calls
    );
    const result = await hasLiveSession("ory_kratos_session=abc", {
      orySdkUrl: ORY,
      fetchImpl,
    });
    expect(result).toBe(false);
  });

  it("returns false when the session request fails", async () => {
    const calls = { count: 0 };
    const fetchImpl = mockFetch(new Error("network down"), calls);
    const result = await hasLiveSession("ory_kratos_session=abc", {
      orySdkUrl: ORY,
      fetchImpl,
    });
    expect(result).toBe(false);
  });
});

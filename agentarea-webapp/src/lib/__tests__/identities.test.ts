import { describe, expect, it, vi } from "vitest";
import { identityToProfile, resolveIdentityProfiles } from "@/lib/identities";

const mockEnv = vi.hoisted<{ ORY_ADMIN_URL: string | undefined }>(() => ({
  ORY_ADMIN_URL: "http://kratos:4434",
}));
vi.mock("@/env", () => ({ env: mockEnv }));
vi.mock("server-only", () => ({}));

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

describe("identityToProfile", () => {
  it("joins first and last name and reads email/username traits", () => {
    expect(
      identityToProfile({
        traits: {
          email: "julia@example.com",
          name: { first: "Julia", last: "A" },
          username: "julia",
        },
      })
    ).toEqual({
      email: "julia@example.com",
      name: "Julia A",
      username: "julia",
    });
  });

  it("tolerates a missing or malformed name", () => {
    expect(
      identityToProfile({ traits: { name: { first: "" } } }).name
    ).toBeNull();
    expect(identityToProfile({ traits: { name: 42 } }).name).toBeNull();
    expect(identityToProfile({}).email).toBeNull();
  });
});

describe("resolveIdentityProfiles", () => {
  it("fetches each unique id from the admin API", async () => {
    const fetchImpl = vi.fn(async (url: string | URL | Request) => {
      const id = String(url).split("/").pop();
      return jsonResponse({ id, traits: { email: `${id}@example.com` } });
    });

    const profiles = await resolveIdentityProfiles(
      ["a", "b", "a"],
      fetchImpl as unknown as typeof fetch
    );

    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(fetchImpl.mock.calls[0][0]).toBe(
      "http://kratos:4434/admin/identities/a"
    );
    expect(profiles.get("a")?.email).toBe("a@example.com");
    expect(profiles.get("b")?.email).toBe("b@example.com");
  });

  it("leaves unknown ids and failed requests unresolved", async () => {
    const fetchImpl = vi.fn(async (url: string | URL | Request) => {
      if (String(url).endsWith("/missing")) return jsonResponse({}, 404);
      if (String(url).endsWith("/down")) throw new Error("ECONNREFUSED");
      return jsonResponse({ traits: { email: "ok@example.com" } });
    });
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const profiles = await resolveIdentityProfiles(
      ["ok", "missing", "down"],
      fetchImpl as unknown as typeof fetch
    );

    expect([...profiles.keys()]).toEqual(["ok"]);
    errorSpy.mockRestore();
  });

  it("skips the lookup entirely when no admin URL is configured", async () => {
    const fetchImpl = vi.fn();
    const saved = mockEnv.ORY_ADMIN_URL;
    mockEnv.ORY_ADMIN_URL = undefined;
    try {
      const profiles = await resolveIdentityProfiles(
        ["a"],
        fetchImpl as unknown as typeof fetch
      );
      expect(profiles.size).toBe(0);
      expect(fetchImpl).not.toHaveBeenCalled();
    } finally {
      mockEnv.ORY_ADMIN_URL = saved;
    }
  });

  it("does nothing for an empty list", async () => {
    const fetchImpl = vi.fn();
    expect(
      (await resolveIdentityProfiles([], fetchImpl as unknown as typeof fetch))
        .size
    ).toBe(0);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

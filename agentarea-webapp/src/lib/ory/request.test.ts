import { headers } from "next/headers";
import { describe, expect, it, vi } from "vitest";
import { getCookieHeader, getPublicUrl } from "./request";

vi.mock("next/headers", () => ({
  headers: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  redirect: vi.fn(),
  RedirectType: { replace: "replace" },
}));

function mockHeaders(values: Record<string, string | undefined>) {
  vi.mocked(headers).mockResolvedValue({
    get: (key: string) => values[key] ?? null,
  } as unknown as Awaited<ReturnType<typeof headers>>);
}

describe("getCookieHeader", () => {
  it("returns the cookie header when present", async () => {
    mockHeaders({ cookie: "cookie-value" });
    await expect(getCookieHeader()).resolves.toBe("cookie-value");
  });

  it("returns undefined when the cookie header is absent", async () => {
    mockHeaders({});
    await expect(getCookieHeader()).resolves.toBeUndefined();
  });
});

describe("getPublicUrl", () => {
  it("uses x-forwarded-proto when available", async () => {
    mockHeaders({ host: "example.com", "x-forwarded-proto": "https" });
    await expect(getPublicUrl()).resolves.toBe("https://example.com");
  });

  it("defaults to http when x-forwarded-proto is absent", async () => {
    mockHeaders({ host: "example.com" });
    await expect(getPublicUrl()).resolves.toBe("http://example.com");
  });
});

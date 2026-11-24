import { describe, expect, it } from "vitest";
import { isUnderVersionedApi } from "./api-path";

const API = "http://backend:8000";

describe("isUnderVersionedApi", () => {
  it("allows a path under /v1", () => {
    expect(isUnderVersionedApi(`${API}/v1/workspaces/w/agents`, API)).toBe(true);
  });

  it("refuses percent-encoded dot segments that climb out of /v1", () => {
    expect(isUnderVersionedApi(`${API}/v1/%2e%2e/%2e%2e/health`, API)).toBe(false);
    expect(isUnderVersionedApi(`${API}/v1/%2E%2E/openapi.json`, API)).toBe(false);
    expect(isUnderVersionedApi(`${API}/v1/.%2e/oauth2/auth`, API)).toBe(false);
  });

  it("refuses /v1 itself and look-alike prefixes", () => {
    expect(isUnderVersionedApi(`${API}/v1`, API)).toBe(false);
    expect(isUnderVersionedApi(`${API}/v1x/health`, API)).toBe(false);
  });

  it("refuses a different origin", () => {
    expect(isUnderVersionedApi("http://evil.example/v1/x", API)).toBe(false);
  });

  it("respects a base URL with its own path", () => {
    const base = "http://gw/api";
    expect(isUnderVersionedApi(`${base}/v1/agents`, base)).toBe(true);
    expect(isUnderVersionedApi(`${base}/v1/%2e%2e/%2e%2e/admin`, base)).toBe(false);
  });
});

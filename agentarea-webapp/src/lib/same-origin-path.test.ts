import { describe, expect, it } from "vitest";
import { isSameOriginPath } from "./same-origin-path";

describe("isSameOriginPath", () => {
  it("accepts a path on this site", () => {
    expect(isSameOriginPath("/api/proxy/v1/workspaces/w/files/a.png")).toBe(true);
  });

  it("rejects protocol-relative URLs, backslash spelling included", () => {
    expect(isSameOriginPath("//evil.host/x.png")).toBe(false);
    expect(isSameOriginPath("/\\evil.host/x.png")).toBe(false);
  });

  it("rejects absolute URLs and relative names", () => {
    expect(isSameOriginPath("https://evil.host/x.png")).toBe(false);
    expect(isSameOriginPath("media/x.png")).toBe(false);
  });
});

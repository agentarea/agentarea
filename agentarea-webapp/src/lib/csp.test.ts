import { describe, expect, it } from "vitest";
import { CONTENT_SECURITY_POLICY } from "./csp";

describe("CONTENT_SECURITY_POLICY", () => {
  it("locks down object-src, base-uri and frame-ancestors", () => {
    expect(CONTENT_SECURITY_POLICY).toContain("object-src 'none'");
    expect(CONTENT_SECURITY_POLICY).toContain("base-uri 'self'");
    expect(CONTENT_SECURITY_POLICY).toContain("frame-ancestors 'none'");
  });

  it("sets no other directive", () => {
    expect(CONTENT_SECURITY_POLICY.split(";").length).toBe(3);
  });
});

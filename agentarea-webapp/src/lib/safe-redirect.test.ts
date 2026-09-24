import { describe, expect, it } from "vitest";
import { isSafeRedirectUrl } from "./safe-redirect";

describe("isSafeRedirectUrl", () => {
  it("allows https URLs", () => {
    expect(isSafeRedirectUrl("https://as.example.com/authorize?state=1")).toBe(
      true
    );
  });

  it("allows http URLs", () => {
    expect(isSafeRedirectUrl("http://localhost:9000/authorize")).toBe(true);
  });

  it("rejects a javascript: URL", () => {
    expect(isSafeRedirectUrl("javascript:alert(document.cookie)")).toBe(
      false
    );
  });

  it("rejects a data: URL", () => {
    expect(
      isSafeRedirectUrl("data:text/html,<script>alert(1)</script>")
    ).toBe(false);
  });

  it("rejects a vbscript: URL", () => {
    expect(isSafeRedirectUrl("vbscript:msgbox(1)")).toBe(false);
  });

  it("rejects an unparsable string", () => {
    expect(isSafeRedirectUrl("not a url")).toBe(false);
  });

  it("rejects an empty string", () => {
    expect(isSafeRedirectUrl("")).toBe(false);
  });
});

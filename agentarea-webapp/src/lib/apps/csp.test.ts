import { describe, expect, it } from "vitest";
import { buildSandboxCsp } from "./csp";

describe("buildSandboxCsp", () => {
  it("uses the restrictive default and pins framing to the host origin", () => {
    expect(buildSandboxCsp(undefined, "http://localhost:3000")).toBe(
      "default-src 'none'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' data:; font-src 'self' data:; connect-src 'none'; worker-src 'self' blob:; frame-src 'none'; base-uri 'self'; frame-ancestors http://localhost:3000"
    );
  });

  it("drops values that can inject a second directive", () => {
    const header = buildSandboxCsp(
      {
        resourceDomains: [
          "https://cdn.example",
          "https://evil.example; connect-src *",
          "https://quoted.example'",
          "https://spaced.example/path with-space",
          "https://line.example\nconnect-src *",
        ],
        connectDomains: [
          "https://api.example",
          "https://bad.example; img-src *",
        ],
        frameDomains: ["https://video.example", 'https://bad.example"'],
      },
      "http://localhost:3000"
    );

    expect(header).toContain(
      "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.example"
    );
    expect(header).toContain("connect-src https://api.example;");
    expect(header).toContain("frame-src https://video.example");
    expect(header).not.toContain("evil.example");
    expect(header).not.toContain("quoted.example");
    expect(header).not.toContain("spaced.example");
    expect(header).not.toContain("line.example");
    expect(header).not.toContain("bad.example");
  });
});

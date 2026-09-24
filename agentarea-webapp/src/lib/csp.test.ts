import { describe, expect, it } from "vitest";
import { buildContentSecurityPolicy } from "./csp";

describe("buildContentSecurityPolicy", () => {
  it("locks down object-src, base-uri and frame-ancestors unconditionally", () => {
    const csp = buildContentSecurityPolicy({});

    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("base-uri 'self'");
    expect(csp).toContain("frame-ancestors 'none'");
  });

  it("never sends form-action, which would block the Kratos/Hydra redirect chains", () => {
    const csp = buildContentSecurityPolicy({
      apiOrigin: "https://api.agentarea.ai",
      oryOrigin: "https://auth.agentarea.ai",
    });

    expect(csp).not.toContain("form-action");
  });

  it("scopes connect-src to 'self' when no external origins are given", () => {
    const csp = buildContentSecurityPolicy({});

    expect(csp).toContain("connect-src 'self'");
  });

  it("adds the API and Ory origins to connect-src when configured", () => {
    const csp = buildContentSecurityPolicy({
      apiOrigin: "https://api.agentarea.ai",
      oryOrigin: "https://auth.agentarea.ai",
    });

    expect(csp).toContain(
      "connect-src 'self' https://api.agentarea.ai https://auth.agentarea.ai"
    );
  });

  it("reduces a URL with a path to its bare origin", () => {
    const csp = buildContentSecurityPolicy({
      apiOrigin: "https://api.agentarea.ai/v1/",
    });

    expect(csp).toContain("connect-src 'self' https://api.agentarea.ai");
  });

  it("ignores an unparsable origin instead of throwing", () => {
    const csp = buildContentSecurityPolicy({ apiOrigin: "not-a-url" });

    expect(csp).toContain("connect-src 'self'");
    expect(csp).not.toContain("not-a-url");
  });

  it("deduplicates when the API and Ory origins are the same host", () => {
    const csp = buildContentSecurityPolicy({
      apiOrigin: "https://app.agentarea.ai",
      oryOrigin: "https://app.agentarea.ai",
    });

    const connectSrcLine = csp
      .split("; ")
      .find((directive) => directive.startsWith("connect-src"));
    expect(connectSrcLine?.split(" ")).toEqual([
      "connect-src",
      "'self'",
      "https://app.agentarea.ai",
    ]);
  });
});

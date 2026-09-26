import { describe, expect, it } from "vitest";
import { apiProxyUrl, isRelativeApiLink } from "./api-proxy-url";

describe("apiProxyUrl", () => {
  it("proxies an absolute link built from API_BASE_URL", () => {
    expect(
      apiProxyUrl("https://api.agentarea.ru/v1/workspaces/acme/files/a%20b.txt")
    ).toBe("/api/proxy/v1/workspaces/acme/files/a%20b.txt");
  });

  it("drops a path prefix the API is mounted under", () => {
    expect(apiProxyUrl("https://host/api/v1/workspaces/acme/x?y=1")).toBe(
      "/api/proxy/v1/workspaces/acme/x?y=1"
    );
  });

  it("proxies a root-relative link", () => {
    expect(
      apiProxyUrl("/v1/workspaces/acme/agents/a/tasks/t/artifacts/1?dl=1")
    ).toBe("/api/proxy/v1/workspaces/acme/agents/a/tasks/t/artifacts/1?dl=1");
  });

  it("rejects a link that is not an API path", () => {
    expect(() => apiProxyUrl("https://s3.example/bucket/key")).toThrow(
      "is not an API link"
    );
  });
});

describe("isRelativeApiLink", () => {
  it("matches root-relative API links only", () => {
    expect(isRelativeApiLink("/v1/workspaces/acme/x")).toBe(true);
    expect(isRelativeApiLink("https://api/v1/workspaces/acme/x")).toBe(false);
    expect(isRelativeApiLink("https://example.com/report.pdf")).toBe(false);
  });
});

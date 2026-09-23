import { describe, expect, it } from "vitest";
import {
  domainInitials,
  faviconSources,
  getMCPConnectionIconSrc,
} from "./entity-identity";

describe("faviconSources", () => {
  it("asks the host itself, then the site behind its service label", () => {
    expect(faviconSources("https://api.agentarea.ai/v1")).toEqual([
      "https://api.agentarea.ai/favicon.ico",
      "https://agentarea.ai/favicon.ico",
    ]);
  });

  it("does not strip a label that would leave a bare suffix", () => {
    expect(faviconSources("https://api.dev")).toEqual([
      "https://api.dev/favicon.ico",
    ]);
  });

  it("asks over https even when the service is reached over http", () => {
    expect(faviconSources("http://internal.agentarea.ai")).toEqual([
      "https://internal.agentarea.ai/favicon.ico",
    ]);
  });

  it("accepts a bare host, which is all the topology carries for MCP", () => {
    expect(faviconSources("mcp.agentarea.ai")).toEqual([
      "https://mcp.agentarea.ai/favicon.ico",
      "https://agentarea.ai/favicon.ico",
    ]);
  });

  it("has nothing to offer for a missing or unusable URL", () => {
    expect(faviconSources(null)).toEqual([]);
    expect(faviconSources("not a url")).toEqual([]);
  });
});

describe("domainInitials", () => {
  it("names a connection by its registrable domain, not its subdomain", () => {
    expect(domainInitials("https://api-metrika.agentarea.ai")).toBe("AG");
  });

  it("falls back to the connection name when the URL is unusable", () => {
    expect(domainInitials("", "Deleted API")).toBe("DE");
    expect(domainInitials(null, null)).toBe("API");
  });
});

describe("getMCPConnectionIconSrc", () => {
  it("prefers the instance's own icon, then the server spec's, then nothing", () => {
    const spec = { json_spec: { icons: [{ src: "https://cdn/spec.png" }] } };
    expect(
      getMCPConnectionIconSrc(
        { json_spec: { icons: [{ src: "https://cdn/instance.png" }] } },
        spec
      )
    ).toBe("https://cdn/instance.png");
    expect(getMCPConnectionIconSrc({ json_spec: {} }, spec)).toBe(
      "https://cdn/spec.png"
    );
    expect(getMCPConnectionIconSrc({}, null)).toBeUndefined();
  });

  it("ignores an icons entry that carries no usable src", () => {
    expect(
      getMCPConnectionIconSrc({ json_spec: { icons: [{ mimeType: "png" }] } })
    ).toBeUndefined();
  });
});

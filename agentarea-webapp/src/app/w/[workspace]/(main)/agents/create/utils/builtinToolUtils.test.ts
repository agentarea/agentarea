import { describe, expect, it } from "vitest";
import {
  getBuiltinToolDisplayInfo,
  getBuiltinToolLabel,
} from "./builtinToolUtils";

describe("getBuiltinToolLabel", () => {
  it("title-cases a namespaced toolset", () => {
    expect(getBuiltinToolLabel("agentarea/workspace_files")).toBe(
      "Workspace Files"
    );
    expect(getBuiltinToolLabel("agentarea/shell")).toBe("Shell");
  });

  it("keeps initialisms the backend spells in caps", () => {
    expect(getBuiltinToolLabel("agentarea/mcp_servers")).toBe("MCP Servers");
    expect(getBuiltinToolLabel("agentarea/openapi_connections")).toBe(
      "OpenAPI Connections"
    );
  });

  it("reads pre-namespace names still stored on older agents", () => {
    expect(getBuiltinToolLabel("math_toolset")).toBe("Math");
    expect(getBuiltinToolLabel("calculator")).toBe("Calculator");
  });

  it("reads a toolset added after this build without a registry entry", () => {
    expect(getBuiltinToolLabel("agentarea/future_thing")).toBe("Future Thing");
  });

  it("leaves a third-party namespace intact, publisher and all", () => {
    expect(getBuiltinToolLabel("vendor/unknown")).toBe("vendor/unknown");
  });
});

describe("getBuiltinToolDisplayInfo", () => {
  it("prefers the catalog's display_name over the derived label", () => {
    const info = getBuiltinToolDisplayInfo({
      name: "agentarea/context",
      display_name: "Organization Context",
      category: "utility",
      description: "Read files from the organization's context store.",
    });

    expect(info.displayName).toBe("Organization Context");
  });

  it("falls back to the derived label when the catalog omits one", () => {
    const info = getBuiltinToolDisplayInfo({ name: "agentarea/workspace_files" });

    expect(info.displayName).toBe("Workspace Files");
  });
});

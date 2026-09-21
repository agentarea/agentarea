import { describe, expect, it } from "vitest";
import type { Agent } from "@/types/agent";
import { resolveAgentToolIcons } from "./agentToolIcons";

const agentWith = (tools: NonNullable<Agent["tools"]>): Agent =>
  ({ id: "a1", name: "Agent", status: "active", tools }) as Agent;

describe("resolveAgentToolIcons", () => {
  it("labels a builtin toolset with its display name, not its namespace", () => {
    const [icon] = resolveAgentToolIcons(
      agentWith([{ type: "code", name: "agentarea/shell" }])
    );

    expect(icon).toEqual({
      kind: "builtin",
      toolName: "agentarea/shell",
      label: "Shell",
    });
  });

  it("keeps the raw name for a toolset the UI does not know", () => {
    const [icon] = resolveAgentToolIcons(
      agentWith([{ type: "code", name: "vendor/unknown" }])
    );

    expect(icon).toEqual({
      kind: "builtin",
      toolName: "vendor/unknown",
      label: "vendor/unknown",
    });
  });

  it("resolves an OpenAPI tool to its connection by id", () => {
    const [icon] = resolveAgentToolIcons(
      agentWith([
        {
          type: "openapi",
          name: "Yandex Metrica — Read Only",
          settings: { openapi_connection_id: "c1" },
        },
      ]),
      {
        openApiConnections: [
          {
            id: "c1",
            name: "Yandex Metrica — Read Only",
            base_url: "https://api-metrika.yandex.net",
          },
        ],
      }
    );

    expect(icon).toEqual({
      kind: "openapi",
      label: "Yandex Metrica — Read Only",
      initials: "YA",
      resolved: true,
    });
  });

  it("resolves an OpenAPI tool by connection name when no id is stored", () => {
    const [icon] = resolveAgentToolIcons(
      agentWith([{ type: "openapi", name: "Instantly — Outreach" }]),
      {
        openApiConnections: [
          {
            id: "c2",
            name: "Instantly — Outreach",
            base_url: "https://api.instantly.ai",
          },
        ],
      }
    );

    expect(icon).toMatchObject({ resolved: true, initials: "IN" });
  });

  it("marks an OpenAPI tool unresolved when its connection is gone", () => {
    const [icon] = resolveAgentToolIcons(
      agentWith([
        {
          type: "openapi",
          name: "Deleted API",
          settings: { openapi_connection_id: "gone" },
        },
      ]),
      { openApiConnections: [] }
    );

    expect(icon).toEqual({
      kind: "openapi",
      label: "Deleted API",
      resolved: false,
    });
  });

  it("renders a delegated agent as its own kind rather than dropping it", () => {
    const [icon] = resolveAgentToolIcons(
      agentWith([{ type: "agent", name: "BizDev — Score" }])
    );

    expect(icon).toEqual({ kind: "agent", label: "BizDev — Score" });
  });

  it("marks an MCP ref that matches no instance or server as unresolved", () => {
    const [icon] = resolveAgentToolIcons(
      agentWith([{ type: "mcp", name: "dangling-ref" }])
    );

    expect(icon).toEqual({
      kind: "mcp",
      src: undefined,
      label: "dangling-ref",
      resolved: false,
    });
  });
});

import { describe, expect, it } from "vitest";
import type {
  NetworkEdgeData,
  NetworkNodeData,
  TopologyResponse,
} from "../types";
import { getAccessTopology, type AccessScope } from "./accessTopology";

function node(
  id: string,
  type: NetworkNodeData["type"],
  metadata: Record<string, unknown> = {}
): NetworkNodeData {
  return { id, type, label: id, metadata };
}

function edge(
  source: string,
  target: string,
  relation: string
): NetworkEdgeData {
  return { id: `${source}-${target}-${relation}`, source, target, relation };
}

function fixture(): TopologyResponse {
  return {
    deployment_mode: "oss",
    governance: [{ interceptor_name: "audit_observer" }],
    nodes: [
      node("a", "agent"),
      node("private", "mcp_instance", { network_scope: "private" }),
      node("trigger", "trigger", { network_scope: "private" }),
      node("b", "agent", { network_scope: "egress" }),
      node("egress", "mcp_instance", { network_scope: "egress" }),
      node("unknown", "mcp_instance"),
      node("api", "openapi_connection"),
      node("skill", "skill", { network_scope: "private" }),
      node("unsupported", "skill", { network_scope: "internal" }),
    ],
    edges: [
      edge("a", "private", "uses_mcp"),
      edge("a", "trigger", "has_trigger"),
      edge("a", "b", "delegates_to"),
      edge("b", "egress", "uses_mcp"),
      edge("b", "unknown", "uses_mcp"),
      edge("a", "api", "uses_openapi"),
      edge("b", "skill", "has_skill"),
      edge("a", "unsupported", "has_skill"),
      edge("skill", "unsupported", "member_of"),
      edge("a", "missing", "uses_mcp"),
      edge("missing", "private", "uses_mcp"),
      edge("trigger", "a", "delegates_to"),
    ],
  };
}

describe("getAccessTopology", () => {
  it("includes all resource types by default and removes triggers, unsupported relations, and dangling edges", () => {
    const input = fixture();
    const result = getAccessTopology(input);
    expect(result.nodes.map(({ id }) => id)).toEqual([
      "a",
      "private",
      "b",
      "egress",
      "unknown",
      "api",
      "skill",
      "unsupported",
    ]);
    expect(result.edges).toEqual([
      input.edges[0],
      input.edges[2],
      input.edges[3],
      input.edges[4],
      input.edges[5],
      input.edges[6],
      input.edges[7],
    ]);
    expect(result.nodes.some(({ type }) => type === "trigger")).toBe(false);
    expect(getAccessTopology(input, "all")).toEqual(result);
  });

  it.each<{ scope: AccessScope; ids: string[]; edgeIndexes: number[] }>([
    {
      scope: "private",
      ids: ["a", "private", "b", "skill"],
      edgeIndexes: [0, 2, 6],
    },
    {
      scope: "egress",
      ids: ["a", "b", "egress"],
      edgeIndexes: [2, 3],
    },
    {
      scope: "unknown",
      ids: ["a", "b", "unknown", "api", "unsupported"],
      edgeIndexes: [2, 4, 5, 7],
    },
  ])(
    "filters $scope resources while retaining every agent and delegation",
    ({ scope, ids, edgeIndexes }) => {
      const input = fixture();
      const result = getAccessTopology(input, scope);
      expect(result.nodes.map(({ id }) => id)).toEqual(ids);
      expect(result.edges).toEqual(
        edgeIndexes.map((index) => input.edges[index])
      );
    }
  );

  it("keeps resources without explicit scope unclassified regardless of type", () => {
    const input = fixture();
    const privateIds = getAccessTopology(input, "private").nodes.map(
      ({ id }) => id
    );
    expect(privateIds).not.toContain("unknown");
    expect(privateIds).not.toContain("unsupported");
    expect(privateIds).not.toContain("api");
    expect(getAccessTopology(input, "unknown").nodes).toContain(input.nodes[6]);
  });

  it("retains isolated agents and their delegation when no resources match", () => {
    const input: TopologyResponse = {
      ...fixture(),
      nodes: [
        node("a", "agent"),
        node("b", "agent"),
        node("isolated", "agent"),
        node("private", "mcp_instance", { network_scope: "private" }),
      ],
      edges: [edge("a", "b", "delegates_to"), edge("a", "private", "uses_mcp")],
    };
    const result = getAccessTopology(input, "egress");
    expect(result.nodes).toEqual(input.nodes.slice(0, 3));
    expect(result.edges).toEqual([input.edges[0]]);
  });

  it("preserves metadata and original objects without adding permission claims or mutating input", () => {
    const input = fixture();
    const before = structuredClone(input);
    const result = getAccessTopology(input, "private");
    expect(input).toEqual(before);
    expect(result.governance).toBe(input.governance);
    expect(result.deployment_mode).toBe(input.deployment_mode);
    expect(result.nodes[1]).toBe(input.nodes[1]);
    expect(result.edges[0]).toBe(input.edges[0]);
    expect(result.nodes[1].metadata).toEqual({ network_scope: "private" });
  });

  it("handles an empty topology", () => {
    const input = { ...fixture(), nodes: [], edges: [] };
    expect(getAccessTopology(input)).toEqual(input);
  });
});

import { describe, expect, it } from "vitest";
import type {
  NetworkEdgeData,
  NetworkNodeData,
  TopologyResponse,
} from "../types";
import {
  focusAgentTopology,
  getAgentConnections,
  getNetworkScope,
} from "./networkConnections";

function node(
  id: string,
  type: NetworkNodeData["type"] = "agent",
  metadata: Record<string, unknown> = {}
): NetworkNodeData {
  return { id, type, label: id, metadata };
}

function edge(
  source: string,
  target: string,
  relation = "delegates_to"
): NetworkEdgeData {
  return { id: `${source}-${target}-${relation}`, source, target, relation };
}

function topology(
  nodes: NetworkNodeData[],
  edges: NetworkEdgeData[] = []
): TopologyResponse {
  return {
    nodes,
    edges,
    governance: [{ interceptor_name: "audit_observer" }],
    deployment_mode: "oss",
  };
}

describe("getNetworkScope", () => {
  it("distinguishes explicit scope from absent or unsupported metadata", () => {
    expect(
      getNetworkScope(
        node("private", "mcp_instance", { network_scope: "private" })
      )
    ).toBe("private");
    expect(
      getNetworkScope(node("external", "skill", { network_scope: "egress" }))
    ).toBe("egress");
    for (const network_scope of [
      undefined,
      null,
      "",
      "internal",
      "PRIVATE",
      false,
    ]) {
      expect(
        getNetworkScope(node("unknown", "mcp_instance", { network_scope }))
      ).toBe("unknown");
    }
    expect(getNetworkScope(node("agent"))).toBe("unknown");
  });

  it("uses the OpenAPI contract as its only inferred scope", () => {
    expect(getNetworkScope(node("api", "openapi_connection"))).toBe("egress");
    expect(
      getNetworkScope(
        node("api", "openapi_connection", { network_scope: "private" })
      )
    ).toBe("private");
  });
});

describe("getAgentConnections", () => {
  it("shows trigger activation and incoming delegation before outgoing capabilities", () => {
    const input = topology(
      [
        node("agent"),
        node("parent"),
        node("child"),
        node("trigger", "trigger"),
        node("tool", "mcp_instance"),
        node("source", "skill"),
      ],
      [
        edge("parent", "agent"),
        edge("agent", "child"),
        edge("agent", "trigger", "has_trigger"),
        edge("agent", "tool", "uses_mcp"),
        edge("source", "agent", "feeds"),
      ]
    );
    const connections = getAgentConnections(input, "agent");
    expect(connections.incoming.map(({ node }) => node.id)).toEqual([
      "parent",
      "trigger",
      "source",
    ]);
    expect(connections.outgoing.map(({ node }) => node.id)).toEqual([
      "child",
      "tool",
    ]);
    expect(connections.incoming[1].edge).toEqual(
      edge("agent", "trigger", "has_trigger")
    );
  });

  it("accepts an already incoming trigger and ignores invalid or duplicate edges", () => {
    const valid = edge("trigger", "agent", "starts");
    const input = topology(
      [node("agent"), node("trigger", "trigger"), node("tool", "mcp_instance")],
      [
        edge("missing", "agent"),
        edge("agent", "missing"),
        edge("agent", "agent"),
        valid,
        { ...valid },
        edge("agent", "tool", "uses_mcp"),
      ]
    );
    const connections = getAgentConnections(input, "agent");
    expect(connections.incoming).toEqual([
      { edge: valid, node: input.nodes[1] },
    ]);
    expect(connections.outgoing).toHaveLength(1);
  });

  it("shows resource consumers and trigger destinations in their operational direction", () => {
    const input = topology(
      [
        node("a"),
        node("b"),
        node("tool", "mcp_instance"),
        node("trigger", "trigger"),
      ],
      [
        edge("a", "tool", "uses_mcp"),
        edge("b", "tool", "uses_mcp"),
        edge("a", "trigger", "has_trigger"),
      ]
    );
    const before = structuredClone(input);
    const resource = getAgentConnections(input, "tool");
    expect(resource.incoming.map(({ node }) => node.id)).toEqual(["a", "b"]);
    expect(resource.outgoing).toEqual([]);
    const trigger = getAgentConnections(input, "trigger");
    expect(trigger.incoming).toEqual([]);
    expect(trigger.outgoing).toEqual([
      { edge: input.edges[2], node: input.nodes[0] },
    ]);
    expect(input).toEqual(before);
  });

  it("returns no connections for isolated nodes or missing selections", () => {
    const input = topology([node("isolated"), node("tool", "mcp_instance")]);
    for (const id of ["isolated", "missing", "tool"]) {
      expect(getAgentConnections(input, id)).toEqual({
        incoming: [],
        outgoing: [],
      });
    }
  });
});

describe("focusAgentTopology", () => {
  it("keeps only direct connections, preserving direction, order, and topology metadata", () => {
    const input = topology(
      [
        node("a"),
        node("b"),
        node("c"),
        node("trigger", "trigger"),
        node("tool", "mcp_instance"),
      ],
      [
        edge("a", "b"),
        edge("b", "c"),
        edge("a", "trigger", "has_trigger"),
        edge("a", "tool", "uses_mcp"),
        edge("b", "tool", "uses_mcp"),
        edge("a", "missing"),
        edge("a", "a"),
      ]
    );
    const before = structuredClone(input);
    const focused = focusAgentTopology(input, "a");
    expect(focused.nodes.map(({ id }) => id)).toEqual([
      "a",
      "b",
      "trigger",
      "tool",
    ]);
    expect(focused.edges).toEqual([
      input.edges[0],
      input.edges[2],
      input.edges[3],
    ]);
    expect(focused.governance).toBe(input.governance);
    expect(focused.deployment_mode).toBe("oss");
    expect(input).toEqual(before);
  });

  it("keeps an isolated selected agent and returns the original topology for invalid selections", () => {
    const input = topology([node("isolated"), node("tool", "mcp_instance")]);
    expect(focusAgentTopology(input, "isolated")).toEqual({
      ...input,
      nodes: [input.nodes[0]],
      edges: [],
    });
    expect(focusAgentTopology(input, "missing")).toBe(input);
    expect(focusAgentTopology(input, "tool")).toBe(input);
  });

  it("deduplicates edge IDs without mutating repeated input edge references", () => {
    const connection = edge("a", "b");
    const input = topology(
      [node("a"), node("b")],
      [connection, connection, { ...connection }]
    );
    const before = structuredClone(input);
    expect(focusAgentTopology(input, "a").edges).toEqual([connection]);
    expect(input).toEqual(before);
  });
});

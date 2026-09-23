import { describe, expect, it } from "vitest";
import type {
  NetworkEdgeData,
  NetworkNodeData,
  TopologyResponse,
} from "../types";
import {
  getAgentResources,
  NETWORK_AGENT_WIDTH,
  NETWORK_RESOURCE_LIMIT,
  networkAgentHeight,
} from "./networkMapLayout";

function node(
  id: string,
  type: NetworkNodeData["type"] = "agent",
  label = id
): NetworkNodeData {
  return { id, type, label, metadata: {} };
}

function edge(
  source: string,
  target: string,
  relation: string
): NetworkEdgeData {
  return { id: `${source}-${target}-${relation}`, source, target, relation };
}

function topology(
  nodes: NetworkNodeData[],
  edges: NetworkEdgeData[] = []
): TopologyResponse {
  return { nodes, edges, governance: [], deployment_mode: "local" };
}

describe("getAgentResources", () => {
  it("includes empty entries for agents and no entries for unattached resources", () => {
    expect(getAgentResources(topology([]))).toEqual(new Map());
    expect(
      getAgentResources(topology([node("agent"), node("tool", "mcp_instance")]))
    ).toEqual(new Map([["agent", []]]));
  });

  it("deduplicates resources and counts distinct agents sharing each resource", () => {
    const tool = node("tool", "mcp_instance");
    const skill = node("skill", "skill");
    const result = getAgentResources(
      topology(
        [node("alpha"), node("beta"), tool, skill],
        [
          edge("alpha", "tool", "uses_mcp"),
          { ...edge("alpha", "tool", "uses_mcp"), id: "duplicate" },
          edge("beta", "tool", "uses_mcp"),
          edge("alpha", "skill", "has_skill"),
        ]
      )
    );
    expect(result.get("alpha")).toEqual([
      { node: tool, sharedBy: 2 },
      { node: skill, sharedBy: 1 },
    ]);
    expect(result.get("beta")).toEqual([{ node: tool, sharedBy: 2 }]);
  });

  it("sorts triggers, integrations, and skills by label then id without changing input", () => {
    const resources = [
      node("skill", "skill", "A skill"),
      node("mcp-b", "mcp_instance", "Same"),
      node("api", "openapi_connection", "An API"),
      node("trigger", "trigger", "Z trigger"),
      node("mcp-a", "mcp_instance", "Same"),
    ];
    const relations = {
      trigger: "has_trigger",
      skill: "has_skill",
      mcp_instance: "uses_mcp",
      openapi_connection: "uses_openapi",
      agent: "delegates_to",
    };
    const input = topology(
      [node("z"), ...resources, node("a")],
      resources.map((item) => edge("a", item.id, relations[item.type]))
    );
    const before = structuredClone(input);
    const result = getAgentResources(input);
    expect([...result.keys()]).toEqual(["a", "z"]);
    expect(result.get("a")?.map((item) => item.node.id)).toEqual([
      "trigger",
      "api",
      "mcp-a",
      "mcp-b",
      "skill",
    ]);
    expect(
      getAgentResources({
        ...input,
        nodes: [...input.nodes].reverse(),
        edges: [...input.edges].reverse(),
      })
    ).toEqual(result);
    expect(input).toEqual(before);
  });

  it("ignores delegation, unknown relations, missing endpoints, and resource-originated edges", () => {
    const trigger = node("trigger", "trigger");
    const input = topology(
      [node("a"), node("b"), trigger, node("tool", "mcp_instance")],
      [
        edge("a", "b", "delegates_to"),
        edge("a", "b", "uses_mcp"),
        edge("a", "tool", "unknown"),
        edge("a", "missing", "uses_mcp"),
        edge("missing", "tool", "uses_mcp"),
        edge("tool", "trigger", "has_trigger"),
        edge("trigger", "a", "has_trigger"),
        edge("a", "trigger", "has_trigger"),
      ]
    );
    expect(getAgentResources(input)).toEqual(
      new Map([
        ["a", [{ node: trigger, sharedBy: 1 }]],
        ["b", []],
      ])
    );
  });
});

describe("networkAgentHeight", () => {
  it("reserves room for an empty hint and visible resource rows", () => {
    expect(NETWORK_AGENT_WIDTH).toBe(288);
    expect(NETWORK_RESOURCE_LIMIT).toBe(4);
    expect(networkAgentHeight(0, false)).toBe(140);
    expect(networkAgentHeight(0, true)).toBe(140);
    expect(networkAgentHeight(1, false)).toBe(168);
    expect(networkAgentHeight(4, false)).toBe(252);
  });

  it("caps collapsed rows and keeps the expand or collapse footer for overflowing resources", () => {
    expect(networkAgentHeight(5, false)).toBe(284);
    expect(networkAgentHeight(12, false)).toBe(284);
    expect(networkAgentHeight(5, true)).toBe(312);
    expect(networkAgentHeight(12, true)).toBe(508);
  });
});

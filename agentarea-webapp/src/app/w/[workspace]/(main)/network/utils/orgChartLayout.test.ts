import { describe, expect, it } from "vitest";
import type {
  NetworkEdgeData,
  NetworkNodeData,
  TopologyResponse,
} from "../types";
import {
  buildOrgChartLayout,
  ORG_NODE_HEIGHT,
  ORG_NODE_WIDTH,
} from "./orgChartLayout";

function node(
  id: string,
  type: NetworkNodeData["type"] = "agent"
): NetworkNodeData {
  return { id, type, label: id, metadata: {} };
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
  return { nodes, edges, governance: [], deployment_mode: "local" };
}

function expectNoOverlap(
  result: ReturnType<typeof buildOrgChartLayout>,
  nodeSize = (_node: NetworkNodeData) => ({
    width: ORG_NODE_WIDTH,
    height: ORG_NODE_HEIGHT,
  })
) {
  for (const [index, a] of result.nodes.entries()) {
    expect(Number.isFinite(a.position.x)).toBe(true);
    expect(Number.isFinite(a.position.y)).toBe(true);
    for (const b of result.nodes.slice(index + 1)) {
      const separated =
        a.position.x + nodeSize(a).width <= b.position.x ||
        b.position.x + nodeSize(b).width <= a.position.x ||
        a.position.y + nodeSize(a).height <= b.position.y ||
        b.position.y + nodeSize(b).height <= a.position.y;
      expect(separated, `${a.id} overlaps ${b.id}`).toBe(true);
    }
  }
}

function getNode(result: ReturnType<typeof buildOrgChartLayout>, id: string) {
  const found = result.nodes.find((item) => item.id === id);
  if (!found) throw new Error(`Expected node ${id}`);
  return found;
}

describe("buildOrgChartLayout", () => {
  it("keeps the default layout unchanged when explicit default sizes are supplied", () => {
    const input = topology(
      [node("a"), node("b"), node("c"), node("isolated")],
      [edge("a", "b"), edge("a", "c")]
    );
    expect(
      buildOrgChartLayout(input, true, () => ({
        width: ORG_NODE_WIDTH,
        height: ORG_NODE_HEIGHT,
      }))
    ).toEqual(buildOrgChartLayout(input, true));
  });

  it("uses variable card dimensions across hierarchy levels and packed groups", () => {
    const input = topology(
      Array.from({ length: 14 }, (_, index) => node(`agent-${index}`)),
      [
        edge("agent-0", "agent-1"),
        edge("agent-0", "agent-2"),
        edge("agent-1", "agent-3"),
        edge("agent-4", "agent-5"),
      ]
    );
    const nodeSize = (item: NetworkNodeData) => ({
      width: item.id === "agent-0" ? 600 : 288,
      height: 140 + Number(item.id.split("-")[1]) * 42,
    });
    const result = buildOrgChartLayout(input, true, nodeSize);
    expectNoOverlap(result, nodeSize);
    for (const item of result.nodes) {
      expect(item.position.x).toBeGreaterThanOrEqual(0);
      expect(item.position.y).toBeGreaterThanOrEqual(0);
    }
    for (const relation of result.edges) {
      const source = getNode(result, relation.source);
      expect(getNode(result, relation.target).position.y).toBeGreaterThan(
        source.position.y + nodeSize(source).height
      );
    }
    expect(
      buildOrgChartLayout(
        {
          ...input,
          nodes: [...input.nodes].reverse(),
          edges: [...input.edges].reverse(),
        },
        true,
        nodeSize
      )
    ).toEqual(result);
  });

  it("handles an empty organization", () => {
    expect(buildOrgChartLayout(topology([]), false)).toEqual({
      nodes: [],
      edges: [],
    });
  });

  it("uses card dimensions and separates hierarchy levels without overlap", () => {
    const result = buildOrgChartLayout(
      topology(
        [node("lead"), node("writer"), node("researcher"), node("editor")],
        [
          edge("lead", "writer"),
          edge("lead", "researcher"),
          edge("writer", "editor"),
        ]
      ),
      false
    );
    expectNoOverlap(result);
    for (const relation of result.edges) {
      expect(getNode(result, relation.target).position.y).toBeGreaterThan(
        getNode(result, relation.source).position.y + ORG_NODE_HEIGHT
      );
    }
  });

  it("packs isolated agents into multiple compact rows", () => {
    const result = buildOrgChartLayout(
      topology(
        Array.from({ length: 12 }, (_, index) => node(`agent-${index}`))
      ),
      false
    );
    const columns = new Set(result.nodes.map((item) => item.position.x)).size;
    const rows = new Set(result.nodes.map((item) => item.position.y)).size;
    expect(columns).toBeGreaterThan(1);
    expect(columns).toBeLessThanOrEqual(5);
    expect(rows).toBeGreaterThan(1);
    expect(rows).toBeLessThanOrEqual(5);
    expectNoOverlap(result);
  });

  it("places a trigger above its agent and preserves the relation identity", () => {
    const input = topology(
      [node("agent"), node("schedule", "trigger")],
      [edge("agent", "schedule", "has_trigger")]
    );
    const result = buildOrgChartLayout(input, false);
    expect(result.edges).toEqual([
      { ...input.edges[0], source: "schedule", target: "agent" },
    ]);
    expect(getNode(result, "schedule").position.y).toBeLessThan(
      getNode(result, "agent").position.y
    );
    expect(input.edges[0].source).toBe("agent");
  });

  it("retains a single shared resource and every parallel relationship", () => {
    const relations = [
      edge("alpha", "shared", "uses_tool"),
      edge("alpha", "shared", "can_access"),
      edge("beta", "shared", "uses_tool"),
    ];
    const result = buildOrgChartLayout(
      topology(
        [node("alpha"), node("beta"), node("shared", "mcp_instance")],
        relations
      ),
      false
    );
    expect(result.nodes.filter((item) => item.id === "shared")).toHaveLength(1);
    expect(result.edges.map((item) => item.id).sort()).toEqual(
      relations.map((item) => item.id).sort()
    );
    expectNoOverlap(result);
  });

  it("lays out cycles, self-loops and disconnected groups without losing nodes", () => {
    const result = buildOrgChartLayout(
      topology(
        [
          node("a"),
          node("b"),
          node("c"),
          node("d"),
          node("e"),
          node("isolated"),
        ],
        [
          edge("a", "b"),
          edge("b", "c"),
          edge("c", "a"),
          edge("b", "b"),
          edge("d", "e"),
        ]
      ),
      false
    );
    expect(result.nodes).toHaveLength(6);
    expect(result.edges).toHaveLength(5);
    expectNoOverlap(result);
  });

  it("keeps every agent in agents-only mode and only valid delegation edges", () => {
    const result = buildOrgChartLayout(
      topology(
        [node("a"), node("b"), node("isolated"), node("tool", "mcp_instance")],
        [
          edge("a", "b"),
          edge("a", "b", "can_access"),
          edge("a", "tool"),
          edge("a", "missing"),
        ]
      ),
      true
    );
    expect(result.nodes.map((item) => item.id)).toEqual(["a", "b", "isolated"]);
    expect(result.edges).toEqual([edge("a", "b")]);
    expectNoOverlap(result);
  });

  it("drops dangling edges in the full view", () => {
    const result = buildOrgChartLayout(
      topology([node("a")], [edge("a", "missing"), edge("missing", "a")]),
      false
    );
    expect(result.edges).toEqual([]);
    expect(result.nodes).toHaveLength(1);
  });

  it("is deterministic for reordered input and leaves input unchanged", () => {
    const input = topology(
      [
        node("z"),
        { ...node("b"), label: "Same" },
        { ...node("a"), label: "Same" },
        node("isolated"),
      ],
      [edge("z", "a"), edge("z", "b"), edge("a", "b")]
    );
    const before = structuredClone(input);
    const result = buildOrgChartLayout(input, false);
    const reordered = buildOrgChartLayout(
      {
        ...input,
        nodes: [...input.nodes].reverse(),
        edges: [...input.edges].reverse(),
      },
      false
    );
    expect(result).toEqual(reordered);
    expect(input).toEqual(before);
    expect(result.nodes.map((item) => item.id)).toEqual([
      "a",
      "b",
      "isolated",
      "z",
    ]);
  });
  it("places delegates after their source in the horizontal network view", () => {
    const result = buildOrgChartLayout(
      topology(
        [node("lead"), node("delegate"), node("independent")],
        [edge("lead", "delegate")]
      ),
      true,
      () => ({ width: 288, height: 284 }),
      { direction: "LR", aspectRatio: 2.4 }
    );
    const lead = result.nodes.find((node) => node.id === "lead");
    const delegate = result.nodes.find((node) => node.id === "delegate");
    if (!lead || !delegate) throw new Error("Missing delegation endpoints");
    expect(delegate.position.x).toBeGreaterThanOrEqual(lead.position.x + 288);
    expect(result.nodes).toHaveLength(3);
    for (let i = 0; i < result.nodes.length; i++) {
      for (let j = i + 1; j < result.nodes.length; j++) {
        const a = result.nodes[i].position;
        const b = result.nodes[j].position;
        expect(
          a.x + 288 <= b.x ||
            b.x + 288 <= a.x ||
            a.y + 284 <= b.y ||
            b.y + 284 <= a.y
        ).toBe(true);
      }
    }
  });
});

import { describe, expect, it } from "vitest";
import {
  crossing,
  flowLayout,
  flowZone,
  segmentsFor,
  type FlowLayout,
} from "./flowLayout";
import type { GraphEdge, GraphNode, NetworkGraph } from "./networkGraph";
import { insideContour } from "./perimeterContour";

function node(
  id: string,
  kind: GraphNode["kind"] = "agent",
  scope: GraphNode["scope"] = null,
  triggerType: string | null = null
): GraphNode {
  return {
    id,
    label: id,
    kind,
    scope,
    off: false,
    failed: false,
    degree: 0,
    issues: [],
    triggerType,
  };
}

function edge(source: string, target: string, relation: string): GraphEdge {
  return {
    id: `${source}-${target}-${relation}`,
    source,
    target,
    relation,
    off: false,
  };
}

const size = () => 40;

function at(layout: FlowLayout, id: string) {
  const point = layout.positions.get(id);
  if (!point) throw new Error(`no position for ${id}`);
  return point;
}

describe("flowZone", () => {
  it("keeps timers, agents and private stores inside, the rest outside", () => {
    expect(flowZone(node("p", "person"))).toBe("inbound");
    expect(flowZone(node("h", "trigger", null, "webhook"))).toBe("inbound");
    expect(flowZone(node("q", "trigger", null, "polling"))).toBe("inbound");
    expect(flowZone(node("c", "trigger", null, "cron"))).toBe("inside");
    expect(flowZone(node("a"))).toBe("inside");
    expect(flowZone(node("db", "mcp_instance", "private"))).toBe("inside");
    expect(flowZone(node("gh", "openapi_connection", "egress"))).toBe(
      "outbound"
    );
    expect(flowZone(node("u", "mcp_instance", "unknown"))).toBe("outbound");
  });
});

describe("crossing", () => {
  const zones = new Map([
    ["hook", "inbound" as const],
    ["a", "inside" as const],
    ["db", "inside" as const],
    ["gh", "outbound" as const],
    ["gh2", "outbound" as const],
  ]);

  it("names the links that carry data across the boundary", () => {
    expect(crossing(edge("hook", "a", "has_trigger"), zones)).toBe("inbound");
    expect(crossing(edge("a", "gh", "uses_openapi"), zones)).toBe("outbound");
    expect(crossing(edge("a", "db", "uses_mcp"), zones)).toBeNull();
    expect(crossing(edge("gh", "gh2", "member_of"), zones)).toBeNull();
  });
});

describe("flowLayout", () => {
  const graph: NetworkGraph = {
    nodes: [
      node("hook", "trigger", null, "webhook"),
      node("nightly", "trigger", null, "cron"),
      node("support"),
      node("billing"),
      node("db", "mcp_instance", "private"),
      node("github", "openapi_connection", "egress"),
    ],
    edges: [
      edge("hook", "support", "has_trigger"),
      edge("nightly", "billing", "has_trigger"),
      edge("support", "billing", "delegates_to"),
      edge("billing", "db", "uses_mcp"),
      edge("support", "github", "uses_openapi"),
    ],
  };

  it("draws the perimeter around what is inside and nothing else", () => {
    const layout = flowLayout(graph, size);
    for (const id of ["nightly", "support", "billing", "db"]) {
      expect(insideContour(at(layout, id), layout.perimeter)).toBe(true);
    }
    for (const id of ["hook", "github"]) {
      expect(insideContour(at(layout, id), layout.perimeter)).toBe(false);
    }
    expect(layout.insideCount).toBe(4);
  });

  it("reads left to right: sources, then the agent that hands off, then what it reaches", () => {
    const layout = flowLayout(graph, size);
    expect(at(layout, "hook").x).toBeLessThan(at(layout, "support").x);
    expect(at(layout, "support").x).toBeLessThan(at(layout, "billing").x);
    expect(at(layout, "support").x).toBeLessThan(at(layout, "github").x);
    expect(at(layout, "billing").x).toBeLessThan(at(layout, "db").x);
  });

  it("puts a recipient next to its sender and bends the perimeter around it", () => {
    const layout = flowLayout(
      {
        nodes: [
          node("a1"),
          node("a2"),
          node("a3"),
          node("gh", "openapi_connection", "egress"),
        ],
        edges: [
          edge("a1", "a2", "delegates_to"),
          edge("a2", "a3", "delegates_to"),
          edge("a1", "gh", "uses_openapi"),
        ],
      },
      size
    );
    expect(at(layout, "gh").x).toBe(at(layout, "a2").x);
    expect(insideContour(at(layout, "gh"), layout.perimeter)).toBe(false);
    for (const id of ["a1", "a2", "a3"]) {
      expect(insideContour(at(layout, id), layout.perimeter)).toBe(true);
    }
  });

  it("routes a long edge around the nodes it skips", () => {
    const layout = flowLayout(
      {
        nodes: [
          node("t", "trigger", null, "webhook"),
          node("a1"),
          node("a2"),
          node("a3"),
        ],
        edges: [
          edge("t", "a1", "has_trigger"),
          edge("a1", "a2", "delegates_to"),
          edge("a2", "a3", "delegates_to"),
          edge("t", "a3", "has_trigger"),
        ],
      },
      size
    );
    const route = layout.routes.get("t-a3-has_trigger") ?? [];
    expect(route.length).toBeGreaterThan(1);
    for (const id of ["a1", "a2"]) {
      const centre = at(layout, id);
      for (const bend of route) {
        expect(
          Math.hypot(bend.x - centre.x, bend.y - centre.y)
        ).toBeGreaterThan(20);
      }
    }
  });

  it("survives a delegation cycle", () => {
    const layout = flowLayout(
      {
        nodes: [node("a"), node("b")],
        edges: [edge("a", "b", "delegates_to"), edge("b", "a", "delegates_to")],
      },
      size
    );
    expect(layout.positions.size).toBe(2);
  });

  it("lands the same way whatever order the graph came in", () => {
    const reversed = {
      nodes: [...graph.nodes].reverse(),
      edges: [...graph.edges].reverse(),
    };
    expect([...flowLayout(reversed, size).positions].sort()).toEqual(
      [...flowLayout(graph, size).positions].sort()
    );
  });

  it("labels the sources, with no perimeter when nothing is inside", () => {
    const layout = flowLayout(
      {
        nodes: [
          node("p", "person"),
          node("gh", "openapi_connection", "egress"),
        ],
        edges: [],
      },
      size
    );
    expect(layout.labels.map((label) => label.zone)).toEqual(["inbound"]);
    expect(layout.perimeter).toEqual([]);
  });
});

describe("segmentsFor", () => {
  it("places each bend along and across the source-target line", () => {
    const segments = segmentsFor({ x: 0, y: 0 }, { x: 100, y: 0 }, [
      { x: 50, y: 20 },
    ]);
    expect(segments).toEqual({ weights: "0.5000", distances: "20.00" });
  });
});

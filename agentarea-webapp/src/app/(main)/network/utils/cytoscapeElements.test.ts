import cytoscape from "cytoscape";
import { describe, expect, it } from "vitest";
import type {
  CanvasEdge,
  CanvasNode,
  CanvasPoint,
} from "../components/networkCanvasTypes";
import type { NetworkNodeData, TopologyResponse } from "../types";
import {
  buildCytoscapeElements,
  getCanvasBounds,
  getEdgePoints,
  getSegmentCoordinates,
} from "./cytoscapeElements";
import { buildDirectionalLayout } from "./directionalLayout";
import { getDirectionalRoute } from "./directionalRoute";
import { getPersonRoute, withPeopleRoster } from "./peopleLayout";

function card(
  id: string,
  x: number,
  y: number,
  data: Record<string, unknown> = {}
): CanvasNode {
  return {
    id,
    type: "networkAgent",
    position: { x, y },
    width: 288,
    height: 104,
    data,
  };
}

function edge(
  source: string,
  target: string,
  id = `${source}/${target}`
): CanvasEdge {
  return {
    id,
    source,
    target,
    data: { relation: "delegates_to" },
    style: { stroke: "#667788", opacity: 0.6, strokeWidth: 2 },
  };
}

function topologyNode(
  id: string,
  type: NetworkNodeData["type"] = "agent",
  scope?: string
): NetworkNodeData {
  return {
    id,
    type,
    label: id,
    metadata: scope ? { network_scope: scope } : {},
  };
}

function directionalFixture(): TopologyResponse {
  return {
    nodes: [
      topologyNode("root"),
      topologyNode("left"),
      topologyNode("right"),
      topologyNode("end"),
      topologyNode("trigger", "trigger"),
      topologyNode("docs", "mcp_instance", "private"),
      topologyNode("skill", "skill", "private"),
      topologyNode("crm", "openapi_connection", "egress"),
      topologyNode("unknown", "mcp_instance"),
    ],
    edges: [
      { id: "left", source: "root", target: "left", relation: "delegates_to" },
      {
        id: "right",
        source: "root",
        target: "right",
        relation: "delegates_to",
      },
      { id: "end", source: "right", target: "end", relation: "delegates_to" },
      {
        id: "start",
        source: "root",
        target: "trigger",
        relation: "has_trigger",
      },
      { id: "docs1", source: "left", target: "docs", relation: "uses_mcp" },
      { id: "docs2", source: "right", target: "docs", relation: "uses_mcp" },
      { id: "skill", source: "end", target: "skill", relation: "has_skill" },
      { id: "crm", source: "right", target: "crm", relation: "uses_openapi" },
      {
        id: "unknown",
        source: "root",
        target: "unknown",
        relation: "uses_mcp",
      },
    ],
    governance: [],
    deployment_mode: "oss",
  };
}

function assertPointsEqual(actual: CanvasPoint, expected: CanvasPoint) {
  expect(actual.x).toBeCloseTo(expected.x, 8);
  expect(actual.y).toBeCloseTo(expected.y, 8);
}

function checkGeometry(nodes: CanvasNode[], edges: CanvasEdge[]) {
  const elements = buildCytoscapeElements(nodes, edges);
  const graph = cytoscape({
    headless: true,
    elements,
    layout: { name: "preset" },
  });
  try {
    expect(graph.edges()).toHaveLength(edges.length);
    for (const connection of edges) {
      const rendered = graph.getElementById(`e:${connection.id}`);
      const points = getEdgePoints(connection, nodes);
      const source = rendered.source().position();
      const target = rendered.target().position();
      const weights: number[] = rendered.data("weights");
      const distances: number[] = rendered.data("distances");
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const length = Math.hypot(dx, dy);
      expect(weights).toHaveLength(points.length - 2);
      for (let index = 0; index < weights.length; index++) {
        assertPointsEqual(
          {
            x:
              source.x + dx * weights[index] - (dy / length) * distances[index],
            y:
              source.y + dy * weights[index] + (dx / length) * distances[index],
          },
          points[index + 1]
        );
      }
      for (const [field, origin, expected] of [
        ["sourceEndpoint", source, points[0]],
        ["targetEndpoint", target, points[points.length - 1]],
      ] as const) {
        const offsets = String(rendered.data(field)).split(" ").map(parseFloat);
        assertPointsEqual(
          { x: origin.x + offsets[0], y: origin.y + offsets[1] },
          expected
        );
      }
    }
  } finally {
    graph.destroy();
  }
}

describe("Cytoscape element adapter", () => {
  it("keeps node and edge IDs distinct, preserves real adjacency and callback identity", () => {
    const nodes = [card("shared", 0, 0), card("e:shared", 400, 200)];
    const connection = {
      ...edge("shared", "e:shared", "shared"),
      selected: true,
      label: "Configured delegation",
      style: {
        stroke: "hsl(var(--primary))",
        strokeWidth: 3,
        opacity: 0.7,
        strokeDasharray: "4 3",
      },
    };
    const before = JSON.stringify({ nodes, connection });
    const graph = cytoscape({
      headless: true,
      elements: buildCytoscapeElements(nodes, [connection]),
      layout: { name: "preset" },
    });
    try {
      expect(graph.nodes()).toHaveLength(2);
      expect(graph.edges()).toHaveLength(1);
      const source = graph.getElementById("n:shared");
      const route = graph.getElementById("e:shared");
      expect(source.position()).toEqual({ x: 144, y: 52 });
      expect(source.outgoers("node").map((node) => node.id())).toEqual([
        "n:e:shared",
      ]);
      expect(route.source().id()).toBe("n:shared");
      expect(route.target().id()).toBe("n:e:shared");
      expect(route.data()).toMatchObject({
        originalId: "shared",
        selected: true,
        stroke: "hsl(var(--primary))",
        width: 3,
        opacity: 0.7,
        dashed: true,
        label: "Configured delegation",
      });
    } finally {
      graph.destroy();
    }
    expect(JSON.stringify({ nodes, connection })).toBe(before);
  });

  it("filters dangling, self and duplicate edges without mutating the topology", () => {
    const nodes = [card("a", 0, 0), card("b", 400, 0), card("a", 900, 0)];
    const connections = [
      edge("a", "b"),
      edge("a", "missing"),
      edge("a", "a"),
      edge("a", "b"),
    ];
    const elements = buildCytoscapeElements(nodes, connections);
    expect(elements.filter(({ group }) => group === "nodes")).toHaveLength(2);
    expect(elements.filter(({ group }) => group === "edges")).toHaveLength(1);
    expect(nodes).toHaveLength(3);
    expect(connections).toHaveLength(4);
  });

  it("preserves configured directional routes across groups and workspace boundaries", () => {
    const layout = buildDirectionalLayout(directionalFixture());
    const nodes: CanvasNode[] = layout.nodes.map((node) => ({
      id: node.id,
      type: node.type === "agent" ? "networkAgent" : "organization",
      position: node.position,
      width: node.type === "agent" ? 288 : 240,
      height: 104,
      data: node,
    }));
    const edges: CanvasEdge[] = layout.edges.map((connection) => {
      const route = getDirectionalRoute(
        connection,
        layout.nodes,
        layout.regions
      );
      return {
        ...edge(connection.source, connection.target, connection.id),
        data: {
          relation: connection.relation,
          points: route.points,
          labelPosition: route.label,
        },
      };
    });
    checkGeometry(nodes, edges);
  });

  it("preserves selected participant row endpoints and routes around agent cards", () => {
    const layout = withPeopleRoster(
      buildDirectionalLayout(directionalFixture()),
      260
    );
    const target = layout.nodes.find(({ id }) => id === "right");
    if (!target) throw new Error("Missing target agent");
    const route = getPersonRoute(
      {
        position: layout.peoplePosition,
        sourceOffset: 202,
        sourceId: "people",
      },
      target,
      layout
    );
    const nodes: CanvasNode[] = [
      {
        ...card("people", layout.peoplePosition.x, layout.peoplePosition.y),
        type: "people",
        width: 240,
        height: 260,
      },
      card(target.id, target.position.x, target.position.y),
    ];
    checkGeometry(nodes, [
      {
        ...edge("people", target.id),
        data: { relation: "can_execute", points: route.points },
      },
    ]);
  });

  it("generates orthogonal horizontal and vertical routes in both directions", () => {
    for (const horizontal of [true, false]) {
      const nodes = [
        card("a", 0, 0, { _horizontal: horizontal }),
        card("b", 500, 300, { _horizontal: horizontal }),
      ];
      const connections = [edge("a", "b"), edge("b", "a")];
      for (const connection of connections) {
        const points = getEdgePoints(connection, nodes);
        for (let index = 1; index < points.length; index++) {
          expect(
            points[index].x === points[index - 1].x ||
              points[index].y === points[index - 1].y
          ).toBe(true);
        }
        const source = nodes.find(({ id }) => id === connection.source);
        const target = nodes.find(({ id }) => id === connection.target);
        if (!source || !target) throw new Error("Missing route endpoint");
        expect(points[0]).toEqual(
          horizontal
            ? { x: source.position.x + 288, y: source.position.y + 52 }
            : { x: source.position.x + 144, y: source.position.y + 104 }
        );
        expect(points.at(-1)).toEqual(
          horizontal
            ? { x: target.position.x, y: target.position.y + 52 }
            : { x: target.position.x + 144, y: target.position.y }
        );
      }
      checkGeometry(nodes, connections);
    }
  });

  it("anchors a selected participant outside the first four rows at the visible fourth row", () => {
    const nodes: CanvasNode[] = [
      {
        ...card("people", 0, 0, {
          selectedId: "p5",
          people: Array.from({ length: 6 }, (_, index) => ({
            user_id: `p${index}`,
          })),
        }),
        type: "people",
        width: 240,
        height: 260,
      },
      card("a", 500, 300),
    ];
    expect(getEdgePoints(edge("people", "a"), nodes)[0]).toEqual({
      x: 240,
      y: 202,
    });
  });

  it("removes repeated points and handles coincident centers without non-finite coordinates", () => {
    const nodes = [card("a", 0, 0), card("b", 0, 0)];
    const points = [
      { x: 288, y: 52 },
      { x: 288, y: 52 },
      { x: 0, y: 52 },
    ];
    const connection = {
      ...edge("a", "b"),
      data: { relation: "delegates_to", points },
    };
    expect(getEdgePoints(connection, nodes)).toEqual([points[0], points[2]]);
    expect(connection.data.points).toHaveLength(3);
    const route = buildCytoscapeElements(nodes, [connection]).find(
      ({ group }) => group === "edges"
    );
    expect(route?.data).toMatchObject({
      curveStyle: "straight",
      weights: [],
      distances: [],
      sourceEndpoint: "144px 0px",
      targetEndpoint: "-144px 0px",
    });
    expect(
      getSegmentCoordinates({ x: 0, y: 0 }, { x: 0, y: 0 }, [{ x: 20, y: 40 }])
    ).toEqual({ weights: [], distances: [] });
  });
});

describe("getCanvasBounds", () => {
  const nodes: CanvasNode[] = [
    { ...card("workspace", -40, -60), type: "region", width: 900, height: 700 },
    card("a", 0, 0),
    card("b", 500, 300),
  ];

  it("includes workspace borders in the whole-map fit", () => {
    expect(getCanvasBounds(nodes)).toEqual({
      x: -40,
      y: -60,
      width: 900,
      height: 700,
    });
  });
  it("fits matching entity IDs without expanding to the workspace border", () => {
    expect(getCanvasBounds(nodes, ["a", "workspace"])).toEqual({
      x: 0,
      y: 0,
      width: 288,
      height: 104,
    });
    expect(getCanvasBounds(nodes, ["a", "b"])).toEqual({
      x: 0,
      y: 0,
      width: 788,
      height: 404,
    });
  });
  it("uses whole-map bounds when a focused entity disappears and handles an empty map", () => {
    expect(getCanvasBounds(nodes, ["deleted"])).toEqual(getCanvasBounds(nodes));
    expect(getCanvasBounds([])).toEqual({ x: 0, y: 0, width: 1, height: 1 });
  });
});

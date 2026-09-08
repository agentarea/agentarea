import { describe, expect, it } from "vitest";
import type {
  NetworkEdgeData,
  NetworkNodeData,
  TopologyResponse,
} from "../types";
import { buildDirectionalLayout } from "./directionalLayout";
import { getDirectionalRoute } from "./directionalRoute";

function node(
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
function edge(
  source: string,
  target: string,
  relation = "delegates_to"
): NetworkEdgeData {
  return { id: `${source}/${relation}/${target}`, source, target, relation };
}
function sample(): TopologyResponse {
  const agents = [
    "root",
    "child-a",
    "child-b",
    "child-c",
    "grandchild",
    "independent",
  ].map((id) => node(id));
  const resources = [
    node("private-a", "mcp_instance", "private"),
    node("private-b", "skill", "private"),
    node("external-a", "openapi_connection"),
    node("external-b", "mcp_instance", "egress"),
    node("external-c", "skill", "egress"),
    node("external-d", "mcp_instance", "egress"),
    node("unknown", "mcp_instance"),
  ];
  return {
    deployment_mode: "oss",
    governance: [],
    nodes: [
      ...agents,
      ...resources,
      node("trigger-a", "trigger"),
      node("trigger-b", "trigger"),
    ],
    edges: [
      edge("root", "child-a"),
      edge("root", "child-b"),
      edge("root", "child-c"),
      edge("child-a", "grandchild"),
      edge("root", "trigger-a", "has_trigger"),
      edge("independent", "trigger-b", "has_trigger"),
      ...agents.flatMap((agent) =>
        resources.map((resource) =>
          edge(
            agent.id,
            resource.id,
            resource.type === "skill"
              ? "has_skill"
              : resource.type === "openapi_connection"
                ? "uses_openapi"
                : "uses_mcp"
          )
        )
      ),
      edge("private-b", "external-c", "member_of"),
      edge("external-c", "private-b", "member_of"),
    ],
  };
}

type Point = { x: number; y: number };
function intersectsCard(
  start: Point,
  end: Point,
  card: NetworkNodeData & { position: Point }
): boolean {
  const left = card.position.x;
  const right = left + (card.type === "agent" ? 288 : 240);
  const top = card.position.y;
  const bottom = top + 104;
  if (start.x === end.x) {
    return (
      start.x > left &&
      start.x < right &&
      Math.max(Math.min(start.y, end.y), top) <
        Math.min(Math.max(start.y, end.y), bottom)
    );
  }
  if (start.y === end.y) {
    return (
      start.y > top &&
      start.y < bottom &&
      Math.max(Math.min(start.x, end.x), left) <
        Math.min(Math.max(start.x, end.x), right)
    );
  }
  throw new Error("Expected an orthogonal segment");
}
function verifyRoutes(input: TopologyResponse) {
  const layout = buildDirectionalLayout(input);
  for (const connection of layout.edges) {
    const route = getDirectionalRoute(connection, layout.nodes, layout.regions);
    expect(route.points.length, connection.id).toBeGreaterThan(1);
    for (let index = 1; index < route.points.length; index++) {
      const start = route.points[index - 1];
      const end = route.points[index];
      for (const card of layout.nodes) {
        if (card.id === connection.source || card.id === connection.target)
          continue;
        expect(
          intersectsCard(start, end, card),
          `${connection.id} segment ${index} intersects ${card.id}`
        ).toBe(false);
      }
    }
    const target = layout.nodes.find(({ id }) => id === connection.target);
    if (!target) throw new Error("Missing target");
    const end = route.points[route.points.length - 1];
    const previous = route.points[route.points.length - 2];
    if (route.targetHandle === "flow-target") {
      expect(end).toEqual({ x: target.position.x, y: target.position.y + 52 });
      expect(previous.y).toBe(end.y);
      expect(previous.x).toBeLessThan(end.x);
    } else {
      expect(end).toEqual({
        x: target.position.x + (target.type === "agent" ? 144 : 120),
        y: target.position.y,
      });
      expect(previous.x).toBe(end.x);
      expect(previous.y).toBeLessThan(end.y);
    }
  }
  return layout;
}

describe("getDirectionalRoute", () => {
  it("avoids unrelated cards across fork, grandchild, independent, shared, and resource routes", () => {
    verifyRoutes(sample());
  });

  it("uses explicit bottom-to-top delegation and right-to-top capability handles", () => {
    const layout = buildDirectionalLayout(sample());
    expect(
      getDirectionalRoute(edge("root", "child-a"), layout.nodes, layout.regions)
    ).toMatchObject({
      sourceHandle: "delegation-source",
      targetHandle: "delegation-target",
    });
    const resource = getDirectionalRoute(
      edge("root", "private-a", "uses_mcp"),
      layout.nodes,
      layout.regions
    );
    expect(resource.sourceHandle).toBe("flow-source");
    expect(resource.targetHandle).toBeUndefined();
    const trigger = getDirectionalRoute(
      edge("trigger-a", "root", "has_trigger"),
      layout.nodes,
      layout.regions
    );
    expect(trigger.sourceHandle).toBeUndefined();
    expect(trigger.targetHandle).toBe("flow-target");
    const membership = getDirectionalRoute(
      edge("private-b", "external-c", "member_of"),
      layout.nodes,
      layout.regions
    );
    expect(membership.sourceHandle).toBeUndefined();
    expect(membership.targetHandle).toBeUndefined();
  });

  it("avoids cards when delegation runs backwards around a cycle", () => {
    verifyRoutes({
      nodes: [node("a"), node("b"), node("c")],
      edges: [edge("a", "b"), edge("b", "c"), edge("c", "a")],
      governance: [],
      deployment_mode: "oss",
    });
  });

  it("approaches a second-column triggered agent from above when its sibling blocks the left port", () => {
    const input = {
      nodes: [
        node("root"),
        node("left"),
        node("right"),
        node("trigger", "trigger"),
      ],
      edges: [
        edge("root", "left"),
        edge("root", "right"),
        edge("right", "trigger", "has_trigger"),
      ],
      governance: [],
      deployment_mode: "oss",
    };
    const layout = verifyRoutes(input);
    const route = getDirectionalRoute(
      edge("trigger", "right", "has_trigger"),
      layout.nodes,
      layout.regions
    );
    expect(route.targetHandle).toBe("delegation-target");
  });

  it("handles long chains and wider forks without crossing a different rank", () => {
    const agents = Array.from({ length: 12 }, (_, index) =>
      node(`agent-${index}`)
    );
    for (const edges of [
      agents.slice(1).map((item, index) => edge(agents[index].id, item.id)),
      agents.slice(1).map((item) => edge(agents[0].id, item.id)),
    ]) {
      verifyRoutes({
        nodes: agents,
        edges,
        governance: [],
        deployment_mode: "oss",
      });
    }
  });

  it("is deterministic, puts labels on a route segment, and preserves layout data", () => {
    const layout = buildDirectionalLayout(sample());
    const before = structuredClone(layout);
    for (const connection of layout.edges) {
      const route = getDirectionalRoute(
        connection,
        layout.nodes,
        layout.regions
      );
      expect(
        getDirectionalRoute(
          connection,
          [...layout.nodes].reverse(),
          [...layout.regions].reverse()
        )
      ).toEqual(route);
      expect(
        route.points.slice(1).some((end, index) => {
          const start = route.points[index];
          return (
            route.label.y === start.y &&
            route.label.y === end.y &&
            route.label.x >= Math.min(start.x, end.x) &&
            route.label.x <= Math.max(start.x, end.x)
          );
        })
      ).toBe(true);
    }
    expect(layout).toEqual(before);
  });

  it("returns an empty route for missing endpoints and self edges", () => {
    const layout = buildDirectionalLayout(sample());
    for (const connection of [
      edge("missing", "root"),
      edge("root", "missing"),
      edge("root", "root"),
    ]) {
      expect(
        getDirectionalRoute(connection, layout.nodes, layout.regions)
      ).toEqual({ points: [], label: { x: 0, y: 0 } });
    }
  });
});

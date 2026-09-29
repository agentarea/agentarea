import { describe, expect, it } from "vitest";
import type { NetworkNodeData, TopologyResponse } from "../types";
import { buildDirectionalLayout } from "./directionalLayout";
import { getPersonRoute, withPeopleRoster } from "./peopleLayout";

function required<T>(value: T | undefined): T {
  if (value === undefined) throw new Error("Expected a layout item");
  return value;
}

function node(id: string, type: NetworkNodeData["type"] = "agent") {
  return { id, type, label: id, metadata: {} };
}

function fixture(withTriggers = true): TopologyResponse {
  return {
    nodes: [
      node("root"),
      node("left"),
      node("right"),
      node("end"),
      node("resource", "mcp_instance"),
      ...(withTriggers
        ? [node("trigger-a", "trigger"), node("trigger-b", "trigger")]
        : []),
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
      { id: "tool", source: "left", target: "resource", relation: "uses_mcp" },
      ...(withTriggers
        ? [
            {
              id: "a",
              source: "root",
              target: "trigger-a",
              relation: "has_trigger",
            },
            {
              id: "b",
              source: "end",
              target: "trigger-b",
              relation: "has_trigger",
            },
          ]
        : []),
    ],
    governance: [],
    deployment_mode: "oss",
  };
}

type Point = { x: number; y: number };
function intersects(
  start: Point,
  end: Point,
  card: NetworkNodeData & { position: Point }
) {
  const { x, y } = card.position;
  const right = x + (card.type === "agent" ? 288 : 240);
  const bottom = y + 104;
  if (start.x === end.x) {
    return (
      start.x > x &&
      start.x < right &&
      Math.max(Math.min(start.y, end.y), y) <
        Math.min(Math.max(start.y, end.y), bottom)
    );
  }
  expect(start.y).toBe(end.y);
  return (
    start.y > y &&
    start.y < bottom &&
    Math.max(Math.min(start.x, end.x), x) <
      Math.min(Math.max(start.x, end.x), right)
  );
}

describe("withPeopleRoster", () => {
  it("reserves the roster above triggers and expands only the input region", () => {
    const input = buildDirectionalLayout(fixture());
    const before = structuredClone(input);
    const result = withPeopleRoster(input, 260);
    const lane = required(result.regions.find(({ kind }) => kind === "inputs"));
    expect(result.peoplePosition).toEqual({
      x: lane.position.x + 24,
      y: lane.position.y + 64,
    });
    expect(result.peopleWidth).toBe(240);
    const triggers = result.nodes.filter(({ type }) => type === "trigger");
    expect(triggers[0].position.y).toBeGreaterThanOrEqual(
      result.peoplePosition.y + 260 + 32
    );
    expect(
      triggers[1].position.y - triggers[0].position.y
    ).toBeGreaterThanOrEqual(144);
    for (const trigger of triggers) {
      expect(trigger.position.x).toBeGreaterThanOrEqual(lane.position.x + 24);
      expect(trigger.position.x + 240).toBeLessThanOrEqual(
        lane.position.x + lane.width - 24
      );
      expect(trigger.position.y + 104).toBeLessThanOrEqual(
        lane.position.y + lane.height - 24
      );
    }
    expect(input).toEqual(before);
    expect(result.edges).toBe(input.edges);
    result.nodes.forEach((item, index) => {
      if (item.type !== "trigger") expect(item).toBe(input.nodes[index]);
    });
    result.regions.forEach((item, index) => {
      if (item.kind !== "inputs") expect(item).toBe(input.regions[index]);
    });
  });

  it("leaves already separated triggers at their existing positions", () => {
    const input = buildDirectionalLayout(fixture());
    const original = input.nodes.filter(({ type }) => type === "trigger");
    const result = withPeopleRoster(input, 1);
    expect(result.nodes.filter(({ type }) => type === "trigger")).toEqual(
      original
    );
    expect(result.nodes.filter(({ type }) => type === "trigger")[0]).toBe(
      original[0]
    );
  });

  it.each([120, 1200])(
    "contains a %ipx roster when there are no triggers",
    (height) => {
      const input = buildDirectionalLayout(fixture(false));
      const result = withPeopleRoster(input, height);
      const lane = required(
        result.regions.find(({ kind }) => kind === "inputs")
      );
      expect(result.nodes).toEqual(input.nodes);
      expect(lane.position.y + lane.height).toBeGreaterThanOrEqual(
        result.peoplePosition.y + height + 24
      );
    }
  );

  it("moves many triggers in visual order beyond a large roster without shrinking the lane", () => {
    const input = buildDirectionalLayout({
      ...fixture(false),
      nodes: [
        ...fixture(false).nodes,
        ...Array.from({ length: 9 }, (_, i) => node(`trigger-${i}`, "trigger")),
      ],
    });
    input.nodes.reverse();
    const before = structuredClone(input);
    const result = withPeopleRoster(input, 1500);
    const triggers = result.nodes
      .filter(({ type }) => type === "trigger")
      .sort((a, b) => a.position.y - b.position.y);
    expect(triggers[0].position.y).toBe(result.peoplePosition.y + 1532);
    triggers
      .slice(1)
      .forEach((trigger, i) =>
        expect(trigger.position.y - triggers[i].position.y).toBe(144)
      );
    const lane = required(result.regions.find(({ kind }) => kind === "inputs"));
    expect(lane.position.y + lane.height).toBe(
      required(triggers.at(-1)).position.y + 128
    );
    expect(input).toEqual(before);
    expect(
      required(
        withPeopleRoster(result, 1).regions.find(
          ({ kind }) => kind === "inputs"
        )
      ).height
    ).toBe(lane.height);
  });
});

describe("getPersonRoute", () => {
  it("enters an unobstructed agent through its left handle", () => {
    const layout = withPeopleRoster(buildDirectionalLayout(fixture()), 260);
    const target = required(layout.nodes.find(({ id }) => id === "root"));
    const route = getPersonRoute(
      {
        position: layout.peoplePosition,
        sourceOffset: 40,
        sourceId: "person-a",
      },
      target,
      layout
    );
    expect(route.sourceHandle).toBe("person-a");
    expect(route.targetHandle).toBe("flow-target");
    expect(route.points[0]).toEqual({
      x: layout.peoplePosition.x + 240,
      y: layout.peoplePosition.y + 40,
    });
    expect(route.points.at(-1)).toEqual({
      x: target.position.x,
      y: target.position.y + 52,
    });
  });

  it("uses the top handle when a sibling blocks the left approach", () => {
    const layout = withPeopleRoster(buildDirectionalLayout(fixture()), 260);
    const target = required(layout.nodes.find(({ id }) => id === "right"));
    const route = getPersonRoute(
      {
        position: layout.peoplePosition,
        sourceOffset: 60,
        sourceId: "person-b",
      },
      target,
      layout
    );
    expect(route.targetHandle).toBe("delegation-target");
    expect(route.points.at(-2)).toEqual({
      x: target.position.x + 144,
      y: target.position.y - 16,
    });
    expect(route.points.at(-1)).toEqual({
      x: target.position.x + 144,
      y: target.position.y,
    });
  });

  it.each([260, 1800])(
    "avoids unrelated entities for every agent and roster port in a %ipx roster",
    (height) => {
      const layout = withPeopleRoster(
        buildDirectionalLayout(fixture()),
        height
      );
      const before = structuredClone(layout);
      for (const target of layout.nodes.filter(
        ({ type }) => type === "agent"
      )) {
        for (const sourceOffset of [32, height / 2, height - 16]) {
          const route = getPersonRoute(
            {
              position: layout.peoplePosition,
              sourceOffset,
              sourceId: "person",
            },
            target,
            layout
          );
          route.points.slice(1).forEach((end, index) => {
            for (const other of layout.nodes) {
              if (other.id !== target.id)
                expect(
                  intersects(route.points[index], end, other),
                  `${target.id} route intersects ${other.id}`
                ).toBe(false);
            }
          });
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
      }
      expect(layout).toEqual(before);
    }
  );
});

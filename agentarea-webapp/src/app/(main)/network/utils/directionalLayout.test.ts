import { describe, expect, it } from "vitest";
import type {
  NetworkEdgeData,
  NetworkNodeData,
  TopologyResponse,
} from "../types";
import { buildDirectionalLayout } from "./directionalLayout";

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
function topology(
  nodes: NetworkNodeData[],
  edges: NetworkEdgeData[] = []
): TopologyResponse {
  return { nodes, edges, governance: [], deployment_mode: "oss" };
}
type Layout = ReturnType<typeof buildDirectionalLayout>;
function required<T>(value: T | undefined): T {
  if (value === undefined) throw new Error("Expected a layout item");
  return value;
}
function contains(
  region: Layout["regions"][number],
  item: { position: { x: number; y: number }; width: number; height: number },
  header = 64
) {
  expect(item.position.x).toBeGreaterThanOrEqual(region.position.x + 24);
  expect(item.position.y).toBeGreaterThanOrEqual(region.position.y + header);
  expect(item.position.x + item.width).toBeLessThanOrEqual(
    region.position.x + region.width - 24
  );
  expect(item.position.y + item.height).toBeLessThanOrEqual(
    region.position.y + region.height - 24
  );
}
function card(item: Layout["nodes"][number]) {
  return { ...item, width: item.type === "agent" ? 288 : 240, height: 104 };
}

describe("buildDirectionalLayout", () => {
  it("places inputs, workspace, and explicitly external resources in top-aligned regions", () => {
    const activation = edge("a", "t", "has_trigger");
    const result = buildDirectionalLayout(
      topology(
        [node("t", "trigger"), node("a"), node("m", "mcp_instance", "egress")],
        [activation, edge("a", "m", "uses_mcp")]
      )
    );
    const positions = new Map(
      result.nodes.map((item) => [item.id, item.position])
    );
    expect(required(positions.get("t")).x).toBeLessThan(
      required(positions.get("a")).x
    );
    expect(required(positions.get("a")).x).toBeLessThan(
      required(positions.get("m")).x
    );
    expect(
      result.regions
        .filter(({ kind }) => ["inputs", "workspace", "egress"].includes(kind))
        .map(({ position }) => position.y)
    ).toEqual([0, 0, 0]);
    expect(result.edges).toContainEqual({
      ...activation,
      source: "t",
      target: "a",
    });
  });

  it("clusters only delegation components, retaining a shared tool once and both incoming edges", () => {
    const result = buildDirectionalLayout(
      topology(
        [node("a"), node("b"), node("c"), node("shared", "mcp_instance")],
        [
          edge("a", "b"),
          edge("a", "shared", "uses_mcp"),
          edge("c", "shared", "uses_mcp"),
        ]
      )
    );
    expect(
      result.regions
        .filter(({ kind }) => kind === "agentCluster")
        .map(({ count }) => count)
    ).toEqual([2, 1]);
    expect(result.nodes.filter(({ id }) => id === "shared")).toHaveLength(1);
    expect(
      result.edges.filter(({ target }) => target === "shared")
    ).toHaveLength(2);
  });

  it("places a single delegation root first even when its label sorts last", () => {
    const result = buildDirectionalLayout(
      topology(
        [node("a-child"), node("z-root"), node("b-child")],
        [edge("z-root", "a-child"), edge("a-child", "b-child")]
      )
    );
    expect(
      result.nodes.filter(({ type }) => type === "agent").map(({ id }) => id)
    ).toEqual(["z-root", "a-child", "b-child"]);
    expect(
      result.regions.find(({ kind }) => kind === "agentCluster")?.label
    ).toBe("z-root");
  });

  it("keeps cycles and multi-root components unlabeled without losing agents", () => {
    const cycle = buildDirectionalLayout(
      topology([node("b"), node("a")], [edge("a", "b"), edge("b", "a")])
    );
    expect(cycle.nodes.map(({ id }) => id)).toEqual(["a", "b"]);
    expect(
      cycle.regions.find(({ kind }) => kind === "agentCluster")
    ).not.toHaveProperty("label");
    const multiRoot = buildDirectionalLayout(
      topology(
        [node("a"), node("b"), node("c")],
        [edge("a", "c"), edge("b", "c")]
      )
    );
    expect(multiRoot.nodes.map(({ id }) => id)).toEqual(["a", "b", "c"]);
    expect(
      multiRoot.regions.find(({ kind }) => kind === "agentCluster")
    ).not.toHaveProperty("label");
  });

  it("places every DAG target below its parents and centers singleton ranks", () => {
    const input = topology(
      [node("root"), node("left"), node("right"), node("joined"), node("end")],
      [
        edge("root", "left"),
        edge("root", "right"),
        edge("left", "joined"),
        edge("right", "joined"),
        edge("joined", "end"),
      ]
    );
    const result = buildDirectionalLayout(input);
    const cards = new Map(result.nodes.map((item) => [item.id, item]));
    for (const route of input.edges) {
      expect(required(cards.get(route.target)).position.y).toBeGreaterThan(
        required(cards.get(route.source)).position.y
      );
    }
    const cluster = required(
      result.regions.find(({ kind }) => kind === "agentCluster")
    );
    for (const id of ["root", "joined", "end"]) {
      expect(required(cards.get(id)).position.x + 144).toBe(
        cluster.position.x + cluster.width / 2
      );
    }
  });

  it("puts only explicit private resources inside the workspace and keeps missing OpenAPI scope unknown", () => {
    const result = buildDirectionalLayout(
      topology([
        node("private", "skill", "private"),
        node("egress", "mcp_instance", "egress"),
        node("unknown", "mcp_instance"),
        node("api", "openapi_connection"),
      ])
    );
    expect(
      result.regions
        .filter(({ kind }) => ["private", "egress", "unknown"].includes(kind))
        .map(({ kind, count }) => [kind, count])
    ).toEqual([
      ["private", 1],
      ["egress", 1],
      ["unknown", 2],
    ]);
    for (const item of result.nodes) {
      const scope = item.id === "api" ? "unknown" : item.id;
      contains(
        required(result.regions.find(({ kind }) => kind === scope)),
        card(item)
      );
    }
    const unknown = required(result.nodes.find(({ id }) => id === "unknown"));
    const api = required(result.nodes.find(({ id }) => id === "api"));
    expect(unknown.position.y).not.toBe(api.position.y);
    expect(unknown.position.x).toBe(api.position.x);
    const workspace = required(
      result.regions.find(({ kind }) => kind === "workspace")
    );
    const privateRegion = required(
      result.regions.find(({ kind }) => kind === "private")
    );
    const egressRegion = required(
      result.regions.find(({ kind }) => kind === "egress")
    );
    const unknownRegion = required(
      result.regions.find(({ kind }) => kind === "unknown")
    );
    contains(workspace, privateRegion);
    expect(egressRegion.position.x).toBeGreaterThan(
      workspace.position.x + workspace.width
    );
    expect(unknownRegion.position.y).toBeGreaterThan(
      egressRegion.position.y + egressRegion.height
    );
    expect(unknownRegion.position.x).toBe(egressRegion.position.x);
    expect(workspace.count).toBe(1);
  });

  it("fits cards and child regions with header clearance and no overlaps in dense groups", () => {
    const agents = Array.from({ length: 7 }, (_, index) =>
      node(`agent-${index}`)
    );
    const outputs = Array.from({ length: 9 }, (_, index) =>
      node(`tool-${index}`, "mcp_instance", "private")
    );
    const result = buildDirectionalLayout(
      topology(
        [...agents, ...outputs, node("trigger", "trigger")],
        agents.slice(1).map((item) => edge(agents[0].id, item.id))
      )
    );
    const cluster = required(
      result.regions.find(({ kind }) => kind === "agentCluster")
    );
    const resources = required(
      result.regions.find(({ kind }) => kind === "private")
    );
    const agentLane = required(
      result.regions.find(({ kind }) => kind === "agents")
    );
    const workspace = required(
      result.regions.find(({ kind }) => kind === "workspace")
    );
    contains(agentLane, cluster);
    contains(workspace, resources);
    contains(workspace, agentLane);
    expect(workspace.count).toBe(16);
    const agentCards = result.nodes.filter(({ type }) => type === "agent");
    const resourceCards = result.nodes.filter(
      ({ type }) => type === "mcp_instance"
    );
    const agentRows = new Map<number, number>();
    for (const item of agentCards)
      agentRows.set(item.position.y, (agentRows.get(item.position.y) ?? 0) + 1);
    expect(Math.max(...agentRows.values())).toBe(2);
    expect(new Set(resourceCards.map(({ position }) => position.x)).size).toBe(
      2
    );
    for (const item of result.nodes) {
      contains(
        item.type === "agent"
          ? cluster
          : item.type === "trigger"
            ? result.regions[0]
            : resources,
        card(item)
      );
    }
    const cards = result.nodes.map(card);
    for (let a = 0; a < cards.length; a++) {
      for (let b = a + 1; b < cards.length; b++) {
        const first = cards[a];
        const second = cards[b];
        const separated =
          first.position.x + first.width <= second.position.x ||
          second.position.x + second.width <= first.position.x ||
          first.position.y + first.height <= second.position.y ||
          second.position.y + second.height <= first.position.y;
        expect(separated).toBe(true);
      }
    }
  });

  it("keeps agent clusters apart and internal resources beside them inside the workspace", () => {
    const result = buildDirectionalLayout(
      topology([
        node("a"),
        node("b"),
        node("c"),
        node("p", "skill", "private"),
        node("e", "mcp_instance", "egress"),
        node("u", "skill"),
      ])
    );
    const groups = result.regions.filter(({ kind }) => kind === "agentCluster");
    groups
      .slice(1)
      .forEach((group, index) =>
        expect(group.position.y).toBeGreaterThanOrEqual(
          groups[index].position.y + groups[index].height + 32
        )
      );
    const agents = required(
      result.regions.find(({ kind }) => kind === "agents")
    );
    const privateRegion = required(
      result.regions.find(({ kind }) => kind === "private")
    );
    expect(privateRegion.position.y).toBe(agents.position.y);
    expect(privateRegion.position.x).toBeGreaterThanOrEqual(
      agents.position.x + agents.width + 32
    );
  });

  it("is deterministic under reordered input and does not mutate source data", () => {
    const input = topology(
      [
        node("c"),
        node("a"),
        node("b"),
        node("tool", "mcp_instance"),
        node("trigger", "trigger"),
      ],
      [
        edge("b", "c"),
        edge("a", "b"),
        edge("a", "trigger", "has_trigger"),
        edge("b", "tool", "uses_mcp"),
      ]
    );
    const before = structuredClone(input);
    const result = buildDirectionalLayout(input);
    expect(
      buildDirectionalLayout({
        ...input,
        nodes: [...input.nodes].reverse(),
        edges: [...input.edges].reverse(),
      })
    ).toEqual(result);
    expect(input).toEqual(before);
    expect(result.nodes.find(({ id }) => id === "tool")?.metadata).toBe(
      input.nodes[3].metadata
    );
  });

  it("drops dangling, self, and duplicate edges and emits each real node only once", () => {
    const agent = node("a");
    const route = edge("a", "b");
    const result = buildDirectionalLayout(
      topology(
        [agent, node("b"), agent],
        [
          route,
          route,
          edge("a", "a"),
          edge("missing", "a"),
          edge("a", "missing"),
        ]
      )
    );
    expect(result.nodes.map(({ id }) => id)).toEqual(["a", "b"]);
    expect(result.edges).toEqual([route]);
  });

  it("reserves collision-safe region IDs even when source IDs use its prefix", () => {
    const result = buildDirectionalLayout(
      topology([
        node("__network_region__:inputs"),
        node("__network_region__:agents"),
        node("__network_region__:workspace"),
      ])
    );
    const ids = [...result.nodes, ...result.regions].map(({ id }) => id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("retains empty lanes with room for hints and places isolated agents", () => {
    const empty = buildDirectionalLayout(topology([]));
    expect(empty.nodes).toEqual([]);
    expect(empty.edges).toEqual([]);
    expect(empty.regions.map(({ kind, count }) => [kind, count])).toEqual([
      ["inputs", 0],
      ["workspace", 0],
      ["agents", 0],
      ["private", 0],
      ["egress", 0],
    ]);
    empty.regions.forEach((region) => {
      expect(region.height).toBeGreaterThanOrEqual(192);
      expect(region.width).toBeGreaterThanOrEqual(288);
    });
    const isolated = buildDirectionalLayout(topology([node("alone")]));
    expect(isolated.nodes.map(({ id }) => id)).toEqual(["alone"]);
    expect(
      isolated.regions.find(({ kind }) => kind === "agentCluster")?.count
    ).toBe(1);
  });
  it("aligns incoming triggers with their target workflow before independent agents", () => {
    const layout = buildDirectionalLayout(
      topology(
        [
          node("a-independent"),
          node("z-root"),
          node("child"),
          node("webhook", "trigger"),
        ],
        [edge("z-root", "child"), edge("z-root", "webhook", "has_trigger")]
      )
    );
    const trigger = required(
      layout.nodes.find((item) => item.id === "webhook")
    );
    const root = required(layout.nodes.find((item) => item.id === "z-root"));
    const independent = required(
      layout.nodes.find((item) => item.id === "a-independent")
    );
    expect(trigger.position.y).toBe(root.position.y);
    expect(root.position.y).toBeLessThan(independent.position.y);
  });
});

import { describe, expect, it } from "vitest";
import type { NetworkPeopleAccessResponse } from "@/api/client/types.gen";
import type {
  NetworkEdgeData,
  NetworkNodeData,
  TopologyResponse,
} from "../types";
import {
  buildNetworkGraph,
  graphForLens,
  isolatedNodes,
  issueCount,
  lensFromView,
  pathThrough,
  personNodeId,
  personUserId,
  searchGraph,
} from "./networkGraph";

function node(
  id: string,
  type: NetworkNodeData["type"] = "agent",
  status: string | null = "active",
  metadata: Record<string, unknown> = {}
): NetworkNodeData {
  return { id, type, label: id, status, metadata };
}

function edge(source: string, target: string, relation: string) {
  return {
    id: `${source}-${target}-${relation}`,
    source,
    target,
    relation,
  } satisfies NetworkEdgeData;
}

function topology(
  nodes: NetworkNodeData[],
  edges: NetworkEdgeData[]
): TopologyResponse {
  return { nodes, edges, governance: [], deployment_mode: "oss" };
}

const sample = topology(
  [
    node("lead"),
    node("worker"),
    node("api", "openapi_connection", "active", { network_scope: "egress" }),
    node("db", "mcp_instance", "error", { network_scope: "private" }),
    node("spare", "mcp_instance", "active", { network_scope: "private" }),
    node("cron", "trigger", "inactive"),
  ],
  [
    edge("lead", "worker", "delegates_to"),
    edge("worker", "api", "uses_openapi"),
    edge("worker", "db", "uses_mcp"),
    edge("lead", "cron", "has_trigger"),
    edge("lead", "ghost", "delegates_to"),
  ]
);

const people: NetworkPeopleAccessResponse = {
  workspace_id: "ws",
  people: [
    { user_id: "u1", display_name: "Ann", email: null },
    { user_id: "u2", display_name: null, email: "bo@example.com" },
  ],
  access: [
    {
      user_id: "u1",
      agent_id: "lead",
      allowed: true,
      reason: "workspace scope",
    },
    { user_id: "u2", agent_id: "lead", allowed: false, reason: "policy" },
    {
      user_id: "u3",
      agent_id: "lead",
      allowed: true,
      reason: "workspace scope",
    },
  ],
} as NetworkPeopleAccessResponse;

describe("buildNetworkGraph", () => {
  it("points trigger links from the trigger to the agent it starts", () => {
    const graph = buildNetworkGraph(sample);
    const starts = graph.edges.find((item) => item.relation === "has_trigger");
    expect(starts).toMatchObject({ source: "cron", target: "lead", off: true });
  });

  it("drops edges to nodes the topology does not contain", () => {
    const graph = buildNetworkGraph(sample);
    expect(graph.edges.some((item) => item.target === "ghost")).toBe(false);
  });

  it("flags what needs attention", () => {
    const graph = buildNetworkGraph(sample);
    const issues = Object.fromEntries(
      graph.nodes.map((item) => [item.id, item.issues])
    );
    expect(issues).toEqual({
      lead: [],
      worker: [],
      api: [],
      db: ["resourceFailed"],
      spare: ["resourceUnused"],
      cron: ["triggerOff"],
    });
    expect(issueCount(graph)).toBe(3);
  });

  it("adds people from the roster and their access decisions", () => {
    const graph = buildNetworkGraph(sample, people);
    const persons = graph.nodes.filter((item) => item.kind === "person");
    expect(persons.map((item) => item.label)).toEqual([
      "Ann",
      "bo@example.com",
    ]);
    const access = graph.edges.filter(
      (item) => item.relation === "person_access"
    );
    expect(access.map((item) => [item.source, item.off])).toEqual([
      [personNodeId("u1"), false],
      [personNodeId("u2"), true],
    ]);
  });
});

describe("graphForLens", () => {
  const graph = buildNetworkGraph(sample, people);

  it("keeps resources out of the delegation lens", () => {
    const ids = graphForLens(graph, "delegation", false).nodes.map(
      (item) => item.id
    );
    expect(ids).toEqual(["lead", "worker", "cron"]);
  });

  it("shows people in the access lens whether or not they were asked for", () => {
    const access = graphForLens(graph, "access", false);
    expect(access.nodes.some((item) => item.kind === "person")).toBe(true);
    const overview = graphForLens(graph, "overview", false);
    expect(overview.nodes.some((item) => item.kind === "person")).toBe(false);
    expect(
      overview.edges.some((item) => item.relation === "person_access")
    ).toBe(false);
  });
});

describe("pathThrough", () => {
  it("collects everything upstream and downstream of a node", () => {
    const graph = buildNetworkGraph(sample);
    const path = pathThrough(graph, "worker");
    expect([...path.nodes].sort()).toEqual(
      ["api", "cron", "db", "lead", "worker"].sort()
    );
    expect(path.nodes.has("spare")).toBe(false);
  });
});

describe("searchGraph", () => {
  it("matches labels case-insensitively and ignores blank queries", () => {
    const graph = buildNetworkGraph(sample);
    expect(searchGraph(graph, "  WORK ").map((item) => item.id)).toEqual([
      "worker",
    ]);
    expect(searchGraph(graph, "   ")).toEqual([]);
  });
});

describe("person ids and lens parsing", () => {
  it("round-trips person node ids", () => {
    expect(personUserId(personNodeId("u1"))).toBe("u1");
    expect(personUserId("lead")).toBeNull();
  });

  it("falls back to the overview for unknown views", () => {
    expect(lensFromView("delegation")).toBe("delegation");
    expect(lensFromView("access")).toBe("access");
    expect(lensFromView("org")).toBe("overview");
    expect(lensFromView(null)).toBe("overview");
  });
});

describe("isolatedNodes", () => {
  it("lists nodes without edges, agents first", () => {
    const graph = buildNetworkGraph(
      topology(
        [
          node("zeta", "mcp_instance"),
          node("solo"),
          node("lead"),
          node("worker"),
          node("alpha", "openapi_connection"),
        ],
        [edge("lead", "worker", "delegates_to")]
      )
    );
    expect(isolatedNodes(graph).map((item) => item.id)).toEqual([
      "solo",
      "alpha",
      "zeta",
    ]);
  });
});

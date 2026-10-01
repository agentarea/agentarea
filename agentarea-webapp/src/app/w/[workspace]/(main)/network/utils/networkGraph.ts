import type {
  NetworkPeopleAccessResponse,
  NetworkPersonAgentAccess,
} from "@/api/client/types.gen";
import type { NetworkNodeData, TopologyResponse } from "../types";
import { getNetworkScope } from "./networkConnections";

export type GraphLens = "overview" | "delegation" | "access";
export type GraphKind = NetworkNodeData["type"] | "person";
export type GraphIssue =
  | "triggerOff"
  | "resourceFailed"
  | "resourceUnused"
  | "agentOff";

export interface GraphNode {
  id: string;
  label: string;
  kind: GraphKind;
  scope: "private" | "egress" | "unknown" | null;
  off: boolean;
  failed: boolean;
  degree: number;
  issues: GraphIssue[];
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relation: string;
  off: boolean;
  decision?: NetworkPersonAgentAccess;
}

export interface NetworkGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export const PERSON_PREFIX = "person:";

const FAILED = new Set(["error", "failed", "unhealthy"]);
const OFF = new Set(["inactive", "disabled", "stopped"]);
const RESOURCES = new Set<GraphKind>([
  "mcp_instance",
  "openapi_connection",
  "skill",
]);

export function isResource(kind: GraphKind) {
  return RESOURCES.has(kind);
}

export function personNodeId(userId: string) {
  return `${PERSON_PREFIX}${userId}`;
}

export function personUserId(nodeId: string): string | null {
  return nodeId.startsWith(PERSON_PREFIX)
    ? nodeId.slice(PERSON_PREFIX.length)
    : null;
}

/**
 * The topology and the people roster as one directed graph, edges pointing the
 * way work flows: a trigger starts its agent (storage keeps that link the other
 * way round), an agent delegates and calls, a person sends requests. Each node
 * carries what the canvas needs to draw it without looking anything up — its
 * scope, whether it is off or failing, how connected it is, and the problems a
 * reader should notice.
 */
export function buildNetworkGraph(
  topology: TopologyResponse,
  people?: NetworkPeopleAccessResponse | null
): NetworkGraph {
  const known = new Set(topology.nodes.map((node) => node.id));
  const edges: GraphEdge[] = [];
  const seen = new Set<string>();
  const byId = new Map(topology.nodes.map((node) => [node.id, node]));

  for (const edge of topology.edges) {
    if (
      seen.has(edge.id) ||
      edge.source === edge.target ||
      !known.has(edge.source) ||
      !known.has(edge.target)
    ) {
      continue;
    }
    seen.add(edge.id);
    const starts =
      edge.relation === "has_trigger" &&
      byId.get(edge.target)?.type === "trigger";
    const source = starts ? edge.target : edge.source;
    const target = starts ? edge.source : edge.target;
    edges.push({
      id: edge.id,
      source,
      target,
      relation: edge.relation,
      off: starts && isOff(byId.get(source)?.status),
    });
  }

  const roster = people?.people ?? [];
  for (const decision of people?.access ?? []) {
    if (!known.has(decision.agent_id)) continue;
    if (!roster.some((person) => person.user_id === decision.user_id)) continue;
    const id = `person_access:${decision.user_id}:${decision.agent_id}`;
    if (seen.has(id)) continue;
    seen.add(id);
    edges.push({
      id,
      source: personNodeId(decision.user_id),
      target: decision.agent_id,
      relation: "person_access",
      off: !decision.allowed,
      decision,
    });
  }

  const degree = new Map<string, number>();
  const consumed = new Set<string>();
  for (const edge of edges) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
    if (edge.relation !== "has_trigger" && edge.relation !== "member_of") {
      consumed.add(edge.target);
    }
  }

  const nodes: GraphNode[] = topology.nodes.map((node) => {
    const off = isOff(node.status);
    const failed = FAILED.has(node.status?.toLowerCase() ?? "");
    const issues: GraphIssue[] = [];
    if (node.type === "trigger" && off) issues.push("triggerOff");
    if (node.type === "agent" && off) issues.push("agentOff");
    if (isResource(node.type) && failed) issues.push("resourceFailed");
    if (isResource(node.type) && !consumed.has(node.id)) {
      issues.push("resourceUnused");
    }
    return {
      id: node.id,
      label: node.label,
      kind: node.type,
      scope: isResource(node.type) ? getNetworkScope(node) : null,
      off,
      failed,
      degree: degree.get(node.id) ?? 0,
      issues,
    };
  });

  for (const person of roster) {
    const id = personNodeId(person.user_id);
    nodes.push({
      id,
      label:
        person.display_name || person.email || `${person.user_id.slice(0, 8)}…`,
      kind: "person",
      scope: null,
      off: false,
      failed: false,
      degree: degree.get(id) ?? 0,
      issues: [],
    });
  }

  return { nodes, edges };
}

function isOff(status: string | null | undefined) {
  return OFF.has(status?.toLowerCase() ?? "");
}

/**
 * What each lens shows. Overview is everything configured; delegation keeps
 * only who hands work to whom and what starts it; access lays the whole chain
 * out from the people and triggers who send requests to the resources the
 * agents reach, so people are always part of it.
 */
export function graphForLens(
  graph: NetworkGraph,
  lens: GraphLens,
  showPeople: boolean
): NetworkGraph {
  const nodes = graph.nodes.filter((node) => {
    if (node.kind === "person") return showPeople || lens === "access";
    if (lens === "delegation") return !isResource(node.kind);
    return true;
  });
  const ids = new Set(nodes.map((node) => node.id));
  return {
    nodes,
    edges: graph.edges.filter(
      (edge) => ids.has(edge.source) && ids.has(edge.target)
    ),
  };
}

/**
 * Everything upstream and downstream of one node: what can start or reach it,
 * and everything it can in turn hand work to or call.
 */
export function pathThrough(graph: NetworkGraph, nodeId: string) {
  const outgoing = new Map<string, GraphEdge[]>();
  const incoming = new Map<string, GraphEdge[]>();
  for (const edge of graph.edges) {
    outgoing.set(edge.source, [...(outgoing.get(edge.source) ?? []), edge]);
    incoming.set(edge.target, [...(incoming.get(edge.target) ?? []), edge]);
  }
  const nodes = new Set([nodeId]);
  const edges = new Set<string>();
  const walk = (
    adjacency: Map<string, GraphEdge[]>,
    next: (edge: GraphEdge) => string
  ) => {
    const queue = [nodeId];
    const visited = new Set([nodeId]);
    while (queue.length) {
      const current = queue.shift() as string;
      for (const edge of adjacency.get(current) ?? []) {
        edges.add(edge.id);
        const other = next(edge);
        nodes.add(other);
        if (!visited.has(other)) {
          visited.add(other);
          queue.push(other);
        }
      }
    }
  };
  walk(outgoing, (edge) => edge.target);
  walk(incoming, (edge) => edge.source);
  return { nodes, edges };
}

export function issueCount(graph: NetworkGraph) {
  return graph.nodes.filter((node) => node.issues.length > 0).length;
}

export function searchGraph(graph: NetworkGraph, query: string) {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return [];
  return graph.nodes.filter((node) =>
    node.label.toLocaleLowerCase().includes(needle)
  );
}

export function lensFromView(view: string | null): GraphLens {
  return view === "delegation" || view === "access" ? view : "overview";
}

/** Nodes with no edge in this graph, agents first, then by name. */
export function isolatedNodes(graph: NetworkGraph): GraphNode[] {
  const linked = new Set(
    graph.edges.flatMap((edge) => [edge.source, edge.target])
  );
  return graph.nodes
    .filter((node) => !linked.has(node.id))
    .sort(
      (a, b) =>
        Number(b.kind === "agent") - Number(a.kind === "agent") ||
        a.label.localeCompare(b.label)
    );
}

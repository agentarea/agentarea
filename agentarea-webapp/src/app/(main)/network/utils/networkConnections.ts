import type { EntityKind } from "@/lib/entity-icons";
import {
  domainInitials,
  faviconSources,
  type EntityIdentity,
} from "@/lib/entity-identity";
import type {
  NetworkEdgeData,
  NetworkNodeData,
  TopologyResponse,
} from "../types";

type AgentConnection = {
  edge: NetworkEdgeData;
  node: NetworkNodeData;
};

const nodeKinds: Record<NetworkNodeData["type"], EntityKind> = {
  agent: "agent",
  mcp_instance: "mcp",
  openapi_connection: "client",
  skill: "skill",
  trigger: "trigger",
};

function metadataString(
  node: NetworkNodeData,
  key: string
): string | undefined {
  const value = node.metadata[key];
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

/**
 * How a topology node is depicted, from what `/topology` told us about it: the
 * MCP registry logo first, then the favicon of the host the connection points
 * at, then the kind's own mark. The graph never loads the connection records
 * themselves, which is why those nodes carry `icon_url`, `endpoint_host` and
 * `base_url` — everything needed to show a service as itself.
 */
export function getNodeIdentity(node: NetworkNodeData): EntityIdentity {
  const kind = nodeKinds[node.type];
  const logo = metadataString(node, "icon_url");
  if (logo) return { kind, sources: [logo] };

  const baseUrl = metadataString(node, "base_url");
  const host = metadataString(node, "endpoint_host") ?? baseUrl;
  return {
    kind,
    sources: faviconSources(host),
    initials:
      node.type === "openapi_connection"
        ? domainInitials(baseUrl, node.label)
        : undefined,
  };
}

export function getNetworkScope(
  node: NetworkNodeData
): "private" | "egress" | "unknown" {
  const scope = node.metadata.network_scope;
  if (scope === "private" || scope === "egress") return scope;
  return "unknown";
}

export function getAgentConnections(
  topology: TopologyResponse,
  agentId: string
): { incoming: AgentConnection[]; outgoing: AgentConnection[] } {
  const incoming: AgentConnection[] = [];
  const outgoing: AgentConnection[] = [];
  const nodes = new Map(topology.nodes.map((node) => [node.id, node]));
  if (!nodes.has(agentId)) return { incoming, outgoing };

  const seen = new Set<string>();
  for (const edge of topology.edges) {
    if (
      edge.source === edge.target ||
      seen.has(edge.id) ||
      (edge.source !== agentId && edge.target !== agentId)
    ) {
      continue;
    }
    const source = nodes.get(edge.source);
    const target = nodes.get(edge.target);
    if (!source || !target) continue;
    seen.add(edge.id);

    // Storage links agent -> trigger; operationally the trigger starts the agent.
    const triggerActivation =
      edge.relation === "has_trigger" &&
      source.type === "agent" &&
      target.type === "trigger";
    const flowSource = triggerActivation ? target : source;
    const flowTarget = triggerActivation ? source : target;
    if (flowTarget.id === agentId) {
      incoming.push({ edge, node: flowSource });
    } else {
      outgoing.push({ edge, node: flowTarget });
    }
  }
  return { incoming, outgoing };
}

export function focusAgentTopology(
  topology: TopologyResponse,
  agentId: string
): TopologyResponse {
  if (
    !topology.nodes.some((node) => node.id === agentId && node.type === "agent")
  ) {
    return topology;
  }

  const { incoming, outgoing } = getAgentConnections(topology, agentId);
  const connections = [...incoming, ...outgoing];
  const nodeIds = new Set([agentId, ...connections.map(({ node }) => node.id)]);
  const selectedEdges = new Set(connections.map(({ edge }) => edge));

  return {
    ...topology,
    nodes: topology.nodes.filter((node) => nodeIds.has(node.id)),
    edges: topology.edges.filter((edge) => selectedEdges.delete(edge)),
  };
}

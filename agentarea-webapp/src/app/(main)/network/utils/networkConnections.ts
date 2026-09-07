import type {
  NetworkEdgeData,
  NetworkNodeData,
  TopologyResponse,
} from "../types";

type AgentConnection = {
  edge: NetworkEdgeData;
  node: NetworkNodeData;
};

export function getNetworkScope(
  node: NetworkNodeData
): "private" | "egress" | "unknown" {
  const scope = node.metadata.network_scope;
  if (scope === "private" || scope === "egress") return scope;
  // The topology API defines OpenAPI connections as external resources.
  return node.type === "openapi_connection" ? "egress" : "unknown";
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

import type { NetworkNodeData, TopologyResponse } from "../types";

export const NETWORK_AGENT_WIDTH = 288;
export const NETWORK_RESOURCE_LIMIT = 4;

export type AgentResource = { node: NetworkNodeData; sharedBy: number };

const resourceRelations = new Set([
  "uses_mcp",
  "uses_openapi",
  "has_skill",
  "has_trigger",
]);

const typeOrder: Record<NetworkNodeData["type"], number> = {
  trigger: 0,
  mcp_instance: 1,
  openapi_connection: 1,
  skill: 2,
  agent: 3,
};

function compareText(a: string, b: string) {
  return a < b ? -1 : a > b ? 1 : 0;
}

export function getAgentResources(
  topology: TopologyResponse
): Map<string, AgentResource[]> {
  const nodesById = new Map(topology.nodes.map((node) => [node.id, node]));
  const agents = topology.nodes
    .filter((node) => node.type === "agent")
    .sort((a, b) => compareText(a.label, b.label) || compareText(a.id, b.id));
  const resourcesByAgent = new Map(
    agents.map((agent) => [agent.id, new Map<string, NetworkNodeData>()])
  );
  const agentsByResource = new Map<string, Set<string>>();

  for (const edge of topology.edges) {
    const resources = resourcesByAgent.get(edge.source);
    const resource = nodesById.get(edge.target);
    if (
      !resources ||
      !resource ||
      resource.type === "agent" ||
      !resourceRelations.has(edge.relation)
    ) {
      continue;
    }
    resources.set(resource.id, resource);
    const users = agentsByResource.get(resource.id) ?? new Set<string>();
    users.add(edge.source);
    agentsByResource.set(resource.id, users);
  }

  return new Map(
    [...resourcesByAgent].map(([agentId, resources]) => [
      agentId,
      [...resources.values()]
        .map((node) => ({
          node,
          sharedBy: agentsByResource.get(node.id)?.size ?? 1,
        }))
        .sort(
          (a, b) =>
            typeOrder[a.node.type] - typeOrder[b.node.type] ||
            compareText(a.node.label, b.node.label) ||
            compareText(a.node.id, b.node.id)
        ),
    ])
  );
}

export function networkAgentHeight(
  resourceCount: number,
  expanded: boolean
): number {
  const visibleRows = expanded
    ? resourceCount
    : Math.min(resourceCount, NETWORK_RESOURCE_LIMIT);
  return (
    104 +
    36 +
    visibleRows * 28 +
    (resourceCount > NETWORK_RESOURCE_LIMIT ? 32 : 0)
  );
}

import type { TopologyResponse } from "../types";
import { getNetworkScope } from "./networkConnections";

export type AccessScope = "all" | "private" | "egress" | "unknown";

const accessRelations = new Set([
  "uses_mcp",
  "uses_openapi",
  "has_skill",
  "delegates_to",
]);

export function getAccessTopology(
  topology: TopologyResponse,
  scope: AccessScope = "all"
): TopologyResponse {
  const nodes = topology.nodes.filter((node) => {
    if (node.type === "agent") return true;
    if (
      node.type !== "mcp_instance" &&
      node.type !== "openapi_connection" &&
      node.type !== "skill"
    ) {
      return false;
    }
    return scope === "all" || getNetworkScope(node) === scope;
  });
  const nodeIds = new Set(nodes.map((node) => node.id));

  return {
    ...topology,
    nodes,
    edges: topology.edges.filter(
      (edge) =>
        accessRelations.has(edge.relation) &&
        nodeIds.has(edge.source) &&
        nodeIds.has(edge.target)
    ),
  };
}

export interface NetworkNodeData extends Record<string, unknown> {
  id: string;
  type: "agent" | "mcp_instance" | "openapi_connection" | "skill" | "trigger";
  label: string;
  status?: string | null;
  metadata: Record<string, unknown>;
}

export interface NetworkEdgeData {
  id: string;
  source: string;
  target: string;
  relation: string;
}

export interface TopologyResponse {
  nodes: NetworkNodeData[];
  edges: NetworkEdgeData[];
  governance: unknown[];
  deployment_mode: string;
}

export interface NetworkFlowNodeData extends NetworkNodeData {
  _dimmed?: boolean;
  _highlighted?: boolean;
}

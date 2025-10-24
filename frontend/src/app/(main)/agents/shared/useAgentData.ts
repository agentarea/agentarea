import {
  getAgent,
  listBuiltinTools,
  listMCPServerInstances,
  listMCPServers,
  listModelInstances,
  MCPServer,
} from "@/lib/api";

export interface AgentData {
  mcpServers: MCPServer[];
  llmModelInstances: any[];
  mcpInstanceList: any[];
  builtinTools: any[];
}

export interface AgentEditData extends AgentData {
  agent: any;
  initialData: any;
}

export async function loadAgentData(): Promise<AgentData> {
  // Fetch MCP servers
  const response = await listMCPServers();
  const mcpServers: MCPServer[] = (response.data || []).map(
    (server: MCPServer) => {
      const withDownloads = server as MCPServer & { downloads?: number };
      return {
        ...server,
        status: ["published", "draft", "pending", "rejected"].includes(
          server.status
        )
          ? (server.status as MCPServer["status"])
          : "draft",
        ...(typeof withDownloads.downloads === "number"
          ? { downloads: withDownloads.downloads }
          : {}),
      };
    }
  );

  // Fetch LLM model instances
  const llmResponse = await listModelInstances();
  const llmModelInstances = llmResponse.data || [];

  // Fetch MCP server instances
  const mcpInstancesResponse = await listMCPServerInstances();
  const mcpInstanceList = mcpInstancesResponse.data || [];

  // Fetch builtin tools
  const builtinToolsResponse = await listBuiltinTools();
  const builtinTools = Array.isArray(builtinToolsResponse.data)
    ? builtinToolsResponse.data
    : Object.values(builtinToolsResponse.data || {});

  return {
    mcpServers,
    llmModelInstances,
    mcpInstanceList,
    builtinTools,
  };
}

export async function loadAgentEditData(
  agentId: string
): Promise<AgentEditData> {
  // Load base data
  const baseData = await loadAgentData();

  // Fetch agent data
  const agentResponse = await getAgent(agentId);
  const agent = agentResponse.data;

  if (!agent) {
    throw new Error("Agent not found");
  }

  // Transform agent data to form format
  const initialData = {
    name: agent.name,
    description: agent.description || "",
    instruction: agent.instruction || "",
    model_id: agent.model_id,
    tools_config: {
      mcp_server_configs: agent.tools_config?.mcp_server_configs || [],
      builtin_tools: agent.tools_config?.builtin_tools || [],
    },
    events_config: {
      events: agent.events_config?.events || [],
    },
    planning: agent.planning || false,
  };

  return {
    ...baseData,
    agent,
    initialData,
  };
}

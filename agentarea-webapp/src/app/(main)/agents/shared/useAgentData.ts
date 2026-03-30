import {
  getAgent,
  listAllTools,
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
  const response = await listMCPServers({ page_size: 100 });
  const rawServers = (response.data as any)?.items || response.data || [];
  const mcpServers: MCPServer[] = rawServers.map((server: MCPServer) => {
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
  });

  // Fetch LLM model instances
  const llmResponse = await listModelInstances();
  const llmModelInstances = llmResponse.data || [];

  // Fetch MCP server instances
  const mcpInstancesResponse = await listMCPServerInstances();
  const mcpInstanceList = mcpInstancesResponse.data || [];

  // Fetch code tools (previously called builtin tools)
  const codeToolsResponse = await listAllTools({ include: "code" });
  const builtinTools = codeToolsResponse.data || [];

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
      mcp_server_configs: (agent.tools || [])
        .filter((t: any) => t.type === "mcp")
        .map((t: any) => ({ server_name: t.name, ...(t.settings || {}) })),
      builtin_tools: (agent.tools || [])
        .filter((t: any) => t.type === "code")
        .map((t: any) => t.name),
    },
    events_config: {
      events: (agent as any).events_config?.events || [],
    },
    planning: agent.planning || false,
    skills: ((agent as any).skills || []).map((s: any) => ({
      id: s.id,
      name: s.name,
      description: s.description,
    })),
  };

  return {
    ...baseData,
    agent,
    initialData,
  };
}

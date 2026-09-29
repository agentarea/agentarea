import {
  getAgent,
  listAllTools,
  listMCPServerInstances,
  listMCPServers,
  listModelInstances,
} from "@/lib/api";
import type {
  Agent,
  MCPServer,
  MCPServerInstance,
  ModelInstance,
} from "@/lib/api";
import type { AgentFormValues } from "../create/types";
import { fromAgent } from "./agentContract";

export interface AgentData {
  mcpServers: MCPServer[];
  llmModelInstances: ModelInstance[];
  mcpInstanceList: MCPServerInstance[];
  builtinTools: unknown[];
}

export interface AgentEditData extends AgentData {
  agent: Agent;
  initialData: AgentFormValues;
}

export async function loadAgentData(): Promise<AgentData> {
  // Fetch MCP servers
  const response = await listMCPServers({ page_size: 100 });
  const rawServers = response.data?.items ?? [];
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
  const agent: Agent | undefined = agentResponse.data;

  if (!agent) {
    throw new Error("Agent not found");
  }

  return {
    ...baseData,
    agent,
    initialData: fromAgent(agent),
  };
}

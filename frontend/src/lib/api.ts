import type { components } from "../api/schema";
import { createApiClient } from "./api-factory";
import { getServerClient } from "./server-client";

// Create API client using server client
const api = createApiClient(getServerClient());

// Re-export all API functions
export const {
  // Agent API
  listAgents,
  createAgent,
  getAgent,
  deleteAgent,
  updateAgent,

  // Agent Task API
  listAgentTasks,
  createAgentTask,
  getAgentTask,
  getAgentTaskById,
  cancelAgentTask,
  getAgentTaskStatus,
  pauseAgentTask,
  resumeAgentTask,
  getAgentTaskEvents,

  // Chat API
  sendMessage,
  getChatAgents,
  getChatAgent,
  getChatMessageStatus,

  // MCP Server API
  listMCPServers,
  createMCPServer,
  getMCPServer,
  deleteMCPServer,
  updateMCPServer,
  deployMCPServer,

  // MCP Server Instance API
  listMCPServerInstances,
  checkMCPServerInstanceConfiguration,
  createMCPServerInstance,
  getMCPServerInstance,
  deleteMCPServerInstance,
  updateMCPServerInstance,
  startMCPServerInstance,
  stopMCPServerInstance,
  getMCPServerInstanceEnvironment,

  // Provider Spec API
  listProviderSpecs,
  listProviderSpecsWithModels,
  getProviderSpec,
  getProviderSpecByKey,

  // Provider Config API
  listProviderConfigs,
  createProviderConfig,
  getProviderConfig,
  updateProviderConfig,
  deleteProviderConfig,

  // Model Spec API
  listModelSpecs,
  createModelSpec,
  getModelSpec,
  deleteModelSpec,
  updateModelSpec,
  listModelSpecsByProvider,
  getModelSpecByProviderAndName,
  upsertModelSpec,

  // Model Instance API
  listModelInstances,
  createModelInstance,
  testModelInstance,
  getModelInstance,
  deleteModelInstance,

  // Utility API
  healthCheck,

  // Auth API
  getCurrentUser,
  testProtectedEndpoint,

  // Built-in Tools API
  listBuiltinTools,

  // MCP health
  getMCPHealthStatus,
} = api;

// Convenience helpers built on top of the generated API
export const getAgentTaskMessages = async (agentId: string, taskId: string) => {
  // Build message history from task events
  const { data: events, error } = await getAgentTaskEvents(agentId, taskId, {
    page_size: 100,
  } as any);
  if (error || !events) {
    return { data: [], error };
  }

  const messages = (events as any).events
    .filter((event: any) =>
      ["LLMCallCompleted", "ToolCallCompleted", "WorkflowCompleted"].includes(
        event.event_type
      )
    )
    .map((event: any) => ({
      id: event.id,
      content: event.data?.content || event.data?.result || "",
      role: event.event_type === "LLMCallCompleted" ? "assistant" : "system",
      timestamp: event.timestamp,
    }));

  return { data: messages, error: null };
};

export const getAllTasks = async () => {
  const { data: agents, error: agentsError } = await listAgents();
  if (agentsError || !agents) return { data: null, error: agentsError };

  const tasks = await Promise.all(
    agents.map(async (agent: any) => {
      const { data: agentTasks, error } = await listAgentTasks(agent.id);
      if (error || !agentTasks) return [];

      return agentTasks.map((task: any) => ({
        ...task,
        agent_name: agent.name,
        agent_description: agent.description,
      }));
    })
  );

  return { data: tasks.flat(), error: null };
};

export const listProviderConfigsWithModelInstances = async (params?: {
  provider_spec_id?: string;
  is_active?: boolean;
}) => {
  const [providersResponse, configsResponse] = await Promise.all([
    listProviderSpecsWithModels(),
    listProviderConfigs(params),
  ]);
  if (configsResponse.error || !configsResponse.data) {
    return configsResponse;
  }
  const configs = configsResponse.data || [];
  const specsWithModels = providersResponse.data || [];
  const specsById = Object.fromEntries(
    specsWithModels.map((s: any) => [s.id, s])
  );
  const configsWithModels = configs.map((config: any) => ({
    ...config,
    models_list: config.model_instance_ids
      .map((modelSpecId: string) => {
        const providerSpec = specsById[config.provider_spec_id];
        if (!providerSpec) return null;
        return (
          providerSpec.models.find((m: any) => m.id === modelSpecId) || null
        );
      })
      .filter(Boolean),
  }));

  return { data: configsWithModels, error: null };
};

export const getProvidersAndConfigs = async () => {
  const [{ data: specs }, { data: configs }] = await Promise.all([
    listProviderSpecs(),
    listProviderConfigs(),
  ]);

  return {
    data: { providerSpecs: specs || [], providerConfigs: configs || [] },
    error: null,
  };
};

export type Agent =
  components["schemas"]["agentarea_api__api__v1__agents__AgentResponse"];
export type MCPServer = components["schemas"]["MCPServerResponse"];
export type MCPServerInstance =
  components["schemas"]["MCPServerInstanceResponse"];
export type ProviderSpec = components["schemas"]["ProviderSpecResponse"];
export type ProviderSpecWithModels =
  components["schemas"]["ProviderSpecWithModelsResponse"];
export type ProviderConfig = components["schemas"]["ProviderConfigResponse"];
export type ModelSpec =
  components["schemas"]["agentarea_api__api__v1__model_specs__ModelSpecResponse"];
export type ModelInstance = components["schemas"]["ModelInstanceResponse"];
export type ChatAgent =
  components["schemas"]["agentarea_api__api__v1__chat__AgentResponse"];
export type ChatResponse = components["schemas"]["ChatResponse"];
export type ConversationResponse = any;
export type TaskResponse = components["schemas"]["TaskResponse"];
export type AgentCard = components["schemas"]["AgentCard"];
export type TaskWithAgent = TaskResponse & {
  agent_name?: string;
  agent_description?: string | null;
};

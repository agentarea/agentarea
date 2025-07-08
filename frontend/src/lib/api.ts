import client from "./client";
import type { components } from "../api/schema";

// Agent API
export const listAgents = async () => {
  const { data, error } = await client.GET("/v1/agents/");
  return { data, error };
};

export const createAgent = async (agent: components["schemas"]["AgentCreate"]) => {
  const { data, error } = await client.POST("/v1/agents/", { body: agent });
  return { data, error };
};

export const getAgent = async (agentId: string) => {
  const { data, error } = await client.GET("/v1/agents/{agent_id}", {
    params: { path: { agent_id: agentId } },
  });
  return { data, error };
};

export const deleteAgent = async (agentId: string) => {
  const { data, error } = await client.DELETE("/v1/agents/{agent_id}", {
    params: { path: { agent_id: agentId } },
  });
  return { data, error };
};

export const updateAgent = async (agentId: string, agent: components["schemas"]["AgentUpdate"]) => {
  const { data, error } = await client.PATCH("/v1/agents/{agent_id}", {
    params: { path: { agent_id: agentId } },
    body: agent,
  });
  return { data, error };
};

// Agent Task API
export const listAgentTasks = async (agentId: string) => {
  const { data, error } = await client.GET("/v1/agents/{agent_id}/tasks/", {
    params: { path: { agent_id: agentId } },
  });
  return { data, error };
};

export const createAgentTask = async (agentId: string, task: components["schemas"]["TaskCreate"]) => {
  const { data, error } = await client.POST("/v1/agents/{agent_id}/tasks/", {
    params: { path: { agent_id: agentId } },
    body: task,
  });
  return { data, error };
};

export const getAgentTask = async (agentId: string, taskId: string) => {
  const { data, error } = await client.GET("/v1/agents/{agent_id}/tasks/{task_id}", {
    params: { path: { agent_id: agentId, task_id: taskId } },
  });
  return { data, error };
};

export const cancelAgentTask = async (agentId: string, taskId: string) => {
  const { data, error } = await client.DELETE("/v1/agents/{agent_id}/tasks/{task_id}", {
    params: { path: { agent_id: agentId, task_id: taskId } },
  });
  return { data, error };
};

export const getAgentTaskStatus = async (agentId: string, taskId: string) => {
  const { data, error } = await client.GET("/v1/agents/{agent_id}/tasks/{task_id}/status", {
    params: { path: { agent_id: agentId, task_id: taskId } },
  });
  return { data, error };
};

// Chat API
export const sendMessage = async (message: components["schemas"]["ChatMessageRequest"]) => {
  const { data, error } = await client.POST("/v1/chat/messages", { body: message });
  return { data, error };
};

export const streamMessage = async (message: components["schemas"]["ChatMessageRequest"]) => {
  const { data, error } = await client.POST("/v1/chat/messages/stream", { body: message });
  return { data, error };
};

export const getConversationHistory = async (sessionId: string) => {
  const { data, error } = await client.GET("/v1/chat/conversations/{session_id}/messages", {
    params: { path: { session_id: sessionId } },
  });
  return { data, error };
};

export const listConversations = async (params?: { user_id?: string }) => {
  const { data, error } = await client.GET("/v1/chat/conversations", {
    params: { query: params },
  });
  return { data, error };
};

export const getChatAgents = async () => {
  const { data, error } = await client.GET("/v1/chat/agents");
  return { data, error };
};

export const getChatAgent = async (agentId: string) => {
  const { data, error } = await client.GET("/v1/chat/agents/{agent_id}", {
    params: { path: { agent_id: agentId } },
  });
  return { data, error };
};

// Protocol API
export const handleJsonRpc = async (request: any) => {
  const { data, error } = await client.POST("/v1/protocol/rpc", { body: request });
  return { data, error };
};

export const getAgentCard = async (agentId: string) => {
  const { data, error } = await client.GET("/v1/protocol/agents/{agent_id}/card", {
    params: { path: { agent_id: agentId } },
  });
  return { data, error };
};

export const handleAgUiRequest = async (request: components["schemas"]["AGUIRequest"]) => {
  const { data, error } = await client.POST("/v1/protocol/ag-ui", { body: request });
  return { data, error };
};

export const protocolHealthCheck = async () => {
  const { data, error } = await client.GET("/v1/protocol/health");
  return { data, error };
};

export const chatHealthCheck = async () => {
  const { data, error } = await client.GET("/v1/chat/health");
  return { data, error };
};

// MCP Server API
export const listMCPServers = async (params?: {
  status?: string;
  is_public?: boolean;
  tag?: string;
}) => {
  const { data, error } = await client.GET("/v1/mcp-servers/", {
    params: { query: params },
  });
  return { data, error };
};

export const createMCPServer = async (server: components["schemas"]["MCPServerCreate"]) => {
  const { data, error } = await client.POST("/v1/mcp-servers/", { body: server });
  return { data, error };
};

export const getMCPServer = async (serverId: string) => {
  const { data, error } = await client.GET("/v1/mcp-servers/{server_id}", {
    params: { path: { server_id: serverId } },
  });
  return { data, error };
};

export const deleteMCPServer = async (serverId: string) => {
  const { data, error } = await client.DELETE("/v1/mcp-servers/{server_id}", {
    params: { path: { server_id: serverId } },
  });
  return { data, error };
};

export const updateMCPServer = async (serverId: string, server: components["schemas"]["MCPServerUpdate"]) => {
  const { data, error } = await client.PATCH("/v1/mcp-servers/{server_id}", {
    params: { path: { server_id: serverId } },
    body: server,
  });
  return { data, error };
};

export const deployMCPServer = async (serverId: string) => {
  const { data, error } = await client.POST("/v1/mcp-servers/{server_id}/deploy", {
    params: { path: { server_id: serverId } },
  });
  return { data, error };
};

// MCP Server Instance API
export const listMCPServerInstances = async () => {
  const { data, error } = await client.GET("/v1/mcp-server-instances/");
  return { data, error };
};

export const createMCPServerInstance = async (instance: components["schemas"]["MCPServerInstanceCreateRequest"]) => {
  const { data, error } = await client.POST("/v1/mcp-server-instances/", { body: instance });
  return { data, error };
};

export const getMCPServerInstance = async (instanceId: string) => {
  const { data, error } = await client.GET("/v1/mcp-server-instances/{instance_id}", {
    params: { path: { instance_id: instanceId } },
  });
  return { data, error };
};

export const deleteMCPServerInstance = async (instanceId: string) => {
  const { data, error } = await client.DELETE("/v1/mcp-server-instances/{instance_id}", {
    params: { path: { instance_id: instanceId } },
  });
  return { data, error };
};

export const updateMCPServerInstance = async (instanceId: string, instance: Partial<components["schemas"]["MCPServerInstanceCreateRequest"]>) => {
  const { data, error } = await client.PUT("/v1/mcp-server-instances/{instance_id}", {
    params: { path: { instance_id: instanceId } },
    body: instance,
  });
  return { data, error };
};

export const startMCPServerInstance = async (instanceId: string) => {
  const { data, error } = await client.POST("/v1/mcp-server-instances/{instance_id}/start", {
    params: { path: { instance_id: instanceId } },
  });
  return { data, error };
};

export const stopMCPServerInstance = async (instanceId: string) => {
  const { data, error } = await client.POST("/v1/mcp-server-instances/{instance_id}/stop", {
    params: { path: { instance_id: instanceId } },
  });
  return { data, error };
};

export const getMCPServerInstanceEnvironment = async (instanceId: string) => {
  const { data, error } = await client.GET("/v1/mcp-server-instances/{instance_id}/environment", {
    params: { path: { instance_id: instanceId } },
  });
  return { data, error };
};

// Provider Spec API
export const listProviderSpecs = async (params?: { is_builtin?: boolean }) => {
  const { data, error } = await client.GET("/v1/provider-specs/", {
    params: { query: params },
  });
  return { data, error };
};

export const listProviderSpecsWithModels = async (params?: { is_builtin?: boolean }) => {
  const { data, error } = await client.GET("/v1/provider-specs/with-models", {
    params: { query: params },
  });
  return { data, error };
};

export const getProviderSpec = async (providerSpecId: string) => {
  const { data, error } = await client.GET("/v1/provider-specs/{provider_spec_id}", {
    params: { path: { provider_spec_id: providerSpecId } },
  });
  return { data, error };
};

export const getProviderSpecByKey = async (providerKey: string) => {
  const { data, error } = await client.GET("/v1/provider-specs/by-key/{provider_key}", {
    params: { path: { provider_key: providerKey } },
  });
  return { data, error };
};

// Provider Config API
export const listProviderConfigs = async (params?: {
  provider_spec_id?: string;
  is_active?: boolean;
}) => {
  const { data, error } = await client.GET("/v1/provider-configs/", {
    params: { query: params },
  });
  return { data, error };
};

export const createProviderConfig = async (config: components["schemas"]["ProviderConfigCreate"]) => {
  const { data, error } = await client.POST("/v1/provider-configs/", { body: config });
  return { data, error };
};

export async function getProviderConfig(id: string): Promise<components["schemas"]["ProviderConfigResponse"]> {
  const response = await client.GET('/v1/provider-configs/{config_id}', {
    params: { path: { config_id: id } },
  });
  
  if (!response.data) {
    throw new Error('Provider config not found');
  }
  
  return response.data;
}

export const updateProviderConfig = async (configId: string, config: components["schemas"]["ProviderConfigUpdate"]) => {
  const { data, error } = await client.PUT("/v1/provider-configs/{config_id}", {
    params: { path: { config_id: configId } },
    body: config,
  });
  return { data, error };
};

export const deleteProviderConfig = async (configId: string) => {
  const { data, error } = await client.DELETE("/v1/provider-configs/{config_id}", {
    params: { path: { config_id: configId } },
  });
  return { data, error };
};

// Combined API for unified provider management
export const getProvidersAndConfigs = async () => {
  const [specsResponse, configsResponse] = await Promise.all([
    listProviderSpecsWithModels(),
    listProviderConfigs()
  ]);

  return {
    specs: specsResponse.data || [],
    configs: configsResponse.data || [],
    error: specsResponse.error || configsResponse.error
  };
};

// Model Spec API
export const listModelSpecs = async (params?: {
  provider_spec_id?: string;
  is_active?: boolean;
}) => {
  const { data, error } = await client.GET("/v1/model-specs/", {
    params: { query: params },
  });
  return { data, error };
};

export const createModelSpec = async (spec: components["schemas"]["ModelSpecCreate"]) => {
  const { data, error } = await client.POST("/v1/model-specs/", { body: spec });
  return { data, error };
};

export const getModelSpec = async (modelSpecId: string) => {
  const { data, error } = await client.GET("/v1/model-specs/{model_spec_id}", {
    params: { path: { model_spec_id: modelSpecId } },
  });
  return { data, error };
};

export const deleteModelSpec = async (modelSpecId: string) => {
  const { data, error } = await client.DELETE("/v1/model-specs/{model_spec_id}", {
    params: { path: { model_spec_id: modelSpecId } },
  });
  return { data, error };
};

export const updateModelSpec = async (modelSpecId: string, spec: components["schemas"]["ModelSpecUpdate"]) => {
  const { data, error } = await client.PATCH("/v1/model-specs/{model_spec_id}", {
    params: { path: { model_spec_id: modelSpecId } },
    body: spec,
  });
  return { data, error };
};

export const listModelSpecsByProvider = async (providerSpecId: string, params?: { is_active?: boolean }) => {
  const { data, error } = await client.GET("/v1/model-specs/by-provider/{provider_spec_id}", {
    params: { 
      path: { provider_spec_id: providerSpecId },
      query: params
    },
  });
  return { data, error };
};

export const getModelSpecByProviderAndName = async (providerSpecId: string, modelName: string) => {
  const { data, error } = await client.GET("/v1/model-specs/by-provider/{provider_spec_id}/{model_name}", {
    params: { path: { provider_spec_id: providerSpecId, model_name: modelName } },
  });
  return { data, error };
};

export const upsertModelSpec = async (spec: components["schemas"]["ModelSpecCreate"]) => {
  const { data, error } = await client.POST("/v1/model-specs/upsert", { body: spec });
  return { data, error };
};

// Model Instance API
export const listModelInstances = async (params?: {
  provider_config_id?: string;
  model_spec_id?: string;
  is_active?: boolean;
}) => {
  const { data, error } = await client.GET("/v1/model-instances/", {
    params: { query: params },
  });
  return { data, error };
};

export const createModelInstance = async (instance: components["schemas"]["ModelInstanceCreate"]) => {
  const { data, error } = await client.POST("/v1/model-instances/", { body: instance });
  return { data, error };
};

export const getModelInstance = async (instanceId: string) => {
  const { data, error } = await client.GET("/v1/model-instances/{instance_id}", {
    params: { path: { instance_id: instanceId } },
  });
  return { data, error };
};

export const deleteModelInstance = async (instanceId: string) => {
  const { data, error } = await client.DELETE("/v1/model-instances/{instance_id}", {
    params: { path: { instance_id: instanceId } },
  });
  return { data, error };
};

// Health Check API
export const healthCheck = async () => {
  const { data, error } = await client.GET("/health");
  return { data, error };
};

export const rootEndpoint = async () => {
  const { data, error } = await client.GET("/");
  return { data, error };
};

// Type exports for commonly used schemas
export type Agent = components["schemas"]["agentarea_api__api__v1__agents__AgentResponse"];
export type MCPServer = components["schemas"]["MCPServerResponse"];
export type MCPServerInstance = components["schemas"]["MCPServerInstanceResponse"];
export type ProviderSpec = components["schemas"]["ProviderSpecResponse"];
export type ProviderSpecWithModels = components["schemas"]["ProviderSpecWithModelsResponse"];
export type ProviderConfig = components["schemas"]["ProviderConfigResponse"];
export type ModelSpec = components["schemas"]["agentarea_api__api__v1__model_specs__ModelSpecResponse"];
export type ModelInstance = components["schemas"]["ModelInstanceResponse"];
export type ChatAgent = components["schemas"]["agentarea_api__api__v1__chat__AgentResponse"];
export type ChatResponse = components["schemas"]["ChatResponse"];
export type ConversationResponse = components["schemas"]["ConversationResponse"];
export type TaskResponse = components["schemas"]["TaskResponse"];
export type AgentCard = components["schemas"]["AgentCard"];

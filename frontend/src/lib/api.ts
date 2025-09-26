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

export const getAgentTaskById = async (agentId: string, taskId: string) => {
  const { data, error } = await client.GET("/v1/agents/{agent_id}/tasks/{task_id}", {
    params: { path: { agent_id: agentId, task_id: taskId } },
  });
  return { data, error };
};

export const getAgentTaskMessages = async (agentId: string, taskId: string) => {
  // This is a placeholder - the actual endpoint might be different
  // For now, we'll use the events endpoint to build a message history
  const { data: events, error } = await getAgentTaskEvents(agentId, taskId, { page_size: 100 });
  if (error || !events) {
    return { data: [], error };
  }
  
  // Convert events to message format (simplified)
  const messages = events
    .filter((event: any) => ['LLMCallCompleted', 'ToolCallCompleted', 'WorkflowCompleted'].includes(event.event_type))
    .map((event: any) => ({
      id: event.id,
      content: event.data?.content || event.data?.result || '',
      role: event.event_type === 'LLMCallCompleted' ? 'assistant' : 'system',
      timestamp: event.timestamp
    }));
  
  return { data: messages, error: null };
};

export const cancelAgentTask = async (agentId: string, taskId: string) => {
  const { data, error } = await client.DELETE("/v1/agents/{agent_id}/tasks/{task_id}", {
    params: { path: { agent_id: agentId, task_id: taskId } },
  });
  return { data, error };
};

export const getAgentTaskStatus = async (agentId: string, taskId: string) => {
  try {
    const response = await client.GET("/v1/agents/{agent_id}/tasks/{task_id}/status", {
      params: { path: { agent_id: agentId, task_id: taskId } },
    });
    return { 
      data: response.data as {
        task_id: string;
        agent_id: string;
        execution_id: string;
        status: string;
        start_time?: string;
        end_time?: string;
        execution_time?: string;
        error?: string;
        result?: any;
        message?: string;
        artifacts?: any;
        session_id?: string;
        usage_metadata?: any;
      } | undefined, 
      error: response.error 
    };
  } catch (error) {
    return { 
      data: undefined, 
      error: error as Error 
    };
  }
};

export const pauseAgentTask = async (agentId: string, taskId: string) => {
  const { data, error } = await client.POST("/v1/agents/{agent_id}/tasks/{task_id}/pause", {
    params: { path: { agent_id: agentId, task_id: taskId } },
  });
  return { data, error };
};

export const resumeAgentTask = async (agentId: string, taskId: string) => {
  const { data, error } = await client.POST("/v1/agents/{agent_id}/tasks/{task_id}/resume", {
    params: { path: { agent_id: agentId, task_id: taskId } },
  });
  return { data, error };
};

export const getAgentTaskEvents = async (
  agentId: string, 
  taskId: string, 
  options: { 
    page?: number; 
    page_size?: number; 
    event_type?: string; 
  } = {}
) => {
  const { data, error } = await client.GET("/v1/agents/{agent_id}/tasks/{task_id}/events", {
    params: { 
      path: { agent_id: agentId, task_id: taskId },
      query: {
        page: options.page || 1,
        page_size: options.page_size || 50,
        ...(options.event_type && { event_type: options.event_type })
      }
    },
  });
  return { data, error };
};

// Get all tasks across all agents
export const getAllTasks = async () => {
  try {
    // First get all agents
    const { data: agents, error: agentsError } = await listAgents();
    if (agentsError || !agents) {
      return { data: [], error: agentsError };
    }

    // Then get tasks for each agent
    const allTasks = [];
    for (const agent of agents) {
      const { data: agentTasks, error: tasksError } = await listAgentTasks(agent.id);
      if (!tasksError && agentTasks) {
        // Add agent info to each task for display purposes
        const tasksWithAgentInfo = agentTasks.map(task => ({
          ...task,
          agent_name: agent.name,
          agent_description: agent.description,
        }));
        allTasks.push(...tasksWithAgentInfo);
      }
    }

    return { data: allTasks, error: null };
  } catch (error) {
    return { data: [], error: error as Error };
  }
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

export const getChatMessageStatus = async (taskId: string) => {
  const { data, error } = await client.GET("/v1/chat/messages/{task_id}/status", {
    params: { path: { task_id: taskId } },
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

export const checkMCPServerInstanceConfiguration = async (checkRequest: { json_spec: Record<string, any> }) => {
  // Use fetch directly since the endpoint isn't in the generated schema yet
  try {
    const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'}/v1/mcp-server-instances/check`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(checkRequest),
    });
    
    if (!response.ok) {
      const errorData = await response.json();
      return { data: null, error: errorData };
    }
    
    const data = await response.json();
    return { data, error: null };
  } catch (error) {
    return { data: null, error: { message: 'Network error' } };
  }
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

// Enhanced Provider Config API with Model Instances
export const listProviderConfigsWithModelInstances = async (params?: {
  provider_spec_id?: string;
  is_active?: boolean;
}) => {
  try {
    // Fetch provider configs with the new endpoint
    const configsResponse = await client.GET("/v1/provider-configs/with-instances", {
      params: { query: params },
    });
    
    if (configsResponse.error) {
      return { data: null, error: configsResponse.error };
    }

    const configs = configsResponse.data || [];
    
    // Fetch model instances for all configs in parallel
    const instancesPromises = configs.map(config => 
      listModelInstances({
        provider_config_id: config.id,
        is_active: true
      })
    );
    
    const instancesResponses = await Promise.all(instancesPromises);
    
    // Enhance configs with their model instances
    const enhancedConfigs = configs.map((config, index) => {
      const instancesResponse = instancesResponses[index];
      const modelInstances = instancesResponse.data || [];
      
      return {
        ...config,
        model_instances: modelInstances
      };
    });
    
    return { data: enhancedConfigs, error: null };
  } catch (error) {
    return { 
      data: null, 
      error: { 
        detail: [{ 
          loc: [], 
          msg: error instanceof Error ? error.message : 'Unknown error', 
          type: 'error' 
        }] 
      } 
    };
  }
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

export const testModelInstance = async (testRequest: {
  provider_config_id: string;
  model_spec_id: string;
  test_message?: string;
}) => {
  const { data, error } = await client.POST("/v1/model-instances/test", { body: testRequest });
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
  const { data, error } = await client.GET("/health", {});
  return { data, error };
};

export const rootEndpoint = async () => {
  const { data, error } = await client.GET("/", {});
  return { data, error };
};

// Authentication API
export const getCurrentUser = async () => {
  const { data, error } = await client.GET("/v1/auth/users/me", {});
  return { data, error };
};

export const testPublicEndpoint = async () => {
  const { data, error } = await client.GET("/health", {});
  return { data, error };
};

export const testProtectedEndpoint = async () => {
  const { data, error } = await client.GET("/v1/protected/test", {});
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

// MCP Health Monitoring
export async function getMCPHealthStatus(): Promise<{
  health_checks: Array<{
    service_name: string;
    slug: string;
    url: string;
    healthy: boolean;
    http_reachable: boolean;
    response_time_ms: number;
    error?: string;
    timestamp: string;
    container_status: string;
  }>;
  total: number;
}> {
  try {
    const response = await fetch(`http://localhost:8000/v1/mcp-server-instances/health/containers`);
    if (!response.ok) {
      // Return empty health checks if endpoint is not available
      return { health_checks: [], total: 0 };
    }
    return response.json();
  } catch (error) {
    console.warn('Failed to fetch MCP health status:', error);
    // Return empty health checks instead of throwing
    return { health_checks: [], total: 0 };
  }
}

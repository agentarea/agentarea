import type { paths } from "../api/schema";
import type { components } from "../api/schema";
import createClient from "openapi-fetch";

type Client = ReturnType<typeof createClient<paths>>;

// Factory function that creates all API functions for a given client
export function createApiClient(client: Client) {
  return {
    // Agent API
    listAgents: async () => {
      const { data, error } = await client.GET("/v1/agents/");
      return { data, error };
    },

    createAgent: async (agent: components["schemas"]["AgentCreate"]) => {
      const { data, error } = await client.POST("/v1/agents/", { body: agent });
      return { data, error };
    },

    getAgent: async (agentId: string) => {
      const { data, error } = await client.GET("/v1/agents/{agent_id}", {
        params: { path: { agent_id: agentId } },
      });
      return { data, error };
    },

    deleteAgent: async (agentId: string) => {
      const { data, error } = await client.DELETE("/v1/agents/{agent_id}", {
        params: { path: { agent_id: agentId } },
      });
      return { data, error };
    },

    updateAgent: async (agentId: string, agent: components["schemas"]["AgentUpdate"]) => {
      const { data, error } = await client.PATCH("/v1/agents/{agent_id}", {
        params: { path: { agent_id: agentId } },
        body: agent,
      });
      return { data, error };
    },

    // Agent Task API
    listAgentTasks: async (agentId: string) => {
      const { data, error } = await client.GET("/v1/agents/{agent_id}/tasks/", {
        params: { path: { agent_id: agentId } },
      });
      return { data, error };
    },

    createAgentTask: async (agentId: string, task: components["schemas"]["TaskCreate"]) => {
      const { data, error } = await client.POST("/v1/agents/{agent_id}/tasks/", {
        params: { path: { agent_id: agentId } },
        body: task,
      });
      return { data, error };
    },

    getAgentTask: async (agentId: string, taskId: string) => {
      const { data, error } = await client.GET("/v1/agents/{agent_id}/tasks/{task_id}", {
        params: { path: { agent_id: agentId, task_id: taskId } },
      });
      return { data, error };
    },

    getAgentTaskById: async (agentId: string, taskId: string) => {
      const { data, error } = await client.GET("/v1/agents/{agent_id}/tasks/{task_id}", {
        params: { path: { agent_id: agentId, task_id: taskId } },
      });
      return { data, error };
    },

    cancelAgentTask: async (agentId: string, taskId: string) => {
      const { data, error } = await client.DELETE("/v1/agents/{agent_id}/tasks/{task_id}", {
        params: { path: { agent_id: agentId, task_id: taskId } },
      });
      return { data, error };
    },

    getAgentTaskStatus: async (agentId: string, taskId: string) => {
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
    },

    pauseAgentTask: async (agentId: string, taskId: string) => {
      const { data, error } = await client.POST("/v1/agents/{agent_id}/tasks/{task_id}/pause", {
        params: { path: { agent_id: agentId, task_id: taskId } },
      });
      return { data, error };
    },

    resumeAgentTask: async (agentId: string, taskId: string) => {
      const { data, error } = await client.POST("/v1/agents/{agent_id}/tasks/{task_id}/resume", {
        params: { path: { agent_id: agentId, task_id: taskId } },
      });
      return { data, error };
    },

    getAgentTaskEvents: async (
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
    },

    // Chat API
    sendMessage: async (message: components["schemas"]["ChatMessageRequest"]) => {
      const { data, error } = await client.POST("/v1/chat/messages", { body: message });
      return { data, error };
    },

    getChatAgents: async () => {
      const { data, error } = await client.GET("/v1/chat/agents");
      return { data, error };
    },

    getChatAgent: async (agentId: string) => {
      const { data, error } = await client.GET("/v1/chat/agents/{agent_id}", {
        params: { path: { agent_id: agentId } },
      });
      return { data, error };
    },

    getChatMessageStatus: async (taskId: string) => {
      const { data, error } = await client.GET("/v1/chat/messages/{task_id}/status", {
        params: { path: { task_id: taskId } },
      });
      return { data, error };
    },

    // MCP Server API
    listMCPServers: async (params?: {
      status?: string;
      is_public?: boolean;
      tag?: string;
    }) => {
      const { data, error } = await client.GET("/v1/mcp-servers/", {
        params: { query: params },
      });
      return { data, error };
    },

    createMCPServer: async (server: components["schemas"]["MCPServerCreate"]) => {
      const { data, error } = await client.POST("/v1/mcp-servers/", { body: server });
      return { data, error };
    },

    getMCPServer: async (serverId: string) => {
      const { data, error } = await client.GET("/v1/mcp-servers/{server_id}", {
        params: { path: { server_id: serverId } },
      });
      return { data, error };
    },

    deleteMCPServer: async (serverId: string) => {
      const { data, error} = await client.DELETE("/v1/mcp-servers/{server_id}", {
        params: { path: { server_id: serverId } },
      });
      return { data, error };
    },

    updateMCPServer: async (serverId: string, server: components["schemas"]["MCPServerUpdate"]) => {
      const { data, error } = await client.PATCH("/v1/mcp-servers/{server_id}", {
        params: { path: { server_id: serverId } },
        body: server,
      });
      return { data, error };
    },

    deployMCPServer: async (serverId: string) => {
      const { data, error } = await client.POST("/v1/mcp-servers/{server_id}/deploy", {
        params: { path: { server_id: serverId } },
      });
      return { data, error };
    },

    // MCP Server Instance API
    listMCPServerInstances: async () => {
      const { data, error } = await client.GET("/v1/mcp-server-instances/");
      return { data, error };
    },

    checkMCPServerInstanceConfiguration: async (checkRequest: { json_spec: Record<string, any> }) => {
      const { data, error } = await client.POST("/v1/mcp-server-instances/check", {
        body: checkRequest,
      });
      return { data, error };
    },

    createMCPServerInstance: async (instance: components["schemas"]["MCPServerInstanceCreateRequest"]) => {
      const { data, error } = await client.POST("/v1/mcp-server-instances/", { body: instance });
      return { data, error };
    },

    getMCPServerInstance: async (instanceId: string) => {
      const { data, error } = await client.GET("/v1/mcp-server-instances/{instance_id}", {
        params: { path: { instance_id: instanceId } },
      });
      return { data, error };
    },

    deleteMCPServerInstance: async (instanceId: string) => {
      const { data, error } = await client.DELETE("/v1/mcp-server-instances/{instance_id}", {
        params: { path: { instance_id: instanceId } },
      });
      return { data, error };
    },

    updateMCPServerInstance: async (instanceId: string, instance: components["schemas"]["MCPServerInstanceUpdate"]) => {
      const { data, error } = await client.PATCH("/v1/mcp-server-instances/{instance_id}", {
        params: { path: { instance_id: instanceId } },
        body: instance,
      });
      return { data, error };
    },

    startMCPServerInstance: async (instanceId: string) => {
      const { data, error } = await client.POST("/v1/mcp-server-instances/{instance_id}/start", {
        params: { path: { instance_id: instanceId } },
      });
      return { data, error };
    },

    stopMCPServerInstance: async (instanceId: string) => {
      const { data, error } = await client.POST("/v1/mcp-server-instances/{instance_id}/stop", {
        params: { path: { instance_id: instanceId } },
      });
      return { data, error };
    },

    getMCPServerInstanceEnvironment: async (instanceId: string) => {
      const { data, error } = await client.GET("/v1/mcp-server-instances/{instance_id}/environment", {
        params: { path: { instance_id: instanceId } },
      });
      return { data, error };
    },

    // Provider Spec API
    listProviderSpecs: async (params?: { is_builtin?: boolean }) => {
      const { data, error } = await client.GET("/v1/provider-specs/", {
        params: { query: params },
      });
      return { data, error };
    },

    listProviderSpecsWithModels: async (params?: { is_builtin?: boolean }) => {
      const { data, error } = await client.GET("/v1/provider-specs/with-models", {
        params: { query: params },
      });
      return { data, error };
    },

    getProviderSpec: async (providerSpecId: string) => {
      const { data, error } = await client.GET("/v1/provider-specs/{provider_spec_id}", {
        params: { path: { provider_spec_id: providerSpecId } },
      });
      return { data, error };
    },

    getProviderSpecByKey: async (providerKey: string) => {
      const { data, error } = await client.GET("/v1/provider-specs/by-key/{provider_key}", {
        params: { path: { provider_key: providerKey } },
      });
      return { data, error };
    },

    // Provider Config API
    listProviderConfigs: async (params?: {
      provider_spec_id?: string;
      is_active?: boolean;
    }) => {
      const { data, error } = await client.GET("/v1/provider-configs/", {
        params: { query: params },
      });
      return { data, error };
    },

    createProviderConfig: async (config: components["schemas"]["ProviderConfigCreate"]) => {
      const { data, error } = await client.POST("/v1/provider-configs/", { body: config });
      return { data, error };
    },

    getProviderConfig: async (id: string): Promise<components["schemas"]["ProviderConfigResponse"]> => {
      const response = await client.GET('/v1/provider-configs/{config_id}', {
        params: { path: { config_id: id } },
      });

      if (!response.data) {
        throw new Error('Provider config not found');
      }

      return response.data;
    },

    updateProviderConfig: async (configId: string, config: components["schemas"]["ProviderConfigUpdate"]) => {
      const { data, error } = await client.PUT("/v1/provider-configs/{config_id}", {
        params: { path: { config_id: configId } },
        body: config,
      });
      return { data, error };
    },

    deleteProviderConfig: async (configId: string) => {
      const { data, error } = await client.DELETE("/v1/provider-configs/{config_id}", {
        params: { path: { config_id: configId } },
      });
      return { data, error };
    },

    // Model Spec API
    listModelSpecs: async (params?: {
      provider_spec_id?: string;
      is_active?: boolean;
    }) => {
      const { data, error } = await client.GET("/v1/model-specs/", {
        params: { query: params },
      });
      return { data, error };
    },

    createModelSpec: async (spec: components["schemas"]["ModelSpecCreate"]) => {
      const { data, error } = await client.POST("/v1/model-specs/", { body: spec });
      return { data, error };
    },

    getModelSpec: async (modelSpecId: string) => {
      const { data, error } = await client.GET("/v1/model-specs/{model_spec_id}", {
        params: { path: { model_spec_id: modelSpecId } },
      });
      return { data, error };
    },

    deleteModelSpec: async (modelSpecId: string) => {
      const { data, error } = await client.DELETE("/v1/model-specs/{model_spec_id}", {
        params: { path: { model_spec_id: modelSpecId } },
      });
      return { data, error };
    },

    updateModelSpec: async (modelSpecId: string, spec: components["schemas"]["ModelSpecUpdate"]) => {
      const { data, error } = await client.PATCH("/v1/model-specs/{model_spec_id}", {
        params: { path: { model_spec_id: modelSpecId } },
        body: spec,
      });
      return { data, error };
    },

    listModelSpecsByProvider: async (providerSpecId: string, params?: { is_active?: boolean }) => {
      const { data, error } = await client.GET("/v1/model-specs/by-provider/{provider_spec_id}", {
        params: {
          path: { provider_spec_id: providerSpecId },
          query: params
        },
      });
      return { data, error };
    },

    getModelSpecByProviderAndName: async (providerSpecId: string, modelName: string) => {
      const { data, error } = await client.GET("/v1/model-specs/by-provider/{provider_spec_id}/{model_name}", {
        params: { path: { provider_spec_id: providerSpecId, model_name: modelName } },
      });
      return { data, error };
    },

    upsertModelSpec: async (spec: components["schemas"]["ModelSpecCreate"]) => {
      const { data, error } = await client.POST("/v1/model-specs/upsert", { body: spec });
      return { data, error };
    },

    // Model Instance API
    listModelInstances: async (params?: {
      provider_config_id?: string;
      model_spec_id?: string;
      is_active?: boolean;
    }) => {
      const { data, error } = await client.GET("/v1/model-instances/", {
        params: { query: params },
      });
      return { data, error };
    },

    createModelInstance: async (instance: components["schemas"]["ModelInstanceCreate"]) => {
      const { data, error } = await client.POST("/v1/model-instances/", { body: instance });
      return { data, error };
    },

    testModelInstance: async (testRequest: {
      provider_config_id: string;
      model_spec_id: string;
      test_message?: string;
    }) => {
      // TODO: Implement model instance testing endpoint
      return { data: null, error: { detail: [{ msg: "Model instance testing not yet implemented", type: "error" }] } };
    },

    getModelInstance: async (instanceId: string) => {
      const { data, error } = await client.GET("/v1/model-instances/{instance_id}", {
        params: { path: { instance_id: instanceId } },
      });
      return { data, error };
    },

    deleteModelInstance: async (instanceId: string) => {
      const { data, error } = await client.DELETE("/v1/model-instances/{instance_id}", {
        params: { path: { instance_id: instanceId } },
      });
      return { data, error };
    },

    // Health Check API
    healthCheck: async () => {
      // TODO: Implement health check endpoint
      return { data: { status: "healthy" }, error: null };
    },

    // Authentication API
    getCurrentUser: async () => {
      const { data, error } = await client.GET("/v1/auth/users/me", {});
      return { data, error };
    },

    testProtectedEndpoint: async () => {
      const { data, error } = await client.GET("/v1/protected/test", {});
      return { data, error };
    },

    // Builtin Tools API (outside generated schema)
    listBuiltinTools: async () => {
      const { data, error } = await client.GET("/v1/agents/tools/builtin" as any, {});
      return { data, error };
    },

    // MCP Health Monitoring
    getMCPHealthStatus: async (): Promise<{
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
    }> => {
      try {
        const { data, error } = await client.GET('/v1/mcp-server-instances/health/containers');
        if (error || !data) {
          return { health_checks: [], total: 0 };
        }
        return data as any;
      } catch (error) {
        console.warn('Failed to fetch MCP health status:', error);
        return { health_checks: [], total: 0 };
      }
    },
  };
}

// Type for the API client
export type ApiClient = ReturnType<typeof createApiClient>;

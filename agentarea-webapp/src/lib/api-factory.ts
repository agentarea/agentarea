import createClient from "openapi-fetch";
import type { components, paths } from "../api/schema";

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

    updateAgent: async (
      agentId: string,
      agent: components["schemas"]["AgentUpdate"]
    ) => {
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

    createAgentTask: async (
      agentId: string,
      task: components["schemas"]["TaskCreate"]
    ) => {
      const { data, error } = await client.POST(
        "/v1/agents/{agent_id}/tasks/",
        {
          params: { path: { agent_id: agentId } },
          body: task,
        }
      );
      return { data, error };
    },

    getAgentTask: async (agentId: string, taskId: string) => {
      const { data, error } = await client.GET(
        "/v1/agents/{agent_id}/tasks/{task_id}",
        {
          params: { path: { agent_id: agentId, task_id: taskId } },
        }
      );
      return { data, error };
    },

    getAgentTaskById: async (agentId: string, taskId: string) => {
      const { data, error } = await client.GET(
        "/v1/agents/{agent_id}/tasks/{task_id}",
        {
          params: { path: { agent_id: agentId, task_id: taskId } },
        }
      );
      return { data, error };
    },

    cancelAgentTask: async (agentId: string, taskId: string) => {
      const { data, error } = await client.DELETE(
        "/v1/agents/{agent_id}/tasks/{task_id}",
        {
          params: { path: { agent_id: agentId, task_id: taskId } },
        }
      );
      return { data, error };
    },

    getAgentTaskStatus: async (agentId: string, taskId: string) => {
      try {
        const response = await client.GET(
          "/v1/agents/{agent_id}/tasks/{task_id}/status",
          {
            params: { path: { agent_id: agentId, task_id: taskId } },
          }
        );
        return {
          data: response.data as
            | {
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
              }
            | undefined,
          error: response.error,
        };
      } catch (error) {
        return {
          data: undefined,
          error: error as Error,
        };
      }
    },

    pauseAgentTask: async (agentId: string, taskId: string) => {
      const { data, error } = await client.POST(
        "/v1/agents/{agent_id}/tasks/{task_id}/pause",
        {
          params: { path: { agent_id: agentId, task_id: taskId } },
        }
      );
      return { data, error };
    },

    resumeAgentTask: async (agentId: string, taskId: string) => {
      const { data, error } = await client.POST(
        "/v1/agents/{agent_id}/tasks/{task_id}/resume",
        {
          params: { path: { agent_id: agentId, task_id: taskId } },
        }
      );
      return { data, error };
    },

    sendTaskCommand: async (
      agentId: string,
      taskId: string,
      payload: { command: string; [key: string]: any }
    ) => {
      const { data, error } = await client.POST(
        `/v1/agents/${agentId}/tasks/${taskId}/command` as any,
        { body: payload } as any
      );
      return { data, error };
    },

    resolveEscalation: async (
      agentId: string,
      taskId: string,
      escalationId: string,
      approved: boolean,
      comment: string = ""
    ) => {
      const { data, error } = await client.POST(
        "/v1/agents/{agent_id}/tasks/{task_id}/resolve-escalation" as any,
        {
          params: { path: { agent_id: agentId, task_id: taskId } } as any,
          body: { escalation_id: escalationId, approved, comment } as any,
        }
      );
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
      const { data, error } = await client.GET(
        "/v1/agents/{agent_id}/tasks/{task_id}/events",
        {
          params: {
            path: { agent_id: agentId, task_id: taskId },
            query: {
              page: options.page || 1,
              page_size: options.page_size || 50,
              ...(options.event_type && { event_type: options.event_type }),
            },
          },
        }
      );
      return { data, error };
    },

    // Chat API
    sendMessage: async (message: {
      agent_id: string;
      message: string;
      conversation_id?: string;
    }) => {
      const { data, error } = await client.POST("/v1/chat/messages" as any, {
        body: message as any,
      });
      return { data, error };
    },

    getChatAgents: async () => {
      const { data, error } = await client.GET("/v1/chat/agents" as any, {});
      return { data, error };
    },

    getChatAgent: async (agentId: string) => {
      const { data, error } = await client.GET(
        "/v1/chat/agents/{agent_id}" as any,
        {
          params: { path: { agent_id: agentId } },
        }
      );
      return { data, error };
    },

    getChatMessageStatus: async (taskId: string) => {
      const { data, error } = await client.GET(
        "/v1/chat/messages/{task_id}/status" as any,
        {
          params: { path: { task_id: taskId } },
        }
      );
      return { data, error };
    },

    // MCP Server API
    listMCPServers: async (params?: {
      status?: string;
      is_public?: boolean;
      tag?: string;
      page?: number;
      page_size?: number;
      search?: string;
    }) => {
      const { data, error } = await client.GET("/v1/mcp-servers/", {
        params: { query: params },
      });
      return { data, error };
    },

    createMCPServer: async (
      server: components["schemas"]["MCPServerCreate"]
    ) => {
      const { data, error } = await client.POST("/v1/mcp-servers/", {
        body: server,
      });
      return { data, error };
    },

    getMCPServer: async (serverId: string) => {
      const { data, error } = await client.GET("/v1/mcp-servers/{server_id}", {
        params: { path: { server_id: serverId } },
      });
      return { data, error };
    },

    deleteMCPServer: async (serverId: string) => {
      const { data, error } = await client.DELETE(
        "/v1/mcp-servers/{server_id}",
        {
          params: { path: { server_id: serverId } },
        }
      );
      return { data, error };
    },

    updateMCPServer: async (
      serverId: string,
      server: components["schemas"]["MCPServerUpdate"]
    ) => {
      const { data, error } = await client.PATCH(
        "/v1/mcp-servers/{server_id}",
        {
          params: { path: { server_id: serverId } },
          body: server,
        }
      );
      return { data, error };
    },

    deployMCPServer: async (serverId: string) => {
      const { data, error } = await client.POST(
        "/v1/mcp-servers/{server_id}/deploy",
        {
          params: { path: { server_id: serverId } },
        }
      );
      return { data, error };
    },

    // MCP Server Instance API
    listMCPServerInstances: async () => {
      const { data, error } = await client.GET("/v1/mcp-server-instances/");
      return { data, error };
    },

    checkMCPServerInstanceConfiguration: async (checkRequest: {
      json_spec: Record<string, any>;
    }) => {
      const { data, error } = await client.POST(
        "/v1/mcp-server-instances/check",
        {
          body: checkRequest,
        }
      );
      return { data, error };
    },

    createMCPServerInstance: async (
      instance: components["schemas"]["MCPServerInstanceCreateRequest"]
    ) => {
      const { data, error } = await client.POST("/v1/mcp-server-instances/", {
        body: instance,
      });
      return { data, error };
    },

    getMCPServerInstance: async (instanceId: string) => {
      const { data, error } = await client.GET(
        "/v1/mcp-server-instances/{instance_id}",
        {
          params: { path: { instance_id: instanceId } },
        }
      );
      return { data, error };
    },

    deleteMCPServerInstance: async (instanceId: string) => {
      const { data, error } = await client.DELETE(
        "/v1/mcp-server-instances/{instance_id}",
        {
          params: { path: { instance_id: instanceId } },
        }
      );
      return { data, error };
    },

    updateMCPServerInstance: async (
      instanceId: string,
      instance: components["schemas"]["MCPServerInstanceUpdate"]
    ) => {
      const { data, error } = await client.PATCH(
        "/v1/mcp-server-instances/{instance_id}",
        {
          params: { path: { instance_id: instanceId } },
          body: instance,
        }
      );
      return { data, error };
    },

    verifyMCPServerInstance: async (instanceId: string) => {
      const { data, error } = await client.POST(
        `/v1/mcp-server-instances/${instanceId}/verify` as any,
        {}
      );
      return { data, error };
    },

    validateMCPServerInstanceSpec: async (spec: Record<string, unknown>) => {
      const { data, error } = await client.POST(
        "/v1/mcp-server-instances/validate" as any,
        { body: spec }
      );
      return { data, error };
    },

    getMCPServerInstanceEnvironment: async (instanceId: string) => {
      const { data, error } = await client.GET(
        "/v1/mcp-server-instances/{instance_id}/environment",
        {
          params: { path: { instance_id: instanceId } },
        }
      );
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
      const { data, error } = await client.GET(
        "/v1/provider-specs/with-models",
        {
          params: { query: params },
        }
      );
      return { data, error };
    },

    getProviderSpec: async (providerSpecId: string) => {
      const { data, error } = await client.GET(
        "/v1/provider-specs/{provider_spec_id}",
        {
          params: { path: { provider_spec_id: providerSpecId } },
        }
      );
      return { data, error };
    },

    getProviderSpecByKey: async (providerKey: string) => {
      const { data, error } = await client.GET(
        "/v1/provider-specs/by-key/{provider_key}",
        {
          params: { path: { provider_key: providerKey } },
        }
      );
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

    createProviderConfig: async (
      config: components["schemas"]["ProviderConfigCreate"]
    ) => {
      const { data, error } = await client.POST("/v1/provider-configs/", {
        body: config,
      });
      return { data, error };
    },

    getProviderConfig: async (
      id: string
    ): Promise<components["schemas"]["ProviderConfigResponse"]> => {
      const response = await client.GET("/v1/provider-configs/{config_id}", {
        params: { path: { config_id: id } },
      });

      if (!response.data) {
        throw new Error("Provider config not found");
      }

      return response.data;
    },

    updateProviderConfig: async (
      configId: string,
      config: components["schemas"]["ProviderConfigUpdate"]
    ) => {
      const { data, error } = await client.PUT(
        "/v1/provider-configs/{config_id}",
        {
          params: { path: { config_id: configId } },
          body: config,
        }
      );
      return { data, error };
    },

    deleteProviderConfig: async (configId: string) => {
      const { data, error } = await client.DELETE(
        "/v1/provider-configs/{config_id}",
        {
          params: { path: { config_id: configId } },
        }
      );
      return { data, error };
    },

    discoverModels: async (configId: string) => {
      const { data, error } = await client.POST(
        "/v1/provider-configs/{config_id}/discover" as any,
        {
          params: { path: { config_id: configId } },
        }
      );
      return { data, error };
    },

    discoverModelsPreview: async (body: {
      provider_key: string;
      api_key: string;
      endpoint_url?: string | null;
    }) => {
      const { data, error } = await client.POST(
        "/v1/provider-configs/discover-preview" as any,
        { body }
      );
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
      const { data, error } = await client.POST("/v1/model-specs/", {
        body: spec,
      });
      return { data, error };
    },

    getModelSpec: async (modelSpecId: string) => {
      const { data, error } = await client.GET(
        "/v1/model-specs/{model_spec_id}",
        {
          params: { path: { model_spec_id: modelSpecId } },
        }
      );
      return { data, error };
    },

    deleteModelSpec: async (modelSpecId: string) => {
      const { data, error } = await client.DELETE(
        "/v1/model-specs/{model_spec_id}",
        {
          params: { path: { model_spec_id: modelSpecId } },
        }
      );
      return { data, error };
    },

    updateModelSpec: async (
      modelSpecId: string,
      spec: components["schemas"]["ModelSpecUpdate"]
    ) => {
      const { data, error } = await client.PATCH(
        "/v1/model-specs/{model_spec_id}",
        {
          params: { path: { model_spec_id: modelSpecId } },
          body: spec,
        }
      );
      return { data, error };
    },

    listModelSpecsByProvider: async (
      providerSpecId: string,
      params?: { is_active?: boolean }
    ) => {
      const { data, error } = await client.GET(
        "/v1/model-specs/by-provider/{provider_spec_id}",
        {
          params: {
            path: { provider_spec_id: providerSpecId },
            query: params,
          },
        }
      );
      return { data, error };
    },

    getModelSpecByProviderAndName: async (
      providerSpecId: string,
      modelName: string
    ) => {
      const { data, error } = await client.GET(
        "/v1/model-specs/by-provider/{provider_spec_id}/{model_name}",
        {
          params: {
            path: { provider_spec_id: providerSpecId, model_name: modelName },
          },
        }
      );
      return { data, error };
    },

    upsertModelSpec: async (spec: components["schemas"]["ModelSpecCreate"]) => {
      const { data, error } = await client.POST("/v1/model-specs/upsert", {
        body: spec,
      });
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

    createModelInstance: async (
      instance: components["schemas"]["ModelInstanceCreate"]
    ) => {
      const { data, error } = await client.POST("/v1/model-instances/", {
        body: instance,
      });
      return { data, error };
    },

    bulkCreateModelInstances: async (
      body: components["schemas"]["ModelInstanceBulkCreateRequest"]
    ) => {
      const { data, error } = await client.POST(
        "/v1/model-instances/bulk" as any,
        { body: body as any }
      );
      return { data, error };
    },

    testModelInstance: async (testRequest: {
      provider_config_id: string;
      model_spec_id: string;
      test_message?: string;
    }) => {
      const { data, error } = await client.POST(
        "/v1/model-instances/test" as any,
        {
          body: testRequest,
        }
      );
      return { data, error };
    },

    getModelInstance: async (instanceId: string) => {
      const { data, error } = await client.GET(
        "/v1/model-instances/{instance_id}",
        {
          params: { path: { instance_id: instanceId } },
        }
      );
      return { data, error };
    },

    deleteModelInstance: async (instanceId: string) => {
      const { data, error } = await client.DELETE(
        "/v1/model-instances/{instance_id}",
        {
          params: { path: { instance_id: instanceId } },
        }
      );
      return { data, error };
    },

    // Health Check API
    healthCheck: async () => {
      // TODO: Implement health check endpoint
      return { data: { status: "healthy" }, error: null };
    },

    // Authentication API
    getCurrentUser: async () => {
      const { data, error } = await client.GET("/v1/auth/users/me" as any, {});
      return { data, error };
    },

    testProtectedEndpoint: async () => {
      const { data, error } = await client.GET("/v1/protected/test" as any, {});
      return { data, error };
    },

    // Unified Tools API (outside generated schema)
    listAllTools: async (options?: {
      include?: "code" | "mcp" | "code,mcp";
      mcpInstanceId?: string;
    }) => {
      const params = new URLSearchParams();
      if (options?.include) {
        params.append("include", options.include);
      }
      if (options?.mcpInstanceId) {
        params.append("mcp_instance_id", options.mcpInstanceId);
      }

      const queryString = params.toString();
      const path = queryString
        ? `/v1/agents/tools?${queryString}`
        : `/v1/agents/tools`;

      const { data, error } = await client.GET(path as any, {});
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
        const { data, error } = await client.GET(
          "/v1/mcp-server-instances/health/containers"
        );
        if (error || !data) {
          return { health_checks: [], total: 0 };
        }
        return data as any;
      } catch (error) {
        console.warn("Failed to fetch MCP health status:", error);
        return { health_checks: [], total: 0 };
      }
    },

    getMCPInstanceHealth: async (
      instanceName: string
    ): Promise<{
      health_check: {
        service_name: string;
        slug: string;
        url: string;
        healthy: boolean;
        http_reachable: boolean;
        response_time_ms: number;
        error?: string;
        timestamp: string;
        container_status: string;
        details?: {
          proxy_url?: string;
          direct_http_endpoint?: string;
          container_port?: number;
          container_image?: string;
        };
      } | null;
    }> => {
      try {
        const { data, error } = await client.GET(
          "/v1/mcp-server-instances/health/containers"
        );
        if (error || !data) {
          return { health_check: null };
        }
        const healthData = data as any;
        const healthCheck = healthData.health_checks?.find(
          (check: any) => check.service_name === instanceName
        );
        return { health_check: healthCheck || null };
      } catch (error) {
        console.warn("Failed to fetch MCP instance health:", error);
        return { health_check: null };
      }
    },

    // Skills API
    listSkills: async () => {
      const { data, error } = await client.GET("/v1/skills" as any, {});
      return { data, error };
    },

    getSkill: async (skillId: string) => {
      const { data, error } = await client.GET(
        `/v1/skills/${skillId}` as any,
        {}
      );
      return { data, error };
    },

    getSkillContent: async (skillId: string) => {
      const { data, error } = await client.GET(
        `/v1/skills/${skillId}/content` as any,
        {}
      );
      return { data, error };
    },

    getSkillFiles: async (skillId: string, includeUrls: boolean = false) => {
      const { data, error } = await client.GET(
        `/v1/skills/${skillId}/files${includeUrls ? "?include_urls=true" : ""}` as any,
        {}
      );
      return { data, error };
    },

    getSkillFile: async (skillId: string, filePath: string) => {
      const { data, error } = await client.GET(
        `/v1/skills/${skillId}/files/${filePath}` as any,
        {}
      );
      return { data, error };
    },

    createSkill: async (skill: {
      content?: string | null;
      github_url?: string | null;
      name?: string | null;
      description?: string | null;
    }) => {
      const { data, error } = await client.POST("/v1/skills" as any, {
        body: skill,
      });
      return { data, error };
    },

    uploadSkill: async (formData: FormData) => {
      // For file upload, we need to use fetch directly
      const response = await fetch("/api/proxy/v1/skills/upload", {
        method: "POST",
        body: formData,
        credentials: "include",
      });
      if (!response.ok) {
        const error = await response
          .json()
          .catch(() => ({ detail: "Upload failed" }));
        return { data: null, error };
      }
      const data = await response.json();
      return { data, error: null };
    },

    updateSkill: async (
      skillId: string,
      skill: {
        name?: string | null;
        description?: string | null;
        content?: string | null;
      }
    ) => {
      const { data, error } = await client.PUT(`/v1/skills/${skillId}` as any, {
        body: skill,
      });
      return { data, error };
    },

    deleteSkill: async (skillId: string) => {
      const { data, error } = await client.DELETE(
        `/v1/skills/${skillId}` as any,
        {}
      );
      return { data, error };
    },

    // MCP Auth Config API
    listMCPAuthConfigs: async () => {
      const { data, error } = await client.GET(
        "/v1/mcp-auth-configs/" as any,
        {}
      );
      return { data, error };
    },

    createMCPAuthConfig: async (body: {
      name: string;
      description?: string;
      auth_type: string;
      config?: Record<string, any>;
      credentials?: Record<string, any>;
    }) => {
      const { data, error } = await client.POST(
        "/v1/mcp-auth-configs/" as any,
        { body }
      );
      return { data, error };
    },

    // API Keys API
    listAPIKeys: async () => {
      const { data, error } = await client.GET("/v1/api-keys/" as any, {});
      return { data, error };
    },

    createAPIKey: async (body: { name: string; expires_in_days?: number }) => {
      const { data, error } = await client.POST("/v1/api-keys/" as any, {
        body,
      });
      return { data, error };
    },

    getAPIKey: async (tokenId: string) => {
      const { data, error } = await client.GET(
        `/v1/api-keys/${tokenId}` as any,
        {}
      );
      return { data, error };
    },

    revokeAPIKey: async (tokenId: string) => {
      const { data, error } = await client.DELETE(
        `/v1/api-keys/${tokenId}` as any,
        {}
      );
      return { data, error };
    },

    // Triggers API
    listTriggerCatalog: async () => {
      const { data, error } = await client.GET("/v1/triggers/catalog" as any, {});
      return { data, error };
    },

    listTriggers: async (params?: {
      agent_id?: string;
      trigger_type?: string;
      active_only?: boolean;
    }) => {
      const { data, error } = await client.GET("/v1/triggers/" as any, {
        params: { query: params },
      });
      return { data, error };
    },

    createTrigger: async (body: {
      name: string;
      trigger_type: string;
      agent_id: string;
      config: Record<string, any>;
      task_parameters?: Record<string, any>;
      failure_threshold?: number;
    }) => {
      // Flatten config into the body — backend expects flat fields
      const { config, ...rest } = body;
      const flat = { ...rest, ...config };
      const { data, error } = await client.POST("/v1/triggers/" as any, {
        body: flat,
      });
      return { data, error };
    },

    getTrigger: async (triggerId: string) => {
      const { data, error } = await client.GET(
        `/v1/triggers/${triggerId}` as any,
        {}
      );
      return { data, error };
    },

    updateTrigger: async (
      triggerId: string,
      body: {
        name?: string;
        cron_expression?: string;
        timezone?: string;
        task_parameters?: Record<string, any>;
        failure_threshold?: number;
        description?: string;
        is_active?: boolean;
        conditions?: Record<string, any>;
      }
    ) => {
      const { data, error } = await client.PUT(
        `/v1/triggers/${triggerId}` as any,
        { body }
      );
      return { data, error };
    },

    deleteTrigger: async (triggerId: string) => {
      const { data, error } = await client.DELETE(
        `/v1/triggers/${triggerId}` as any,
        {}
      );
      return { data, error };
    },

    enableTrigger: async (triggerId: string) => {
      const { data, error } = await client.POST(
        `/v1/triggers/${triggerId}/enable` as any,
        {}
      );
      return { data, error };
    },

    disableTrigger: async (triggerId: string) => {
      const { data, error } = await client.POST(
        `/v1/triggers/${triggerId}/disable` as any,
        {}
      );
      return { data, error };
    },

    getTriggerStatus: async (triggerId: string) => {
      const { data, error } = await client.GET(
        `/v1/triggers/${triggerId}/status` as any,
        {}
      );
      return { data, error };
    },

    getTriggerExecutions: async (
      triggerId: string,
      params?: {
        page?: number;
        page_size?: number;
      }
    ) => {
      const { data, error } = await client.GET(
        `/v1/triggers/${triggerId}/executions` as any,
        {
          params: { query: params },
        }
      );
      return { data, error };
    },

    getTriggerMetrics: async (triggerId: string) => {
      const { data, error } = await client.GET(
        `/v1/triggers/${triggerId}/metrics` as any,
        {}
      );
      return { data, error };
    },

    getTriggerTimeline: async (triggerId: string) => {
      const { data, error } = await client.GET(
        `/v1/triggers/${triggerId}/timeline` as any,
        {}
      );
      return { data, error };
    },

    getTriggerCorrelations: async (triggerId: string) => {
      const { data, error } = await client.GET(
        `/v1/triggers/${triggerId}/correlations` as any,
        {}
      );
      return { data, error };
    },

    // Workspace Import/Export API
    exportWorkspace: async () => {
      const { data, error } = await client.GET(
        "/v1/workspace/export" as any,
        {}
      );
      return { data, error };
    },

    importWorkspace: async (body: {
      config: string;
      skip_missing_dependencies?: boolean;
      override_existing?: boolean;
    }) => {
      const { data, error } = await client.POST("/v1/workspace/import" as any, {
        body,
      });
      return { data, error };
    },

    // MCP Instance Tools Discovery
    discoverMCPInstanceTools: async (instanceId: string) => {
      const { data, error } = await client.POST(
        `/v1/mcp-server-instances/${instanceId}/discover-tools` as any,
        {}
      );
      return { data, error };
    },

    testMCPInstanceAuth: async (instanceId: string) => {
      const { data, error } = await client.POST(
        `/v1/mcp-server-instances/${instanceId}/test-auth` as any,
        {}
      );
      return { data, error };
    },

    // Skill Bundle API
    listSkillMembers: async (skillId: string) => {
      const { data, error } = await client.GET(
        `/v1/skills/${skillId}/members` as any,
        {}
      );
      return { data, error };
    },

    addSkillMember: async (skillId: string, childSkillId: string) => {
      const { data, error } = await client.POST(
        `/v1/skills/${skillId}/members` as any,
        {
          body: { child_skill_id: childSkillId },
        }
      );
      return { data, error };
    },

    removeSkillMember: async (skillId: string, childSkillId: string) => {
      const { data, error } = await client.DELETE(
        `/v1/skills/${skillId}/members/${childSkillId}` as any,
        {}
      );
      return { data, error };
    },

    flattenSkill: async (skillId: string) => {
      const { data, error } = await client.GET(
        `/v1/skills/${skillId}/flatten` as any,
        {}
      );
      return { data, error };
    },

    // Network Topology API
    getNetworkTopology: async () => {
      const { data, error } = await client.GET(
        "/v1/network/topology" as any,
        {}
      );
      return { data, error };
    },

    // OpenAPI Connections API
    listOpenAPIConnections: async (params?: {
      status?: string;
      search?: string;
      limit?: number;
      offset?: number;
    }) => {
      const { data, error } = await client.GET(
        "/v1/openapi-connections/" as any,
        {
          params: { query: params },
        }
      );
      return { data, error };
    },

    createOpenAPIConnection: async (
      body: components["schemas"]["OpenAPIConnectionCreate"]
    ) => {
      const { data, error } = await client.POST(
        "/v1/openapi-connections/" as any,
        { body }
      );
      return { data, error };
    },

    deleteOpenAPIConnection: async (connectionId: string) => {
      const { data, error } = await client.DELETE(
        `/v1/openapi-connections/${connectionId}` as any,
        {}
      );
      return { data, error };
    },

    getOpenAPIConnection: async (connectionId: string) => {
      const { data, error } = await client.GET(
        `/v1/openapi-connections/${connectionId}` as any,
        {}
      );
      return { data, error };
    },

    updateOpenAPIConnection: async (
      connectionId: string,
      body: components["schemas"]["OpenAPIConnectionUpdate"]
    ) => {
      const { data, error } = await client.PATCH(
        `/v1/openapi-connections/${connectionId}` as any,
        { body: body as any }
      );
      return { data, error };
    },

    discoverOpenAPITools: async (connectionId: string) => {
      const { data, error } = await client.POST(
        "/v1/openapi-connections/{connection_id}/discover-tools",
        { params: { path: { connection_id: connectionId } } }
      );
      return { data, error };
    },

    previewOpenAPISpec: async (body: {
      spec_url?: string;
      spec_content?: Record<string, unknown>;
    }) => {
      const { data, error } = await client.POST(
        "/v1/openapi-connections/preview-spec",
        { body: body as any }
      );
      return { data, error };
    },

    // Compound MCP API
    listCompoundMCPs: async () => {
      const { data, error } = await client.GET("/v1/compound-mcps/" as any, {});
      return { data, error };
    },

    getCompoundMCP: async (compoundId: string) => {
      const { data, error } = await client.GET("/v1/compound-mcps/{compound_id}" as any, {
        params: { path: { compound_id: compoundId } },
      });
      return { data, error };
    },

    createCompoundMCP: async (body: any) => {
      const { data, error } = await client.POST("/v1/compound-mcps/" as any, { body });
      return { data, error };
    },

    updateCompoundMCP: async (compoundId: string, body: any) => {
      const { data, error } = await client.PUT("/v1/compound-mcps/{compound_id}" as any, {
        params: { path: { compound_id: compoundId } },
        body,
      });
      return { data, error };
    },

    deleteCompoundMCP: async (compoundId: string) => {
      const { data, error } = await client.DELETE("/v1/compound-mcps/{compound_id}" as any, {
        params: { path: { compound_id: compoundId } },
      });
      return { data, error };
    },

    listCompoundMCPMembers: async (compoundId: string) => {
      const { data, error } = await client.GET("/v1/compound-mcps/{compound_id}/members" as any, {
        params: { path: { compound_id: compoundId } },
      });
      return { data, error };
    },

    addCompoundMCPMember: async (compoundId: string, body: any) => {
      const { data, error } = await client.POST("/v1/compound-mcps/{compound_id}/members" as any, {
        params: { path: { compound_id: compoundId } },
        body,
      });
      return { data, error };
    },

    removeCompoundMCPMember: async (compoundId: string, instanceId: string) => {
      const { data, error } = await client.DELETE("/v1/compound-mcps/{compound_id}/members/{instance_id}" as any, {
        params: { path: { compound_id: compoundId, instance_id: instanceId } },
      });
      return { data, error };
    },

    // Project API
    listProjects: async () => {
      const { data, error } = await client.GET("/v1/projects/");
      return { data, error };
    },

    getProject: async (projectId: string) => {
      const { data, error } = await client.GET("/v1/projects/{project_id}", {
        params: { path: { project_id: projectId } },
      });
      return { data, error };
    },

    createProject: async (project: components["schemas"]["ProjectCreate"]) => {
      const { data, error } = await client.POST("/v1/projects/", {
        body: project,
      });
      return { data, error };
    },

    updateProject: async (
      projectId: string,
      project: components["schemas"]["ProjectUpdate"]
    ) => {
      const { data, error } = await client.PATCH("/v1/projects/{project_id}", {
        params: { path: { project_id: projectId } },
        body: project,
      });
      return { data, error };
    },

    deleteProject: async (projectId: string) => {
      const { data, error } = await client.DELETE("/v1/projects/{project_id}", {
        params: { path: { project_id: projectId } },
      });
      return { data, error };
    },

    // Project Association API
    addSkillToProject: async (projectId: string, skillId: string) => {
      const { data, error } = await client.POST(
        "/v1/projects/{project_id}/skills" as any,
        {
          params: { path: { project_id: projectId } },
          body: { skill_id: skillId },
        }
      );
      return { data, error };
    },

    removeSkillFromProject: async (projectId: string, skillId: string) => {
      const { data, error } = await client.DELETE(
        "/v1/projects/{project_id}/skills/{skill_id}" as any,
        {
          params: { path: { project_id: projectId, skill_id: skillId } },
        }
      );
      return { data, error };
    },

    addAgentToProject: async (projectId: string, agentId: string) => {
      const { data, error } = await client.POST(
        "/v1/projects/{project_id}/agents" as any,
        {
          params: { path: { project_id: projectId } },
          body: { agent_id: agentId },
        }
      );
      return { data, error };
    },

    removeAgentFromProject: async (projectId: string, agentId: string) => {
      const { data, error } = await client.DELETE(
        "/v1/projects/{project_id}/agents/{agent_id}" as any,
        {
          params: { path: { project_id: projectId, agent_id: agentId } },
        }
      );
      return { data, error };
    },

    addMcpInstanceToProject: async (
      projectId: string,
      mcpInstanceId: string
    ) => {
      const { data, error } = await client.POST(
        "/v1/projects/{project_id}/mcp-instances" as any,
        {
          params: { path: { project_id: projectId } },
          body: { mcp_instance_id: mcpInstanceId },
        }
      );
      return { data, error };
    },

    removeMcpInstanceFromProject: async (
      projectId: string,
      mcpInstanceId: string
    ) => {
      const { data, error } = await client.DELETE(
        "/v1/projects/{project_id}/mcp-instances/{mcp_instance_id}" as any,
        {
          params: {
            path: { project_id: projectId, mcp_instance_id: mcpInstanceId },
          },
        }
      );
      return { data, error };
    },

    // Project Files API
    listProjectFiles: async (projectId: string) => {
      const { data, error } = await client.GET(
        "/v1/projects/{project_id}/files" as any,
        {
          params: { path: { project_id: projectId } },
        }
      );
      return { data, error };
    },

    uploadProjectFile: async (projectId: string, formData: FormData) => {
      const response = await fetch(
        `/api/proxy/v1/projects/${projectId}/files`,
        {
          method: "POST",
          body: formData,
          credentials: "include",
        }
      );
      if (!response.ok) {
        const error = await response
          .json()
          .catch(() => ({ detail: "Upload failed" }));
        return { data: null, error };
      }
      const data = await response.json();
      return { data, error: null };
    },

    downloadProjectFile: async (projectId: string, filePath: string) => {
      const { data, error } = await client.GET(
        "/v1/projects/{project_id}/files/{file_path}" as any,
        {
          params: { path: { project_id: projectId, file_path: filePath } },
        }
      );
      return { data, error };
    },

    deleteProjectFile: async (projectId: string, filePath: string) => {
      const { data, error } = await client.DELETE(
        "/v1/projects/{project_id}/files/{file_path}" as any,
        {
          params: { path: { project_id: projectId, file_path: filePath } },
        }
      );
      return { data, error };
    },

    // Workspace Files API (read-only)
    listWorkspaceFiles: async () => {
      const { data, error } = await client.GET("/v1/files" as any, {} as any);
      return { data, error };
    },

    downloadWorkspaceFile: async (filePath: string) => {
      const { data, error } = await client.GET(
        "/v1/files/{file_path}" as any,
        {
          params: { path: { file_path: filePath } },
        }
      );
      return { data, error };
    },

    // Wallet API
    getAgentWallet: async (agentId: string) => {
      const { data, error } = await client.GET("/v1/agents/{agent_id}/wallet" as any, {
        params: { path: { agent_id: agentId } },
      } as any);
      return { data, error };
    },

    createAgentWallet: async (agentId: string, body: any) => {
      const { data, error } = await client.POST("/v1/agents/{agent_id}/wallet" as any, {
        params: { path: { agent_id: agentId } },
        body,
      } as any);
      return { data, error };
    },

    updateAgentWallet: async (agentId: string, body: any) => {
      const { data, error } = await client.PUT("/v1/agents/{agent_id}/wallet" as any, {
        params: { path: { agent_id: agentId } },
        body,
      } as any);
      return { data, error };
    },

    deleteAgentWallet: async (agentId: string) => {
      const { data, error } = await client.DELETE("/v1/agents/{agent_id}/wallet" as any, {
        params: { path: { agent_id: agentId } },
      } as any);
      return { data, error };
    },

    getAgentWalletBalance: async (agentId: string) => {
      const { data, error } = await client.GET("/v1/agents/{agent_id}/wallet/balance" as any, {
        params: { path: { agent_id: agentId } },
      } as any);
      return { data, error };
    },

    getAgentWalletPayments: async (agentId: string, params?: { protocol?: string; status?: string; page?: number; page_size?: number }) => {
      const { data, error } = await client.GET("/v1/agents/{agent_id}/wallet/payments" as any, {
        params: { path: { agent_id: agentId }, query: params },
      } as any);
      return { data, error };
    },

    fundAgentWallet: async (agentId: string, body: any) => {
      const { data, error } = await client.POST("/v1/agents/{agent_id}/wallet/fund" as any, {
        params: { path: { agent_id: agentId } },
        body,
      } as any);
      return { data, error };
    },

    getAllTasks: async () => {
      const { data, error } = await client.GET("/v1/tasks/");
      return { data, error };
    },

    getInbox: async (params?: { status?: string; agent_id?: string; page?: number; page_size?: number }) => {
      const { data, error } = await client.GET("/v1/inbox/" as any, {
        params: { query: params },
      } as any);
      return { data, error };
    },

    getTask: async (taskId: string) => {
      const { data, error } = await client.GET("/v1/tasks/{task_id}" as any, {
        params: { path: { task_id: taskId } },
      });
      return { data, error };
    },

    // Audit Logs API
    listAuditLogs: async (params?: {
      action?: string;
      actor_id?: string;
      resource_type?: string;
      resource_id?: string;
      since?: string;
      until?: string;
      cursor?: string;
      limit?: number;
    }) => {
      const { data, error } = await client.GET("/v1/audit-logs/" as any, {
        params: { query: params },
      } as any);
      return { data, error };
    },
  };
}

// Type for the API client
export type ApiClient = ReturnType<typeof createApiClient>;

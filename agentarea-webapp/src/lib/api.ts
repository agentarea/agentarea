import { client as serverClient } from "@/api/client/client.gen";
import * as sdk from "@/api/client/sdk.gen";
import type {
  A2UiActionPayload,
  AgentareaApiApiV1ModelSpecsModelSpecResponse,
  AgentCreate,
  AgentResponse,
  AgentUpdate,
  AnalyzeRequest,
  AgentCard as ApiAgentCard,
  TaskResponse as ApiTaskResponse,
  CreateInvitationBody,
  CreateWalletRequest,
  FundWalletRequest,
  HttpValidationError,
  ImportWorkspaceConfigV1WorkspaceImportPostData,
  InstallRequest,
  InvitationCreatedResponse,
  InvitationResponse,
  ListPolicyRulesV1PoliciesGetData,
  ListRelationshipsV1AccessControlRelationshipsGetData,
  McpInstanceConsumer,
  McpServerCreate,
  McpServerInstanceCreate,
  McpServerInstanceResponse,
  McpServerInstanceUpdate,
  McpServerResponse,
  McpServerUpdate,
  MemberResponse,
  ModelInstanceBulkCreateRequest,
  ModelInstanceCreate,
  ModelInstanceResponse,
  ModelSpecCreate,
  ModelSpecUpdate,
  OpenApiConnectionCreate,
  OpenApiConnectionUpdate,
  PaginatedResponseSkillResponse,
  PolicyRuleCreateRequest,
  PolicyRuleUpdateRequest,
  ProjectCreate,
  ProjectResponse,
  ProjectUpdate,
  ProviderConfigCreate,
  ProviderConfigResponse,
  ProviderConfigUpdate,
  ProviderSpecResponse,
  ProviderSpecWithModelsResponse,
  RelationshipWriteRequest,
  ResolveRequest,
  SkillContentResponse,
  SkillCreateRequest,
  SkillFileResponse,
  SkillResponse,
  SkillUpdateRequest,
  TaskCreate,
  TriggerCreate,
  UpdateWalletRequest,
  ValidateRequest,
} from "@/api/client/types.gen";

type RawRequestOptions = {
  body?: unknown;
  params?: {
    path?: Record<string, unknown>;
    query?: Record<string, unknown>;
  };
};

type RawMethod = "DELETE" | "GET" | "PATCH" | "POST" | "PUT";

function requestJson<TData = unknown, TError = unknown>(
  method: RawMethod,
  url: string,
  options?: RawRequestOptions
) {
  const { params, ...rest } = options ?? {};
  return serverClient.request<TData, TError>({
    ...rest,
    method,
    path: params?.path,
    query: params?.query,
    url,
  });
}

interface McpContainerHealthCheck {
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
}

function withStatus<TData, TError>(result: {
  data?: TData;
  error?: TError;
  response?: Response;
}) {
  return {
    data: result.data,
    error: result.error,
    status: result.response?.status,
  };
}

// Extract a human-readable message from an API error. The backend returns
// RFC 9457 problem+json ({ type, title, status, code, detail, ... }); validation
// failures carry field errors under `errors`. We also keep the legacy FastAPI
// shape (detail-as-array of {msg}) for backward compatibility.
function formatErrorDetail(error: unknown) {
  if (!error) return "No response data";
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  if (typeof error === "object") {
    const obj = error as {
      detail?: unknown;
      errors?: unknown;
      title?: unknown;
    };

    // problem+json validation errors: surface field-level messages.
    if (Array.isArray(obj.errors) && obj.errors.length > 0) {
      const msgs = obj.errors
        .map((item) =>
          typeof item === "object" && item && "msg" in item
            ? String((item as { msg: unknown }).msg)
            : String(item)
        )
        .filter(Boolean);
      if (msgs.length > 0) return msgs.join(", ");
    }

    const detail = obj.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      // Legacy FastAPI validation shape.
      return detail
        .map((item) =>
          typeof item === "object" && item && "msg" in item
            ? String((item as { msg: unknown }).msg)
            : String(item)
        )
        .join(", ");
    }

    // problem+json without a usable detail: fall back to the title.
    if (typeof obj.title === "string") return obj.title;
  }
  return JSON.stringify(error);
}

export const listAgents = async () => {
  const { data, error } = await sdk.listAgentsV1AgentsGet({
    client: serverClient,
  });
  return { data, error };
};

export const createAgent = async (agent: AgentCreate) => {
  const { data, error } = await sdk.createAgentV1AgentsPost({
    client: serverClient,
    body: agent,
  });
  return { data, error };
};

export const getAgent = async (agentId: string) => {
  const result = await sdk.getAgentV1AgentsAgentIdGet({
    client: serverClient,
    path: { agent_id: agentId },
  });
  return withStatus(result);
};

export const deleteAgent = async (agentId: string) => {
  const { data, error } = await sdk.deleteAgentV1AgentsAgentIdDelete({
    client: serverClient,
    path: { agent_id: agentId },
  });
  return { data, error };
};

export const installAgent = async (agentId: string) => {
  const result = await sdk.installAgentV1AgentsAgentIdInstallPost({
    client: serverClient,
    path: { agent_id: agentId },
  });
  return withStatus(result);
};

export const updateAgent = async (agentId: string, agent: AgentUpdate) => {
  const { data, error } = await sdk.updateAgentV1AgentsAgentIdPatch({
    client: serverClient,
    path: { agent_id: agentId },
    body: agent,
  });
  return { data, error };
};

export const listRegistries = async (params?: {
  registry_type?: string;
  active_only?: boolean;
}) => {
  const { data, error } = await sdk.listRegistriesV1RegistriesGet({
    client: serverClient,
    query: params,
  });
  return { data, error };
};

export const listRegistryItems = async (
  registryId: string,
  params?: { limit?: number; offset?: number }
) => {
  const { data, error } =
    await sdk.listRegistryItemsV1RegistriesRegistryIdItemsGet({
      client: serverClient,
      path: { registry_id: registryId },
      query: params,
    });
  return { data, error };
};

export const getCatalogItem = async (itemId: string) => {
  const { data, error } =
    await sdk.getCatalogItemV1RegistriesCatalogItemsItemIdGet({
      client: serverClient,
      path: { item_id: itemId },
    });
  return { data, error };
};

export const analyzeBundle = async (body: AnalyzeRequest) => {
  const { data, error } = await sdk.analyzeBundleV1BundlesAnalyzePost({
    client: serverClient,
    body,
  });
  return { data, error };
};

export const installBundle = async (body: InstallRequest) => {
  const { data, error } = await sdk.installBundleV1BundlesInstallPost({
    client: serverClient,
    body,
  });
  return { data, error };
};

export const listAgentTasks = async (agentId: string) => {
  const { data, error } = await sdk.listAgentTasksV1AgentsAgentIdTasksGet({
    client: serverClient,
    path: { agent_id: agentId },
  });
  return { data, error };
};

export const createAgentTask = async (agentId: string, task: TaskCreate) => {
  // Use the synchronous (non-streaming) endpoint: it returns the created
  // task as JSON (including its id) right after the workflow is started,
  // so callers can redirect to /tasks/{id}. The bare POST /tasks/ returns
  // an SSE stream, which a JSON client cannot parse — the task gets created
  // but no id is ever returned.
  const { data, error } =
    await sdk.createTaskForAgentSyncV1AgentsAgentIdTasksSyncPost({
      client: serverClient,
      path: { agent_id: agentId },
      body: task,
    });
  return { data, error };
};

export const getAgentTask = async (agentId: string, taskId: string) => {
  const result = await sdk.getAgentTaskV1AgentsAgentIdTasksTaskIdGet({
    client: serverClient,
    path: { agent_id: agentId, task_id: taskId },
  });
  return withStatus(result);
};

export const getAgentTaskById = async (agentId: string, taskId: string) => {
  const result = await sdk.getAgentTaskV1AgentsAgentIdTasksTaskIdGet({
    client: serverClient,
    path: { agent_id: agentId, task_id: taskId },
  });
  return withStatus(result);
};

export const cancelAgentTask = async (agentId: string, taskId: string) => {
  const { data, error } =
    await sdk.cancelAgentTaskV1AgentsAgentIdTasksTaskIdDelete({
      client: serverClient,
      path: { agent_id: agentId, task_id: taskId },
    });
  return { data, error };
};

export const getAgentTaskStatus = async (agentId: string, taskId: string) => {
  try {
    const response =
      await sdk.getAgentTaskStatusV1AgentsAgentIdTasksTaskIdStatusGet({
        client: serverClient,
        path: { agent_id: agentId, task_id: taskId },
      });
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
            result?: unknown;
            message?: string;
            artifacts?: unknown;
            session_id?: string;
            usage_metadata?: unknown;
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
};

export const pauseAgentTask = async (agentId: string, taskId: string) => {
  const { data, error } =
    await sdk.pauseAgentTaskV1AgentsAgentIdTasksTaskIdPausePost({
      client: serverClient,
      path: { agent_id: agentId, task_id: taskId },
    });
  return { data, error };
};

export const resumeAgentTask = async (agentId: string, taskId: string) => {
  const { data, error } =
    await sdk.resumeAgentTaskV1AgentsAgentIdTasksTaskIdResumePost({
      client: serverClient,
      path: { agent_id: agentId, task_id: taskId },
    });
  return { data, error };
};

export const continueAgentTask = async (
  taskId: string,
  additionalIterations: number,
  additionalBudgetUsd?: string
) => {
  const body: Record<string, number | string> = {
    additional_iterations: additionalIterations,
  };
  if (additionalBudgetUsd) {
    body.additional_budget_usd = additionalBudgetUsd;
  }
  const { data, error } = await requestJson(
    "POST",
    "/v1/tasks/{task_id}/continue",
    {
      params: { path: { task_id: taskId } },
      body,
    }
  );
  return { data, error };
};

export const sendTaskCommand = async (
  agentId: string,
  taskId: string,
  payload: { command: string; [key: string]: unknown }
) => {
  const { data, error } =
    await sdk.sendTaskCommandV1AgentsAgentIdTasksTaskIdCommandPost({
      client: serverClient,
      path: { agent_id: agentId, task_id: taskId },
      body: payload,
    });
  return { data, error };
};

export const sendA2UIAction = async (
  agentId: string,
  taskId: string,
  payload: A2UiActionPayload
) => {
  const { data, error } =
    await sdk.sendA2UiActionV1AgentsAgentIdTasksTaskIdA2UiActionPost({
      client: serverClient,
      path: { agent_id: agentId, task_id: taskId },
      body: payload,
    });
  return { data, error };
};

export const resolveEscalation = async (
  agentId: string,
  taskId: string,
  escalationId: string,
  approved: boolean,
  comment: string = ""
) => {
  const { data, error } =
    await sdk.resolveTaskEscalationV1AgentsAgentIdTasksTaskIdResolveEscalationPost(
      {
        client: serverClient,
        path: { agent_id: agentId, task_id: taskId },
        body: { escalation_id: escalationId, approved, comment },
      }
    );
  return { data, error };
};

export const submitTaskInput = async (
  agentId: string,
  taskId: string,
  submission: {
    input_request_id: string;
    answers: Record<string, unknown>;
    secrets: Record<string, string | { value: string; secret_name?: string }>;
  }
) => {
  const { data, error } =
    await sdk.submitTaskInputV1AgentsAgentIdTasksTaskIdInputPost({
      client: serverClient,
      path: { agent_id: agentId, task_id: taskId },
      body: submission,
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
  const { data, error } =
    await sdk.getTaskEventsV1AgentsAgentIdTasksTaskIdEventsGet({
      client: serverClient,
      path: { agent_id: agentId, task_id: taskId },
      query: {
        page: options.page || 1,
        page_size: options.page_size || 50,
        ...(options.event_type && { event_type: options.event_type }),
      },
    });
  return { data, error };
};

export const sendMessage = async (message: {
  agent_id: string;
  message: string;
  conversation_id?: string;
}) => {
  const { data, error } = await requestJson("POST", "/v1/chat/messages", {
    body: message,
  });
  return { data, error };
};

export const getChatAgents = async () => {
  const { data, error } = await requestJson("GET", "/v1/chat/agents", {});
  return { data, error };
};

export const getChatAgent = async (agentId: string) => {
  const { data, error } = await requestJson(
    "GET",
    "/v1/chat/agents/{agent_id}",
    {
      params: { path: { agent_id: agentId } },
    }
  );
  return { data, error };
};

export const getChatMessageStatus = async (taskId: string) => {
  const { data, error } = await requestJson(
    "GET",
    "/v1/chat/messages/{task_id}/status",
    {
      params: { path: { task_id: taskId } },
    }
  );
  return { data, error };
};

export const listMCPServers = async (params?: {
  status?: string;
  is_public?: boolean;
  tag?: string;
  page?: number;
  page_size?: number;
  search?: string;
}) => {
  const { data, error } = await sdk.listMcpServersV1McpServersGet({
    client: serverClient,
    query: params,
  });
  return { data, error };
};

export const createMCPServer = async (server: McpServerCreate) => {
  const { data, error } = await sdk.createMcpServerV1McpServersPost({
    client: serverClient,
    body: server,
  });
  return { data, error };
};

export const getMCPServer = async (serverId: string) => {
  const result = await sdk.getMcpServerV1McpServersServerIdGet({
    client: serverClient,
    path: { server_id: serverId },
  });
  return withStatus(result);
};

export const deleteMCPServer = async (serverId: string) => {
  const { data, error } = await sdk.deleteMcpServerV1McpServersServerIdDelete({
    client: serverClient,
    path: { server_id: serverId },
  });
  return { data, error };
};

export const updateMCPServer = async (
  serverId: string,
  server: McpServerUpdate
) => {
  const { data, error } = await sdk.updateMcpServerV1McpServersServerIdPatch({
    client: serverClient,
    path: { server_id: serverId },
    body: server,
  });
  return { data, error };
};

export const deployMCPServer = async (serverId: string) => {
  const { data, error } =
    await sdk.deployMcpServerV1McpServersServerIdDeployPost({
      client: serverClient,
      path: { server_id: serverId },
    });
  return { data, error };
};

export const listMCPServerInstances = async () => {
  const { data, error } =
    await sdk.listMcpServerInstancesV1McpServerInstancesGet({
      client: serverClient,
    });
  return { data, error };
};

export const checkMCPServerInstanceConfiguration = async (checkRequest: {
  json_spec: Record<string, unknown>;
}) => {
  const { data, error } =
    await sdk.checkMcpServerInstanceConfigurationV1McpServerInstancesCheckPost({
      client: serverClient,
      body: checkRequest,
    });
  return { data, error };
};

export const createMCPServerInstance = async (
  instance: McpServerInstanceCreate
) => {
  const { data, error } =
    await sdk.createMcpServerInstanceV1McpServerInstancesPost({
      client: serverClient,
      body: instance,
    });
  return { data, error };
};

export const getMCPServerInstance = async (instanceId: string) => {
  const result =
    await sdk.getMcpServerInstanceV1McpServerInstancesInstanceIdGet({
      client: serverClient,
      path: { instance_id: instanceId },
    });
  return withStatus(result);
};

export const deleteMCPServerInstance = async (instanceId: string) => {
  const { data, error } =
    await sdk.deleteMcpServerInstanceV1McpServerInstancesInstanceIdDelete({
      client: serverClient,
      path: { instance_id: instanceId },
    });
  return { data, error };
};

export const updateMCPServerInstance = async (
  instanceId: string,
  instance: McpServerInstanceUpdate
) => {
  const { data, error } =
    await sdk.updateMcpServerInstanceV1McpServerInstancesInstanceIdPatch({
      client: serverClient,
      path: { instance_id: instanceId },
      body: instance,
    });
  return { data, error };
};

export const verifyMCPServerInstance = async (instanceId: string) => {
  const { data, error } =
    await sdk.verifyMcpServerInstanceV1McpServerInstancesInstanceIdVerifyPost({
      client: serverClient,
      path: { instance_id: instanceId },
    });
  return { data, error };
};

export const validateMCPServerInstanceSpec = async (spec: ValidateRequest) => {
  const { data, error } =
    await sdk.validateInstanceSpecV1McpServerInstancesValidatePost({
      client: serverClient,
      body: spec,
    });
  return { data, error };
};

export const getMCPServerInstanceEnvironment = async (instanceId: string) => {
  const { data, error } =
    await sdk.getInstanceEnvironmentV1McpServerInstancesInstanceIdEnvironmentGet(
      { client: serverClient, path: { instance_id: instanceId } }
    );
  return { data, error };
};

export const listProviderSpecs = async (params?: { is_builtin?: boolean }) => {
  const { data, error } = await sdk.listProviderSpecsV1ProviderSpecsGet({
    client: serverClient,
    query: params,
  });
  return { data, error };
};

export const listProviderSpecsWithModels = async (params?: {
  is_builtin?: boolean;
}) => {
  const { data, error } =
    await sdk.listProviderSpecsWithModelsV1ProviderSpecsWithModelsGet({
      client: serverClient,
      query: params,
    });
  return { data, error };
};

export const getProviderSpec = async (providerSpecId: string) => {
  const { data, error } =
    await sdk.getProviderSpecV1ProviderSpecsProviderSpecIdGet({
      client: serverClient,
      path: { provider_spec_id: providerSpecId },
    });
  return { data, error };
};

export const getProviderSpecByKey = async (providerKey: string) => {
  const { data, error } =
    await sdk.getProviderSpecByKeyV1ProviderSpecsByKeyProviderKeyGet({
      client: serverClient,
      path: { provider_key: providerKey },
    });
  return { data, error };
};

export const listProviderConfigs = async (params?: {
  provider_spec_id?: string;
  is_active?: boolean;
}) => {
  const { data, error } = await sdk.listProviderConfigsV1ProviderConfigsGet({
    client: serverClient,
    query: params,
  });
  return { data, error };
};

export const createProviderConfig = async (config: ProviderConfigCreate) => {
  const { data, error } = await sdk.createProviderConfigV1ProviderConfigsPost({
    client: serverClient,
    body: config,
  });
  return { data, error };
};

export const getProviderConfig = async (
  id: string
): Promise<ProviderConfigResponse> => {
  const response = await sdk.getProviderConfigV1ProviderConfigsConfigIdGet({
    client: serverClient,
    path: { config_id: id },
  });

  if (!response.data) {
    const error = new Error(
      `Failed to load provider config (${response.response?.status ?? "unknown"}): ${formatErrorDetail(response.error)}`
    );
    (error as Error & { status?: number }).status = response.response?.status;
    throw error;
  }

  return response.data;
};

export const updateProviderConfig = async (
  configId: string,
  config: ProviderConfigUpdate
) => {
  const { data, error } =
    await sdk.updateProviderConfigV1ProviderConfigsConfigIdPut({
      client: serverClient,
      path: { config_id: configId },
      body: config,
    });
  return { data, error };
};

export const deleteProviderConfig = async (configId: string) => {
  const { data, error } =
    await sdk.deleteProviderConfigV1ProviderConfigsConfigIdDelete({
      client: serverClient,
      path: { config_id: configId },
    });
  return { data, error };
};

export const discoverModels = async (configId: string) => {
  const { data, error } =
    await sdk.discoverModelsV1ProviderConfigsConfigIdDiscoverPost({
      client: serverClient,
      path: { config_id: configId },
    });
  return { data, error };
};

export const discoverModelsPreview = async (body: {
  provider_key: string;
  api_key?: string | null;
  endpoint_url?: string | null;
}) => {
  const { data, error } =
    await sdk.discoverModelsPreviewV1ProviderConfigsDiscoverPreviewPost({
      client: serverClient,
      body,
    });
  return { data, error };
};

export const listModelSpecs = async (params?: {
  provider_spec_id?: string;
  is_active?: boolean;
}) => {
  const { data, error } = await sdk.listModelSpecsV1ModelSpecsGet({
    client: serverClient,
    query: params,
  });
  return { data, error };
};

export const createModelSpec = async (spec: ModelSpecCreate) => {
  const { data, error } = await sdk.createModelSpecV1ModelSpecsPost({
    client: serverClient,
    body: spec,
  });
  return { data, error };
};

export const getModelSpec = async (modelSpecId: string) => {
  const { data, error } = await sdk.getModelSpecV1ModelSpecsModelSpecIdGet({
    client: serverClient,
    path: { model_spec_id: modelSpecId },
  });
  return { data, error };
};

export const deleteModelSpec = async (modelSpecId: string) => {
  const { data, error } =
    await sdk.deleteModelSpecV1ModelSpecsModelSpecIdDelete({
      client: serverClient,
      path: { model_spec_id: modelSpecId },
    });
  return { data, error };
};

export const updateModelSpec = async (
  modelSpecId: string,
  spec: ModelSpecUpdate
) => {
  const { data, error } = await sdk.updateModelSpecV1ModelSpecsModelSpecIdPatch(
    { client: serverClient, path: { model_spec_id: modelSpecId }, body: spec }
  );
  return { data, error };
};

export const listModelSpecsByProvider = async (
  providerSpecId: string,
  params?: { is_active?: boolean }
) => {
  const { data, error } =
    await sdk.listModelSpecsByProviderV1ModelSpecsByProviderProviderSpecIdGet({
      client: serverClient,
      path: { provider_spec_id: providerSpecId },
      query: params,
    });
  return { data, error };
};

export const getModelSpecByProviderAndName = async (
  providerSpecId: string,
  modelName: string
) => {
  const { data, error } =
    await sdk.getModelSpecByProviderAndNameV1ModelSpecsByProviderProviderSpecIdModelNameGet(
      {
        client: serverClient,
        path: { provider_spec_id: providerSpecId, model_name: modelName },
      }
    );
  return { data, error };
};

export const upsertModelSpec = async (spec: ModelSpecCreate) => {
  const { data, error } = await sdk.upsertModelSpecV1ModelSpecsUpsertPost({
    client: serverClient,
    body: spec,
  });
  return { data, error };
};

export const listModelInstances = async (params?: {
  provider_config_id?: string;
  model_spec_id?: string;
  is_active?: boolean;
}) => {
  const { data, error } = await sdk.listModelInstancesV1ModelInstancesGet({
    client: serverClient,
    query: params,
  });
  return { data, error };
};

export const createModelInstance = async (instance: ModelInstanceCreate) => {
  const { data, error } = await sdk.createModelInstanceV1ModelInstancesPost({
    client: serverClient,
    body: instance,
  });
  return { data, error };
};

export const bulkCreateModelInstances = async (
  body: ModelInstanceBulkCreateRequest
) => {
  const { data, error } =
    await sdk.createModelInstancesBulkV1ModelInstancesBulkPost({
      client: serverClient,
      body,
    });
  return { data, error };
};

export const testModelInstance = async (testRequest: {
  provider_config_id: string;
  model_spec_id: string;
  test_message?: string;
}) => {
  const { data, error } =
    await sdk.validateModelInstanceV1ModelInstancesTestPost({
      client: serverClient,
      body: testRequest,
    });
  return { data, error };
};

export const getModelInstance = async (instanceId: string) => {
  const { data, error } =
    await sdk.getModelInstanceV1ModelInstancesInstanceIdGet({
      client: serverClient,
      path: { instance_id: instanceId },
    });
  return { data, error };
};

export const deleteModelInstance = async (instanceId: string) => {
  const { data, error } =
    await sdk.deleteModelInstanceV1ModelInstancesInstanceIdDelete({
      client: serverClient,
      path: { instance_id: instanceId },
    });
  return { data, error };
};

export const healthCheck = async () => {
  // TODO: Implement health check endpoint
  return { data: { status: "healthy" }, error: null };
};

export const getCurrentUser = async () => {
  const { data, error } = await requestJson("GET", "/v1/auth/users/me", {});
  return { data, error };
};

export const testProtectedEndpoint = async () => {
  const { data, error } = await requestJson("GET", "/v1/protected/test", {});
  return { data, error };
};

export const listAllTools = async (options?: {
  include?: "code" | "mcp" | "code,mcp";
  mcpInstanceId?: string;
}) => {
  const { data, error } = await sdk.getAllToolsV1AgentsToolsGet({
    client: serverClient,
    query: {
      include: options?.include,
      mcp_instance_id: options?.mcpInstanceId,
    },
  });
  return { data, error };
};

export const getMCPHealthStatus = async (): Promise<{
  health_checks: McpContainerHealthCheck[];
  total: number;
}> => {
  try {
    const { data, error } =
      await sdk.getContainersHealthV1McpServerInstancesHealthContainersGet({
        client: serverClient,
      });
    if (error || !data) {
      return { health_checks: [], total: 0 };
    }
    return data as { health_checks: McpContainerHealthCheck[]; total: number };
  } catch (error) {
    console.warn("Failed to fetch MCP health status:", error);
    return { health_checks: [], total: 0 };
  }
};

export const getMCPInstanceHealth = async (
  managerServiceName: string
): Promise<{
  health_check: McpContainerHealthCheck | null;
}> => {
  try {
    const { data, error } =
      await sdk.getContainersHealthV1McpServerInstancesHealthContainersGet({
        client: serverClient,
      });
    if (error || !data) {
      return { health_check: null };
    }
    const healthData = data as { health_checks?: McpContainerHealthCheck[] };
    const healthCheck = healthData.health_checks?.find(
      (check) => check.service_name === managerServiceName
    );
    return { health_check: healthCheck || null };
  } catch (error) {
    console.warn("Failed to fetch MCP instance health:", error);
    return { health_check: null };
  }
};

export type MCPInstanceConsumer = McpInstanceConsumer;

export const getMCPInstanceConsumers = async (
  instanceId: string
): Promise<MCPInstanceConsumer[]> => {
  try {
    const { data, error } =
      await sdk.listMcpServerInstanceConsumersV1McpServerInstancesInstanceIdConsumersGet(
        {
          client: serverClient,
          path: { instance_id: instanceId },
        }
      );
    if (error || !data) return [];
    return data;
  } catch (error) {
    console.warn("Failed to fetch MCP instance consumers:", error);
    return [];
  }
};

type ListSkillsOptions = {
  page?: number;
  page_size?: number;
  search?: string;
  source_type?: string;
  network_scope?: string;
  from_registry?: boolean;
};

type ListSkillsError = HttpValidationError | undefined;

export async function listSkills(
  options: ListSkillsOptions & { paginated: true }
): Promise<{
  data: PaginatedResponseSkillResponse | undefined;
  error: ListSkillsError;
}>;
export async function listSkills(
  options?: ListSkillsOptions & { paginated?: false }
): Promise<{ data: SkillResponse[]; error: ListSkillsError }>;
export async function listSkills(
  options: ListSkillsOptions & { paginated?: boolean } = {}
) {
  const pageSize = options.page_size || (options.paginated ? 50 : 100);
  const query = (page: number) => ({
    page,
    page_size: pageSize,
    ...(options.search ? { search: options.search } : {}),
    ...(options.source_type ? { source_type: options.source_type } : {}),
    ...(options.network_scope ? { network_scope: options.network_scope } : {}),
    ...(options.from_registry !== undefined
      ? { from_registry: options.from_registry }
      : {}),
  });

  const { data, error } = await sdk.listSkillsV1SkillsGet({
    client: serverClient,
    query: query(options.page || 1),
  });

  if (options.paginated) {
    return { data, error };
  }

  const items = Array.isArray(data) ? data : data?.items || [];
  if (error || Array.isArray(data) || !data?.has_next) {
    return { data: items, error };
  }

  const allItems = [...items];
  let page = data.page || 1;
  let hasNext = Boolean(data.has_next);
  while (hasNext) {
    page += 1;
    const next = await sdk.listSkillsV1SkillsGet({
      client: serverClient,
      query: query(page),
    });
    if (next.error) {
      return { data: allItems, error: next.error };
    }

    const nextData = next.data;
    const nextItems = Array.isArray(nextData)
      ? nextData
      : nextData?.items || [];
    allItems.push(...nextItems);
    hasNext = !Array.isArray(nextData) && Boolean(nextData?.has_next);
  }

  return { data: allItems, error: null };
}

export const getSkill = async (skillId: string) => {
  const result = await sdk.getSkillV1SkillsSkillIdGet({
    client: serverClient,
    path: { skill_id: skillId },
  });
  return withStatus(result);
};

export const getSkillContent = async (skillId: string) => {
  const { data, error } = await sdk.getSkillContentV1SkillsSkillIdContentGet({
    client: serverClient,
    path: { skill_id: skillId },
  });
  return { data, error };
};

export const getSkillFiles = async (
  skillId: string,
  includeUrls: boolean = false
) => {
  const { data, error } = await sdk.listSkillFilesV1SkillsSkillIdFilesGet({
    client: serverClient,
    path: { skill_id: skillId },
    query: { include_urls: includeUrls },
  });
  return { data, error };
};

export const getSkillFile = async (
  skillId: string,
  filePath: string,
  options?: { redirect?: boolean }
) => {
  const { data, error } = await sdk.getSkillFileV1SkillsSkillIdFilesPathGet({
    client: serverClient,
    path: { skill_id: skillId, path: filePath },
    query:
      options?.redirect === undefined
        ? undefined
        : { redirect: options.redirect },
  });
  return { data, error };
};

export const createSkill = async (skill: {
  content?: string | null;
  github_url?: string | null;
  name?: string | null;
  description?: string | null;
}) => {
  const { data, error } = await sdk.createSkillV1SkillsPost({
    client: serverClient,
    body: skill,
  });
  return { data, error };
};

export const uploadSkill = async (formData: FormData) => {
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
};

export const updateSkill = async (
  skillId: string,
  skill: {
    name?: string | null;
    description?: string | null;
    content?: string | null;
  }
) => {
  const { data, error } = await sdk.updateSkillV1SkillsSkillIdPut({
    client: serverClient,
    path: { skill_id: skillId },
    body: skill,
  });
  return { data, error };
};

export const installSkill = async (skillId: string) => {
  const { data, error } = await sdk.installSkillV1SkillsSkillIdInstallPost({
    client: serverClient,
    path: { skill_id: skillId },
  });
  return { data, error };
};

export const deleteSkill = async (skillId: string) => {
  const { data, error } = await sdk.deleteSkillV1SkillsSkillIdDelete({
    client: serverClient,
    path: { skill_id: skillId },
  });
  return { data, error };
};

export const listMCPAuthConfigs = async () => {
  const { data, error } = await sdk.listMcpAuthConfigsV1McpAuthConfigsGet({
    client: serverClient,
  });
  return { data, error };
};

export const createMCPAuthConfig = async (body: {
  name: string;
  description?: string;
  auth_type: string;
  config?: Record<string, unknown>;
  credentials?: Record<string, unknown>;
}) => {
  const { data, error } = await sdk.createMcpAuthConfigV1McpAuthConfigsPost({
    client: serverClient,
    body,
  });
  return { data, error };
};

export const listAPIKeys = async () => {
  const { data, error } = await sdk.listApiKeysV1ApiKeysGet({
    client: serverClient,
  });
  return { data, error };
};

export const createAPIKey = async (body: {
  name: string;
  expires_in_days?: number;
}) => {
  const { data, error } = await sdk.createApiKeyV1ApiKeysPost({
    client: serverClient,
    body,
  });
  return { data, error };
};

export const getAPIKey = async (tokenId: string) => {
  const { data, error } = await sdk.getApiKeyV1ApiKeysTokenIdGet({
    client: serverClient,
    path: { token_id: tokenId },
  });
  return { data, error };
};

export const revokeAPIKey = async (tokenId: string) => {
  const { data, error } = await sdk.revokeApiKeyV1ApiKeysTokenIdDelete({
    client: serverClient,
    path: { token_id: tokenId },
  });
  return { data, error };
};

export const listTriggerCatalog = async () => {
  const { data, error } = await sdk.getCatalogV1TriggersCatalogGet({
    client: serverClient,
  });
  return { data, error };
};

export const listTriggers = async (params?: {
  agent_id?: string;
  trigger_type?: string;
  active_only?: boolean;
}) => {
  const { data, error } = await sdk.listTriggersV1TriggersGet({
    client: serverClient,
    query: params,
  });
  return { data, error };
};

export const createTrigger = async (body: {
  name: string;
  trigger_type: TriggerCreate["trigger_type"];
  agent_id: string;
  config: Record<string, unknown>;
  task_parameters?: Record<string, unknown>;
  failure_threshold?: number;
}) => {
  // Flatten config into the body — backend expects flat fields
  const { config, ...rest } = body;
  const flat = { ...rest, ...config };
  const { data, error } = await sdk.createTriggerV1TriggersPost({
    client: serverClient,
    body: flat,
  });
  return { data, error };
};

export const getTrigger = async (triggerId: string) => {
  const result = await sdk.getTriggerV1TriggersTriggerIdGet({
    client: serverClient,
    path: { trigger_id: triggerId },
  });
  return withStatus(result);
};

export const updateTrigger = async (
  triggerId: string,
  body: {
    name?: string;
    cron_expression?: string;
    timezone?: string;
    task_parameters?: Record<string, unknown>;
    failure_threshold?: number;
    description?: string;
    is_active?: boolean;
    conditions?: Record<string, unknown>;
  }
) => {
  const { data, error } = await sdk.updateTriggerV1TriggersTriggerIdPut({
    client: serverClient,
    path: { trigger_id: triggerId },
    body,
  });
  return { data, error };
};

export const deleteTrigger = async (triggerId: string) => {
  const { data, error } = await sdk.deleteTriggerV1TriggersTriggerIdDelete({
    client: serverClient,
    path: { trigger_id: triggerId },
  });
  return { data, error };
};

export const enableTrigger = async (triggerId: string) => {
  const { data, error } = await sdk.enableTriggerV1TriggersTriggerIdEnablePost({
    client: serverClient,
    path: { trigger_id: triggerId },
  });
  return { data, error };
};

export const disableTrigger = async (triggerId: string) => {
  const { data, error } =
    await sdk.disableTriggerV1TriggersTriggerIdDisablePost({
      client: serverClient,
      path: { trigger_id: triggerId },
    });
  return { data, error };
};

export const getTriggerStatus = async (triggerId: string) => {
  const { data, error } =
    await sdk.getTriggerStatusV1TriggersTriggerIdStatusGet({
      client: serverClient,
      path: { trigger_id: triggerId },
    });
  return { data, error };
};

export const getTriggerExecutions = async (
  triggerId: string,
  params?: {
    page?: number;
    page_size?: number;
  }
) => {
  const { data, error } =
    await sdk.getExecutionHistoryV1TriggersTriggerIdExecutionsGet({
      client: serverClient,
      path: { trigger_id: triggerId },
      query: params,
    });
  return { data, error };
};

export const getTriggerMetrics = async (triggerId: string) => {
  const { data, error } =
    await sdk.getExecutionMetricsV1TriggersTriggerIdMetricsGet({
      client: serverClient,
      path: { trigger_id: triggerId },
    });
  return { data, error };
};

export const getTriggerTimeline = async (triggerId: string) => {
  const { data, error } =
    await sdk.getExecutionTimelineV1TriggersTriggerIdTimelineGet({
      client: serverClient,
      path: { trigger_id: triggerId },
    });
  return { data, error };
};

export const getTriggerCorrelations = async (triggerId: string) => {
  const { data, error } =
    await sdk.getExecutionCorrelationsV1TriggersTriggerIdCorrelationsGet({
      client: serverClient,
      path: { trigger_id: triggerId },
    });
  return { data, error };
};

export const exportWorkspace = async () => {
  const { data, error } = await sdk.exportWorkspaceConfigV1WorkspaceExportGet({
    client: serverClient,
  });
  return { data, error };
};

export const importWorkspace = async (body: {
  config: string;
  skip_missing_dependencies?: boolean;
  override_existing?: boolean;
}) => {
  const payload: ImportWorkspaceConfigV1WorkspaceImportPostData["body"] = {
    yaml_content: body.config,
    skip_missing_dependencies: body.skip_missing_dependencies,
    override_existing: body.override_existing,
  };
  const { data, error } = await sdk.importWorkspaceConfigV1WorkspaceImportPost({
    client: serverClient,
    body: payload,
  });
  return { data, error };
};

export const listWorkspaceMembers = async (workspaceId: string) => {
  const { data, error } =
    await sdk.listMembersV1WorkspacesWorkspaceIdMembersGet({
      client: serverClient,
      path: { workspace_id: workspaceId },
    });
  return { data, error };
};

export const removeWorkspaceMember = async (
  workspaceId: string,
  userId: string
) => {
  const { data, error } =
    await sdk.removeMemberV1WorkspacesWorkspaceIdMembersUserIdDelete({
      client: serverClient,
      path: { workspace_id: workspaceId, user_id: userId },
    });
  return { data, error };
};

export const listWorkspaceInvitations = async (workspaceId: string) => {
  const { data, error } =
    await sdk.listInvitationsV1WorkspacesWorkspaceIdInvitationsGet({
      client: serverClient,
      path: { workspace_id: workspaceId },
    });
  return { data, error };
};

export const createWorkspaceInvitation = async (
  workspaceId: string,
  body: CreateInvitationBody
) => {
  const { data, error } =
    await sdk.createInvitationV1WorkspacesWorkspaceIdInvitationsPost({
      client: serverClient,
      path: { workspace_id: workspaceId },
      body,
    });
  return { data, error };
};

export const revokeWorkspaceInvitation = async (
  workspaceId: string,
  invitationId: string
) => {
  const { data, error } =
    await sdk.revokeInvitationV1WorkspacesWorkspaceIdInvitationsInvitationIdDelete(
      {
        client: serverClient,
        path: { workspace_id: workspaceId, invitation_id: invitationId },
      }
    );
  return { data, error };
};

export const acceptWorkspaceInvitation = async (token: string) => {
  const { data, error } = await sdk.acceptInvitationV1InvitationsAcceptPost({
    client: serverClient,
    body: { token },
  });
  return { data, error };
};

export const discoverMCPInstanceTools = async (instanceId: string) => {
  const { data, error } =
    await sdk.discoverMcpServerInstanceToolsV1McpServerInstancesInstanceIdDiscoverToolsPost(
      { client: serverClient, path: { instance_id: instanceId } }
    );
  return { data, error };
};

export const testMCPInstanceAuth = async (instanceId: string) => {
  const { data, error } =
    await sdk.runTestAuthV1McpServerInstancesInstanceIdTestAuthPost({
      client: serverClient,
      path: { instance_id: instanceId },
    });
  return { data, error };
};

export const listSkillMembers = async (skillId: string) => {
  const { data, error } = await sdk.listSkillMembersV1SkillsSkillIdMembersGet({
    client: serverClient,
    path: { skill_id: skillId },
  });
  if (error || !data) {
    return { data: [], error };
  }
  const { data: skills, error: skillsError } = await listSkills();
  if (skillsError) {
    return { data: [], error: skillsError };
  }
  const skillsById = new Map(skills.map((skill) => [skill.id, skill]));
  return {
    data: data
      .map((member) => skillsById.get(member.child_skill_id))
      .filter((skill): skill is SkillResponse => Boolean(skill)),
    error: null,
  };
};

export const addSkillMember = async (skillId: string, childSkillId: string) => {
  const { data, error } = await sdk.addSkillMemberV1SkillsSkillIdMembersPost({
    client: serverClient,
    path: { skill_id: skillId },
    body: { child_skill_id: childSkillId },
  });
  return { data, error };
};

export const removeSkillMember = async (
  skillId: string,
  childSkillId: string
) => {
  const { data, error } =
    await sdk.removeSkillMemberV1SkillsSkillIdMembersChildSkillIdDelete({
      client: serverClient,
      path: { skill_id: skillId, child_skill_id: childSkillId },
    });
  return { data, error };
};

export const flattenSkill = async (skillId: string) => {
  const { data, error } =
    await sdk.flattenSkillMembersV1SkillsSkillIdFlattenGet({
      client: serverClient,
      path: { skill_id: skillId },
    });
  return { data, error };
};

export const getNetworkTopology = async () => {
  const { data, error } = await sdk.getNetworkTopologyV1NetworkTopologyGet({
    client: serverClient,
  });
  return { data, error };
};

export const listOpenAPIConnections = async (params?: {
  status?: string;
  search?: string;
  limit?: number;
  offset?: number;
}) => {
  const { data, error } = await sdk.listConnectionsV1OpenapiConnectionsGet({
    client: serverClient,
    query: params,
  });
  return { data, error };
};

export const createOpenAPIConnection = async (
  body: OpenApiConnectionCreate
) => {
  const { data, error } = await sdk.createConnectionV1OpenapiConnectionsPost({
    client: serverClient,
    body,
  });
  return { data, error };
};

export const deleteOpenAPIConnection = async (connectionId: string) => {
  const { data, error } =
    await sdk.deleteConnectionV1OpenapiConnectionsConnectionIdDelete({
      client: serverClient,
      path: { connection_id: connectionId },
    });
  return { data, error };
};

export const getOpenAPIConnection = async (connectionId: string) => {
  const result = await sdk.getConnectionV1OpenapiConnectionsConnectionIdGet({
    client: serverClient,
    path: { connection_id: connectionId },
  });
  return withStatus(result);
};

export const updateOpenAPIConnection = async (
  connectionId: string,
  body: OpenApiConnectionUpdate
) => {
  const { data, error } =
    await sdk.updateConnectionV1OpenapiConnectionsConnectionIdPatch({
      client: serverClient,
      path: { connection_id: connectionId },
      body,
    });
  return { data, error };
};

export const discoverOpenAPITools = async (connectionId: string) => {
  const { data, error } =
    await sdk.discoverToolsV1OpenapiConnectionsConnectionIdDiscoverToolsPost({
      client: serverClient,
      path: { connection_id: connectionId },
    });
  return { data, error };
};

export const previewOpenAPISpec = async (body: {
  spec_url?: string;
  spec_content?: Record<string, unknown>;
}) => {
  const { data, error } =
    await sdk.previewSpecV1OpenapiConnectionsPreviewSpecPost({
      client: serverClient,
      body,
    });
  return { data, error };
};

export const listCompoundMCPs = async () => {
  const { data, error } = await requestJson("GET", "/v1/compound-mcps/", {});
  return { data, error };
};

export const getCompoundMCP = async (compoundId: string) => {
  const { data, error } = await requestJson(
    "GET",
    "/v1/compound-mcps/{compound_id}",
    {
      params: { path: { compound_id: compoundId } },
    }
  );
  return { data, error };
};

export const createCompoundMCP = async (body: unknown) => {
  const { data, error } = await requestJson("POST", "/v1/compound-mcps/", {
    body,
  });
  return { data, error };
};

export const updateCompoundMCP = async (compoundId: string, body: unknown) => {
  const { data, error } = await requestJson(
    "PUT",
    "/v1/compound-mcps/{compound_id}",
    {
      params: { path: { compound_id: compoundId } },
      body,
    }
  );
  return { data, error };
};

export const deleteCompoundMCP = async (compoundId: string) => {
  const { data, error } = await requestJson(
    "DELETE",
    "/v1/compound-mcps/{compound_id}",
    {
      params: { path: { compound_id: compoundId } },
    }
  );
  return { data, error };
};

export const listCompoundMCPMembers = async (compoundId: string) => {
  const { data, error } = await requestJson(
    "GET",
    "/v1/compound-mcps/{compound_id}/members",
    {
      params: { path: { compound_id: compoundId } },
    }
  );
  return { data, error };
};

export const addCompoundMCPMember = async (
  compoundId: string,
  body: unknown
) => {
  const { data, error } = await requestJson(
    "POST",
    "/v1/compound-mcps/{compound_id}/members",
    {
      params: { path: { compound_id: compoundId } },
      body,
    }
  );
  return { data, error };
};

export const removeCompoundMCPMember = async (
  compoundId: string,
  instanceId: string
) => {
  const { data, error } = await requestJson(
    "DELETE",
    "/v1/compound-mcps/{compound_id}/members/{instance_id}",
    {
      params: {
        path: { compound_id: compoundId, instance_id: instanceId },
      },
    }
  );
  return { data, error };
};

export const listProjects = async () => {
  const { data, error } = await sdk.listProjectsV1ProjectsGet({
    client: serverClient,
  });
  return { data, error };
};

export const getProject = async (projectId: string) => {
  const result = await sdk.getProjectV1ProjectsProjectIdGet({
    client: serverClient,
    path: { project_id: projectId },
  });
  return withStatus(result);
};

export const createProject = async (project: ProjectCreate) => {
  const { data, error } = await sdk.createProjectV1ProjectsPost({
    client: serverClient,
    body: project,
  });
  return { data, error };
};

export const updateProject = async (
  projectId: string,
  project: ProjectUpdate
) => {
  const { data, error } = await sdk.updateProjectV1ProjectsProjectIdPatch({
    client: serverClient,
    path: { project_id: projectId },
    body: project,
  });
  return { data, error };
};

export const deleteProject = async (projectId: string) => {
  const { data, error } = await sdk.deleteProjectV1ProjectsProjectIdDelete({
    client: serverClient,
    path: { project_id: projectId },
  });
  return { data, error };
};

export const addSkillToProject = async (projectId: string, skillId: string) => {
  const { data, error } =
    await sdk.addSkillToProjectV1ProjectsProjectIdSkillsPost({
      client: serverClient,
      path: { project_id: projectId },
      body: { id: skillId },
    });
  return { data, error };
};

export const removeSkillFromProject = async (
  projectId: string,
  skillId: string
) => {
  const { data, error } =
    await sdk.removeSkillFromProjectV1ProjectsProjectIdSkillsSkillIdDelete({
      client: serverClient,
      path: { project_id: projectId, skill_id: skillId },
    });
  return { data, error };
};

export const addAgentToProject = async (projectId: string, agentId: string) => {
  const { data, error } =
    await sdk.addAgentToProjectV1ProjectsProjectIdAgentsPost({
      client: serverClient,
      path: { project_id: projectId },
      body: { id: agentId },
    });
  return { data, error };
};

export const removeAgentFromProject = async (
  projectId: string,
  agentId: string
) => {
  const { data, error } =
    await sdk.removeAgentFromProjectV1ProjectsProjectIdAgentsAgentIdDelete({
      client: serverClient,
      path: { project_id: projectId, agent_id: agentId },
    });
  return { data, error };
};

export const addMcpInstanceToProject = async (
  projectId: string,
  mcpInstanceId: string
) => {
  const { data, error } =
    await sdk.addMcpInstanceToProjectV1ProjectsProjectIdMcpInstancesPost({
      client: serverClient,
      path: { project_id: projectId },
      body: { id: mcpInstanceId },
    });
  return { data, error };
};

export const removeMcpInstanceFromProject = async (
  projectId: string,
  mcpInstanceId: string
) => {
  const { data, error } =
    await sdk.removeMcpInstanceFromProjectV1ProjectsProjectIdMcpInstancesMcpInstanceIdDelete(
      {
        client: serverClient,
        path: { project_id: projectId, mcp_instance_id: mcpInstanceId },
      }
    );
  return { data, error };
};

export const listClients = async () => {
  const { data, error } = await sdk.listClientsV1ClientsGet({
    client: serverClient,
  });
  return { data, error };
};

export const getClient = async (clientId: string) => {
  const result = await sdk.getClientV1ClientsClientIdGet({
    client: serverClient,
    path: { client_id: clientId },
  });
  return withStatus(result);
};

export const createClient = async (payload: {
  name: string;
  description?: string | null;
  source_project_id?: string | null;
}) => {
  const { data, error } = await sdk.createClientV1ClientsPost({
    client: serverClient,
    body: payload,
  });
  return { data, error };
};

export const updateClient = async (
  clientId: string,
  payload: {
    name?: string;
    description?: string | null;
    source_project_id?: string | null;
  }
) => {
  const { data, error } = await sdk.updateClientV1ClientsClientIdPatch({
    client: serverClient,
    path: { client_id: clientId },
    body: payload,
  });
  return { data, error };
};

export const deleteClient = async (clientId: string) => {
  const { data, error } = await sdk.deleteClientV1ClientsClientIdDelete({
    client: serverClient,
    path: { client_id: clientId },
  });
  return { data, error };
};

export const addSkillToClient = async (clientId: string, skillId: string) => {
  const { data, error } = await sdk.addSkillToClientV1ClientsClientIdSkillsPost(
    {
      client: serverClient,
      path: { client_id: clientId },
      body: { id: skillId },
    }
  );
  return { data, error };
};

export const removeSkillFromClient = async (
  clientId: string,
  skillId: string
) => {
  const { data, error } =
    await sdk.removeSkillFromClientV1ClientsClientIdSkillsSkillIdDelete({
      client: serverClient,
      path: { client_id: clientId, skill_id: skillId },
    });
  return { data, error };
};

export const addMcpInstanceToClient = async (
  clientId: string,
  mcpInstanceId: string,
  namespacePrefix?: string | null
) => {
  const { data, error } =
    await sdk.addMcpInstanceToClientV1ClientsClientIdMcpInstancesPost({
      client: serverClient,
      path: { client_id: clientId },
      body: { id: mcpInstanceId, namespace_prefix: namespacePrefix ?? null },
    });
  return { data, error };
};

export const removeMcpInstanceFromClient = async (
  clientId: string,
  mcpInstanceId: string
) => {
  const { data, error } =
    await sdk.removeMcpInstanceFromClientV1ClientsClientIdMcpInstancesMcpInstanceIdDelete(
      {
        client: serverClient,
        path: { client_id: clientId, mcp_instance_id: mcpInstanceId },
      }
    );
  return { data, error };
};

export const pullClientFromProject = async (
  clientId: string,
  projectId: string | null
) => {
  const { data, error } =
    await sdk.pullFromProjectV1ClientsClientIdPullFromProjectPost({
      client: serverClient,
      path: { client_id: clientId },
      body: { project_id: projectId },
    });
  return { data, error };
};

export const listProjectFiles = async (projectId: string) => {
  const { data, error } = await sdk.listProjectFilesV1ProjectsProjectIdFilesGet(
    { client: serverClient, path: { project_id: projectId } }
  );
  return { data, error };
};

export const uploadProjectFile = async (
  projectId: string,
  formData: FormData
) => {
  const response = await fetch(`/api/proxy/v1/projects/${projectId}/files`, {
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
};

export const downloadProjectFile = async (
  projectId: string,
  filePath: string
) => {
  const { data, error } =
    await sdk.downloadProjectFileV1ProjectsProjectIdFilesFilePathGet({
      client: serverClient,
      path: { project_id: projectId, file_path: filePath },
    });
  return { data, error };
};

export const deleteProjectFile = async (
  projectId: string,
  filePath: string
) => {
  const { data, error } =
    await sdk.deleteProjectFileV1ProjectsProjectIdFilesFilePathDelete({
      client: serverClient,
      path: { project_id: projectId, file_path: filePath },
    });
  return { data, error };
};

export const listWorkspaceFiles = async () => {
  const { data, error } = await sdk.listWorkspaceFilesV1FilesGet({
    client: serverClient,
  });
  return { data, error };
};

export const downloadWorkspaceFile = async (filePath: string) => {
  const { data, error } = await sdk.downloadWorkspaceFileV1FilesFilePathGet({
    client: serverClient,
    path: { file_path: filePath },
  });
  return { data, error };
};

export const workspaceFileHistory = async (filePath: string) => {
  const { data, error } = await sdk.workspaceFileHistoryV1FilesHistoryGet({
    client: serverClient,
    query: { path: filePath },
  });
  return { data, error };
};

export const getAgentWallet = async (agentId: string) => {
  const { data, error } = await sdk.getWalletV1AgentsAgentIdWalletGet({
    client: serverClient,
    path: { agent_id: agentId },
  });
  return { data, error };
};

export const createAgentWallet = async (
  agentId: string,
  body: CreateWalletRequest
) => {
  const { data, error } = await sdk.createWalletV1AgentsAgentIdWalletPost({
    client: serverClient,
    path: { agent_id: agentId },
    body,
  });
  return { data, error };
};

export const updateAgentWallet = async (
  agentId: string,
  body: UpdateWalletRequest
) => {
  const { data, error } = await sdk.updateWalletV1AgentsAgentIdWalletPut({
    client: serverClient,
    path: { agent_id: agentId },
    body,
  });
  return { data, error };
};

export const deleteAgentWallet = async (agentId: string) => {
  const { data, error } = await sdk.deleteWalletV1AgentsAgentIdWalletDelete({
    client: serverClient,
    path: { agent_id: agentId },
  });
  return { data, error };
};

export const getAgentWalletBalance = async (agentId: string) => {
  const { data, error } =
    await sdk.getWalletBalanceV1AgentsAgentIdWalletBalanceGet({
      client: serverClient,
      path: { agent_id: agentId },
    });
  return { data, error };
};

export const getAgentWalletPayments = async (
  agentId: string,
  params?: {
    protocol?: string;
    status?: string;
    page?: number;
    page_size?: number;
  }
) => {
  const { data, error } =
    await sdk.getPaymentHistoryV1AgentsAgentIdWalletPaymentsGet({
      client: serverClient,
      path: { agent_id: agentId },
      query: params,
    });
  return { data, error };
};

export const fundAgentWallet = async (
  agentId: string,
  body: FundWalletRequest
) => {
  const { data, error } = await sdk.fundWalletV1AgentsAgentIdWalletFundPost({
    client: serverClient,
    path: { agent_id: agentId },
    body,
  });
  return { data, error };
};

export const getAllTasks = async () => {
  const { data, error } = await sdk.getAllTasksV1TasksGet({
    client: serverClient,
  });
  return { data, error };
};

export const getInbox = async (params?: {
  status?: string;
  agent_id?: string;
  page?: number;
  page_size?: number;
}) => {
  const { data, error } = await sdk.getInboxItemsV1InboxGet({
    client: serverClient,
    query: params,
  });
  return { data, error };
};

export const getTask = async (taskId: string) => {
  const result = await sdk.getTaskByIdV1TasksTaskIdGet({
    client: serverClient,
    path: { task_id: taskId },
  });
  return withStatus(result);
};

export const listPolicies = async (
  params?: ListPolicyRulesV1PoliciesGetData["query"]
) => {
  const { data, error } = await sdk.listPolicyRulesV1PoliciesGet({
    client: serverClient,
    query: params,
  });
  return { data, error };
};

export const createPolicy = async (body: PolicyRuleCreateRequest) => {
  const { data, error } = await sdk.createPolicyRuleV1PoliciesPost({
    client: serverClient,
    body,
  });
  return { data, error };
};

export const updatePolicy = async (
  id: string,
  body: PolicyRuleUpdateRequest
) => {
  const { data, error } = await sdk.updatePolicyRuleV1PoliciesRuleIdPatch({
    client: serverClient,
    path: { rule_id: id },
    body,
  });
  return { data, error };
};

export const deletePolicy = async (id: string) => {
  const { data, error } = await sdk.deletePolicyRuleV1PoliciesRuleIdDelete({
    client: serverClient,
    path: { rule_id: id },
  });
  return { data, error };
};

export const previewEffectivePolicy = async (body?: {
  agent_id?: string;
  task_policy?: Record<string, unknown>;
}) => {
  const { data, error } =
    await sdk.previewEffectivePolicyV1GovernanceEffectivePolicyPreviewPost({
      client: serverClient,
      body: body ?? {},
    });
  return { data, error };
};

export const getTaskPolicySnapshot = async (taskId: string) => {
  const { data, error } =
    await sdk.getTaskPolicySnapshotV1GovernanceTaskPolicySnapshotsTaskIdGet({
      client: serverClient,
      path: { task_id: taskId },
    });
  return { data, error };
};

export const getAccessControlGraph = async () => {
  const { data, error } = await sdk.getGraphV1AccessControlGraphGet({
    client: serverClient,
  });
  return { data, error };
};

export const listAccessControlRelationships = async (
  params?: ListRelationshipsV1AccessControlRelationshipsGetData["query"]
) => {
  const { data, error } =
    await sdk.listRelationshipsV1AccessControlRelationshipsGet({
      client: serverClient,
      query: params,
    });
  return { data, error };
};

export const resolveAccessControl = async (body: ResolveRequest) => {
  const { data, error } = await sdk.resolveAccessV1AccessControlResolvePost({
    client: serverClient,
    body,
  });
  return { data, error };
};

export const createAccessControlRelationship = async (
  body: RelationshipWriteRequest
) => {
  const { data, error } =
    await sdk.createRelationshipV1AccessControlRelationshipsPost({
      client: serverClient,
      body,
    });
  return { data, error };
};

export const deleteAccessControlRelationship = async (
  body: RelationshipWriteRequest
) => {
  const { data, error } =
    await sdk.deleteRelationshipV1AccessControlRelationshipsDelete({
      client: serverClient,
      body,
    });
  return { data, error };
};

export const listSkillCollections = async () => {
  const { data, error } = await sdk.listCollectionsV1SkillCollectionsGet({
    client: serverClient,
  });
  return { data, error };
};

export const listAuditLogs = async (params?: {
  action?: string;
  actor_id?: string;
  resource_type?: string;
  resource_id?: string;
  since?: string;
  until?: string;
  cursor?: string;
  limit?: number;
}) => {
  const { data, error } = await sdk.listAuditLogsV1AuditLogsGet({
    client: serverClient,
    query: params,
  });
  return { data, error };
};

export const getBillingOverview = async () => {
  const result = await requestJson("GET", "/v1/billing/overview", {});
  return {
    data: result.data,
    error: result.error,
    status: result.response?.status,
  };
};

// Convenience helpers built on top of the generated API
interface TaskEventRecord {
  id: string;
  event_type: string;
  timestamp: string;
  data?: { content?: string; result?: string } | null;
}

export const getAgentTaskMessages = async (agentId: string, taskId: string) => {
  // Build message history from task events
  const { data: events, error } = await getAgentTaskEvents(agentId, taskId, {
    page_size: 100,
  });
  if (error || !events) {
    return { data: [], error };
  }

  const eventList = (events as { events: TaskEventRecord[] }).events;
  const messages = eventList
    .filter((event) =>
      ["LLMCallCompleted", "ToolCallCompleted", "WorkflowCompleted"].includes(
        event.event_type
      )
    )
    .map((event) => ({
      id: event.id,
      content: event.data?.content || event.data?.result || "",
      role: event.event_type === "LLMCallCompleted" ? "assistant" : "system",
      timestamp: event.timestamp,
    }));

  return { data: messages, error: null };
};

// Uses the global /v1/tasks/ endpoint which returns total_cost and agent_name
export const listProviderConfigsWithModelInstances = async (params?: {
  provider_spec_id?: string;
  is_active?: boolean;
}) => {
  const [providersResponse, configsResponse] = await Promise.all([
    listProviderSpecsWithModels(),
    listProviderConfigs(params),
  ]);
  if (configsResponse.error || !configsResponse.data) {
    return { configs: configsResponse, specs: providersResponse };
  }
  const configs = (configsResponse.data ?? []) as ProviderConfigResponse[];
  const specsWithModels = (providersResponse.data ??
    []) as ProviderSpecWithModelsResponse[];
  const specsById: Record<string, ProviderSpecWithModelsResponse> =
    Object.fromEntries(specsWithModels.map((s) => [s.id, s]));
  const configsWithModels = configs.map((config) => ({
    ...config,
    models_list: (config.model_instance_ids ?? [])
      .map((modelSpecId) => {
        const providerSpec = specsById[config.provider_spec_id];
        if (!providerSpec) return null;
        return providerSpec.models.find((m) => m.id === modelSpecId) || null;
      })
      .filter(Boolean),
  }));

  return {
    configs: { data: configsWithModels, error: null },
    specs: providersResponse,
  };
};

// Catalog page fetch (server-side, SSR for /explore). Sums one page across the
// active registries of a type, so the gallery's first paint is server-rendered
// instead of racing client `useState`. Returns raw items + a `hasMore` hint;
// the caller normalizes (see catalog-data.normalize).
export const fetchCatalogPage = async (
  registryType: string,
  offset: number,
  limit: number
) => {
  const { data: registries, error } = await listRegistries({
    registry_type: registryType,
    active_only: true,
  });
  if (error) return { items: [], hasMore: false, error };
  const lists = await Promise.all(
    (registries ?? []).map((r: { id: string }) =>
      listRegistryItems(r.id, { limit, offset })
    )
  );
  const items = lists.flatMap((l: { data?: unknown[] }) => l.data ?? []);
  // A short page (relative to the requested limit) means the server has no more.
  const hasMore = items.length >= limit;
  return { items, hasMore, error: null };
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

export type Agent = AgentResponse;
export type MCPServer = McpServerResponse;
export type MCPServerInstance = McpServerInstanceResponse;
export type ProviderSpec = ProviderSpecResponse;
export type ProviderSpecWithModels = ProviderSpecWithModelsResponse;
export type ProviderConfig = ProviderConfigResponse;
export type ModelSpec = AgentareaApiApiV1ModelSpecsModelSpecResponse;
export type ModelInstance = ModelInstanceResponse;
export type ChatAgent = AgentResponse;
export type ChatResponse = { task_id: string; status: string };
export type ConversationResponse = unknown;
export type TaskResponse = ApiTaskResponse;
export type AgentCard = ApiAgentCard;
export type TaskWithAgent = ApiTaskResponse & {
  agent_name?: string;
  agent_description?: string | null;
  // Set by the /v1/inbox endpoint for waiting_for_approval tasks so the inbox can
  // approve/reject the pending escalation inline.
  escalation_id?: string | null;
  escalation_tool_name?: string | null;
};

export type Skill = SkillResponse;
export type SkillContent = SkillContentResponse;
export type SkillFile = SkillFileResponse;
export type { SkillCreateRequest, SkillUpdateRequest };

export type Project = ProjectResponse;

export type WorkspaceMember = MemberResponse;
export type WorkspaceInvitation = InvitationResponse;
export type WorkspaceInvitationCreated = InvitationCreatedResponse;

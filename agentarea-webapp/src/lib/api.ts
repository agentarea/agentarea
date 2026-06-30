import type { AgentCard as ApiAgentCard, AgentResponse, AgentareaApiApiV1ModelSpecsModelSpecResponse, InvitationCreatedResponse, InvitationResponse, McpServerInstanceResponse, McpServerResponse, MemberResponse, ModelInstanceResponse, ProjectResponse, ProviderConfigResponse, ProviderSpecResponse, ProviderSpecWithModelsResponse, TaskResponse as ApiTaskResponse } from "@/api/client/types.gen";
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
  installAgent,

  // Registry / Catalog API
  listRegistries,
  listRegistryItems,
  analyzeBundle,
  installBundle,

  // Agent Task API
  listAgentTasks,
  createAgentTask,
  getAgentTask,
  getAgentTaskById,
  cancelAgentTask,
  getAgentTaskStatus,
  pauseAgentTask,
  resumeAgentTask,
  sendTaskCommand,
  sendA2UIAction,
  resolveEscalation,
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

  // OpenAPI Connections API
  listOpenAPIConnections,
  createOpenAPIConnection,
  updateOpenAPIConnection,
  deleteOpenAPIConnection,
  getOpenAPIConnection,
  discoverOpenAPITools,
  previewOpenAPISpec,

  // MCP Server Instance API
  listMCPServerInstances,
  checkMCPServerInstanceConfiguration,
  createMCPServerInstance,
  getMCPServerInstance,
  deleteMCPServerInstance,
  updateMCPServerInstance,
  verifyMCPServerInstance,
  validateMCPServerInstanceSpec,
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
  bulkCreateModelInstances,
  testModelInstance,
  getModelInstance,
  deleteModelInstance,
  discoverModels,
  discoverModelsPreview,

  // Utility API
  healthCheck,

  // Auth API
  getCurrentUser,
  testProtectedEndpoint,

  // Unified Tools API
  listAllTools,

  // MCP health
  getMCPHealthStatus,
  getMCPInstanceHealth,

  // Skills API
  listSkills,
  getSkill,
  getSkillContent,
  getSkillFiles,
  getSkillFile,
  createSkill,
  uploadSkill,
  updateSkill,
  installSkill,
  deleteSkill,

  // MCP Auth Config API
  listMCPAuthConfigs,
  createMCPAuthConfig,

  // API Keys API
  listAPIKeys,
  createAPIKey,
  getAPIKey,
  revokeAPIKey,

  // Triggers API
  listTriggerCatalog,
  listTriggers,
  createTrigger,
  getTrigger,
  updateTrigger,
  deleteTrigger,
  enableTrigger,
  disableTrigger,
  getTriggerStatus,
  getTriggerExecutions,
  getTriggerMetrics,
  getTriggerTimeline,
  getTriggerCorrelations,

  // Policies API (unified rule model)
  listPolicies,
  createPolicy,
  updatePolicy,
  deletePolicy,
  previewEffectivePolicy,
  getTaskPolicySnapshot,

  // Access-control graph explorer API
  getAccessControlGraph,
  listAccessControlRelationships,
  resolveAccessControl,
  createAccessControlRelationship,
  deleteAccessControlRelationship,
  grantToolAccess,
  checkToolAccess,
  listSkillCollections,

  // Audit Logs API
  listAuditLogs,

  // Billing API
  getBillingOverview,

  // Workspace Import/Export API
  exportWorkspace,
  importWorkspace,

  // Workspace Members & Invitations API
  listWorkspaceMembers,
  removeWorkspaceMember,
  listWorkspaceInvitations,
  createWorkspaceInvitation,
  revokeWorkspaceInvitation,
  acceptWorkspaceInvitation,

  // MCP Instance Tools Discovery
  discoverMCPInstanceTools,
  testMCPInstanceAuth,

  // Skill Bundle API
  listSkillMembers,
  addSkillMember,
  removeSkillMember,
  flattenSkill,

  // Network API
  getNetworkTopology,

  // Global Tasks API
  getTask,

  // Inbox API
  getInbox,

  // Compound MCP API
  listCompoundMCPs,
  getCompoundMCP,
  createCompoundMCP,
  updateCompoundMCP,
  deleteCompoundMCP,
  listCompoundMCPMembers,
  addCompoundMCPMember,
  removeCompoundMCPMember,

  // Project API
  listProjects,
  getProject,
  createProject,
  updateProject,
  deleteProject,

  // Project Association API
  addSkillToProject,
  removeSkillFromProject,
  addAgentToProject,
  removeAgentFromProject,
  addMcpInstanceToProject,
  removeMcpInstanceFromProject,

  // Project Files API
  listProjectFiles,
  uploadProjectFile,
  downloadProjectFile,
  deleteProjectFile,

  // Workspace Files API (read-only)
  listWorkspaceFiles,
  downloadWorkspaceFile,
  workspaceFileHistory,

  // Wallet API
  getAgentWallet,
  createAgentWallet,
  updateAgentWallet,
  deleteAgentWallet,
  getAgentWalletBalance,
  getAgentWalletPayments,
  fundAgentWallet,
} = api;

type TaskEvent = {
  id: string;
  event_type: string;
  timestamp: string;
  data?: { content?: string; result?: string };
};

type SpecWithModels = {
  id: string;
  models: Array<{ id: string }>;
};

type ConfigWithInstances = {
  provider_spec_id: string;
  model_instance_ids: string[];
  [key: string]: unknown;
};

// Convenience helpers built on top of the generated API
export const getAgentTaskMessages = async (agentId: string, taskId: string) => {
  // Build message history from task events
  const { data: events, error } = await getAgentTaskEvents(agentId, taskId, {
    page_size: 100,
  });
  if (error || !events) {
    return { data: [], error };
  }

  const messages = (events as { events: TaskEvent[] }).events
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
export const getAllTasks = api.getAllTasks;

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
  const configs = (configsResponse.data || []) as ConfigWithInstances[];
  const specsWithModels = (providersResponse.data || []) as SpecWithModels[];
  const specsById = Object.fromEntries(
    specsWithModels.map((s) => [s.id, s])
  );
  const configsWithModels = configs.map((config) => ({
    ...config,
    models_list: config.model_instance_ids
      .map((modelSpecId: string) => {
        const providerSpec = specsById[config.provider_spec_id];
        if (!providerSpec) return null;
        return (
          providerSpec.models.find((m) => m.id === modelSpecId) || null
        );
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
export type MCPServerInstance =
  McpServerInstanceResponse;
export type ProviderSpec = ProviderSpecResponse;
export type ProviderSpecWithModels =
  ProviderSpecWithModelsResponse;
export type ProviderConfig = ProviderConfigResponse;
export type ModelSpec =
  AgentareaApiApiV1ModelSpecsModelSpecResponse;
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

// Re-export skill types for convenience
export type {
  Skill,
  SkillContent,
  SkillFile,
  SkillCreateRequest,
  SkillUpdateRequest,
} from "@/types/skill";

export type Project = ProjectResponse;

export type WorkspaceMember = MemberResponse;
export type WorkspaceInvitation = InvitationResponse;
export type WorkspaceInvitationCreated =
  InvitationCreatedResponse;

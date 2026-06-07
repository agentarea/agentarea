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
  sendTaskCommand,
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

  // ReBAC Access Explorer API
  getRebacGraph,
  listRebacTuples,
  resolveRebac,
  createRebacTuple,
  deleteRebacTuple,
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

  return {
    configs: { data: configsWithModels, error: null },
    specs: providersResponse
  };
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

export type Agent = components["schemas"]["AgentResponse"];
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
export type ChatAgent = components["schemas"]["AgentResponse"];
export type ChatResponse = { task_id: string; status: string };
export type ConversationResponse = any;
export type TaskResponse = components["schemas"]["TaskResponse"];
export type AgentCard = components["schemas"]["AgentCard"];
export type TaskWithAgent = TaskResponse & {
  agent_name?: string;
  agent_description?: string | null;
  // Set by the /v1/inbox endpoint for waiting_for_approval tasks so the inbox can
  // approve/reject the pending escalation inline.
  escalation_id?: string | null;
  escalation_tool_name?: string | null;
};

// Re-export skill types for convenience
export type { Skill, SkillContent, SkillFile, SkillCreateRequest, SkillUpdateRequest } from "@/types/skill";

export type Project = components["schemas"]["ProjectResponse"];

export type WorkspaceMember = components["schemas"]["MemberResponse"];
export type WorkspaceInvitation = components["schemas"]["InvitationResponse"];
export type WorkspaceInvitationCreated =
  components["schemas"]["InvitationCreatedResponse"];

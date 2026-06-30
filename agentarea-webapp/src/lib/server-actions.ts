"use server";

import { revalidatePath } from "next/cache";
import type { McpServerCreate, McpServerInstanceCreate, McpServerInstanceUpdate, ModelInstanceBulkCreateRequest, ModelInstanceCreate, ProviderConfigCreate, ProviderConfigUpdate } from "@/api/client/types.gen";
import {
  zProviderConfigCreate,
  zProviderConfigUpdate,
} from "@/api/client/zod.gen";
import { env } from "@/env";
import {
  addAgentToProject,
  addMcpInstanceToProject,
  addSkillMember,
  addSkillToProject,
  bulkCreateModelInstances,
  cancelAgentTask,
  checkMCPServerInstanceConfiguration,
  createAgentWallet,
  createMCPAuthConfig,
  createMCPServer,
  createMCPServerInstance,
  createModelInstance,
  createOpenAPIConnection,
  createProject,
  createProviderConfig,
  createSkill,
  deleteAgentWallet,
  deleteModelInstance,
  deleteOpenAPIConnection,
  deleteProject,
  deleteProjectFile,
  deleteSkill,
  deleteTrigger,
  disableTrigger,
  discoverMCPInstanceTools,
  discoverModels,
  discoverModelsPreview,
  discoverOpenAPITools,
  downloadProjectFile,
  downloadWorkspaceFile,
  enableTrigger,
  exportWorkspace,
  flattenSkill,
  fundAgentWallet,
  getAgent,
  getAgentTaskStatus,
  getTaskPolicySnapshot,
  getAgentWallet,
  getAgentWalletBalance,
  getAgentWalletPayments,
  getAllTasks,
  getMCPHealthStatus,
  getMCPServerInstance,
  getModelSpec,
  getNetworkTopology,
  getOpenAPIConnection,
  getProject,
  getSkill,
  getSkillContent,
  getSkillFile,
  getSkillFiles,
  getTask,
  importWorkspace,
  installAgent,
  installSkill,
  listAgents,
  listAgentTasks,
  listMCPAuthConfigs,
  listMCPServerInstances,
  listMCPServers,
  listModelInstances,
  listModelSpecs,
  listOpenAPIConnections,
  listProjectFiles,
  listProjects,
  listProviderSpecs,
  listProviderSpecsWithModels,
  listSkillMembers,
  listSkills,
  listTriggers,
  listWorkspaceFiles,
  pauseAgentTask,
  previewOpenAPISpec,
  removeAgentFromProject,
  removeMcpInstanceFromProject,
  removeSkillFromProject,
  removeSkillMember,
  resolveEscalation,
  resumeAgentTask,
  sendTaskCommand,
  testModelInstance,
  updateAgent,
  updateAgentWallet,
  updateMCPServerInstance,
  updateOpenAPIConnection,
  updateProject,
  updateProviderConfig,
  updateSkill,
  workspaceFileHistory,
} from "@/lib/api";
import {
  getWorkspaceSettings,
  updateWorkspaceSettings,
} from "@/lib/api-dashboard";
import { getAuthToken } from "@/lib/getAuthToken";

function isUUID(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    value
  );
}

export async function getAgentAction(agentId: string) {
  return await getAgent(agentId);
}

export async function updateAgentAction(
  agentId: string,
  body: Parameters<typeof updateAgent>[1]
) {
  return await updateAgent(agentId, body);
}

export async function installAgentAction(agentId: string) {
  return await installAgent(agentId);
}

export async function listModelInstancesAction(params?: {
  provider_config_id?: string;
  model_spec_id?: string;
  is_active?: boolean;
}) {
  return await listModelInstances(params);
}

export async function getModelSpecAction(modelSpecId: string) {
  return await getModelSpec(modelSpecId);
}

export async function listModelSpecsAction(params?: {
  provider_spec_id?: string;
  is_active?: boolean;
}) {
  return await listModelSpecs(params);
}

export async function testModelInstanceAction(testRequest: {
  provider_config_id: string;
  model_spec_id: string;
  test_message?: string;
}) {
  return await testModelInstance(testRequest);
}

export async function pauseAgentTaskAction(agentId: string, taskId: string) {
  return await pauseAgentTask(agentId, taskId);
}

export async function resumeAgentTaskAction(agentId: string, taskId: string) {
  return await resumeAgentTask(agentId, taskId);
}

export async function sendTaskCommandAction(
  agentId: string,
  taskId: string,
  payload: { command: string; [key: string]: unknown }
) {
  return await sendTaskCommand(agentId, taskId, payload);
}

export async function cancelAgentTaskAction(agentId: string, taskId: string) {
  return await cancelAgentTask(agentId, taskId);
}

export async function getAllTasksAction() {
  return await getAllTasks();
}

export async function getTaskAction(taskId: string) {
  return await getTask(taskId);
}

export async function getAgentTaskStatusAction(
  agentId: string,
  taskId: string
) {
  return await getAgentTaskStatus(agentId, taskId);
}

export async function getTaskPolicySnapshotAction(taskId: string) {
  return await getTaskPolicySnapshot(taskId);
}

export async function createSkillAction(skill: {
  content?: string | null;
  github_url?: string | null;
  name?: string | null;
  description?: string | null;
}) {
  return await createSkill(skill);
}

export async function uploadSkillAction(formData: FormData) {
  const authToken = await getAuthToken();
  const uploadUrl = `${env.API_URL}/v1/skills/upload`;

  const response = await fetch(uploadUrl, {
    method: "POST",
    headers: {
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
    },
    body: formData,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({
      detail: "Upload failed",
    }));
    return { data: null, error: errorData };
  }

  const data = await response.json();
  return { data, error: null };
}

export async function getMCPHealthStatusAction() {
  return await getMCPHealthStatus();
}

export async function checkMCPServerInstanceConfigurationAction(checkRequest: {
  json_spec: Record<string, unknown>;
}) {
  return await checkMCPServerInstanceConfiguration(checkRequest);
}

export async function createMCPServerAction(
  server: McpServerCreate
) {
  return await createMCPServer(server);
}

export async function listSkillsAction(params?: {
  page?: number;
  page_size?: number;
  search?: string;
  source_type?: string;
  network_scope?: string;
  from_registry?: boolean;
  paginated?: boolean;
}) {
  return await listSkills(params);
}

export async function createMCPServerInstanceAction(
  instance: McpServerInstanceCreate
) {
  return await createMCPServerInstance(instance);
}

export async function getMCPServerInstanceAction(instanceId: string) {
  return await getMCPServerInstance(instanceId);
}

export async function updateMCPServerInstanceAction(
  instanceId: string,
  instance: McpServerInstanceUpdate
) {
  return await updateMCPServerInstance(instanceId, instance);
}

export async function listAgentTasksAction(agentId: string) {
  return await listAgentTasks(agentId);
}

export async function listProviderSpecsAction(params?: {
  is_builtin?: boolean;
}) {
  return await listProviderSpecs(params);
}

export async function listProviderSpecsWithModelsAction(params?: {
  is_builtin?: boolean;
}) {
  return await listProviderSpecsWithModels(params);
}

export async function createProviderConfigAction(
  config: ProviderConfigCreate
) {
  const parsed = zProviderConfigCreate.safeParse(config);
  if (!parsed.success) {
    return { data: undefined, error: parsed.error };
  }
  return await createProviderConfig(
    parsed.data as ProviderConfigCreate
  );
}

export async function updateProviderConfigAction(
  configId: string,
  config: ProviderConfigUpdate
) {
  const parsed = zProviderConfigUpdate.safeParse(config);
  if (!parsed.success) {
    return { data: undefined, error: parsed.error };
  }
  return await updateProviderConfig(
    configId,
    parsed.data as ProviderConfigUpdate
  );
}

export async function createModelInstanceAction(
  instance: ModelInstanceCreate
) {
  return await createModelInstance(instance);
}

export async function bulkCreateModelInstancesAction(
  body: ModelInstanceBulkCreateRequest
) {
  return await bulkCreateModelInstances(body);
}

export async function deleteModelInstanceAction(instanceId: string) {
  return await deleteModelInstance(instanceId);
}

export async function discoverModelsAction(configId: string) {
  return await discoverModels(configId);
}

export async function discoverModelsPreviewAction(body: {
  provider_key: string;
  api_key?: string | null;
  endpoint_url?: string | null;
}) {
  return await discoverModelsPreview(body);
}

export async function listAgentsAction() {
  return await listAgents();
}

export async function listMCPAuthConfigsAction() {
  return await listMCPAuthConfigs();
}

export async function createMCPAuthConfigAction(body: {
  name: string;
  description?: string;
  auth_type: string;
  config?: Record<string, unknown>;
  credentials?: Record<string, unknown>;
}) {
  return await createMCPAuthConfig(body);
}

export async function getSkillAction(skillId: string) {
  return await getSkill(skillId);
}

export async function getSkillContentAction(skillId: string) {
  return await getSkillContent(skillId);
}

export async function getSkillFilesAction(skillId: string) {
  return await getSkillFiles(skillId);
}

export async function getSkillFileAction(skillId: string, filePath: string) {
  return await getSkillFile(skillId, filePath);
}

export async function updateSkillAction(
  skillId: string,
  skill: {
    name?: string | null;
    description?: string | null;
    content?: string | null;
  }
) {
  return await updateSkill(skillId, skill);
}

export async function installSkillAction(skillId: string) {
  return await installSkill(skillId);
}

export async function deleteSkillAction(skillId: string) {
  return await deleteSkill(skillId);
}

export async function resolveEscalationAction(
  agentId: string,
  taskId: string,
  escalationId: string,
  approved: boolean,
  comment: string = ""
) {
  return await resolveEscalation(
    agentId,
    taskId,
    escalationId,
    approved,
    comment
  );
}

export async function listSkillMembersAction(skillId: string) {
  return await listSkillMembers(skillId);
}

export async function addSkillMemberAction(
  skillId: string,
  childSkillId: string
) {
  return await addSkillMember(skillId, childSkillId);
}

export async function removeSkillMemberAction(
  skillId: string,
  childSkillId: string
) {
  return await removeSkillMember(skillId, childSkillId);
}

export async function flattenSkillAction(skillId: string) {
  return await flattenSkill(skillId);
}

export async function discoverMCPInstanceToolsAction(instanceId: string) {
  return await discoverMCPInstanceTools(instanceId);
}

export async function getNetworkTopologyAction() {
  return await getNetworkTopology();
}

export async function exportWorkspaceAction() {
  return await exportWorkspace();
}

export async function importWorkspaceAction(body: {
  config: string;
  skip_missing_dependencies?: boolean;
  override_existing?: boolean;
}) {
  return await importWorkspace(body);
}

export async function listTriggersAction(params?: {
  agent_id?: string;
  trigger_type?: string;
  active_only?: boolean;
}) {
  return await listTriggers(params);
}

export async function enableTriggerAction(triggerId: string) {
  return await enableTrigger(triggerId);
}

export async function disableTriggerAction(triggerId: string) {
  return await disableTrigger(triggerId);
}

export async function deleteTriggerAction(triggerId: string) {
  return await deleteTrigger(triggerId);
}

export async function listMCPServersAction(params?: {
  status?: string;
  is_public?: boolean;
  tag?: string;
  page?: number;
  page_size?: number;
  search?: string;
}) {
  return await listMCPServers(params);
}

export async function listOpenAPIConnectionsAction(
  params?: Parameters<typeof listOpenAPIConnections>[0]
) {
  return await listOpenAPIConnections(params);
}

export async function getOpenAPIConnectionAction(connectionId: string) {
  return await getOpenAPIConnection(connectionId);
}

export async function deleteOpenAPIConnectionAction(connectionId: string) {
  return await deleteOpenAPIConnection(connectionId);
}

export async function discoverOpenAPIToolsAction(connectionId: string) {
  return await discoverOpenAPITools(connectionId);
}

export async function createOpenAPIConnectionAction(
  body: Parameters<typeof createOpenAPIConnection>[0]
) {
  const result = await createOpenAPIConnection(body);
  if (!result.error) {
    // Invalidate the list so the new connection is present when the form
    // navigates to /mcp-servers (the client no longer calls router.refresh).
    revalidatePath("/mcp-servers");
  }
  return result;
}

export async function updateOpenAPIConnectionAction(
  connectionId: string,
  body: Parameters<typeof updateOpenAPIConnection>[1]
) {
  return await updateOpenAPIConnection(connectionId, body);
}

export async function listMCPServerInstancesAction() {
  return await listMCPServerInstances();
}

export async function probeInstanceAuthAction(instanceId: string) {
  // Validate UUID to prevent SSRF/path injection in downstream fetch URL
  if (!/^[a-f0-9-]{36}$/i.test(instanceId)) {
    return { data: null, error: "Invalid instance ID" };
  }

  const token = await getAuthToken();
  const base = new URL(env.API_URL);
  base.pathname = `/v1/mcp-server-instances/${encodeURIComponent(instanceId)}/probe`;

  const res = await fetch(base.href, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    const text = await res.text();
    return { data: null, error: text };
  }
  return { data: await res.json(), error: null };
}

export async function oauthAuthorizeAction(instanceId: string) {
  // Validate UUID to prevent SSRF/path injection in downstream fetch URL
  if (!/^[a-f0-9-]{36}$/i.test(instanceId)) {
    return { data: null, error: "Invalid instance ID" };
  }

  const token = await getAuthToken();
  const base = new URL(env.API_URL);
  base.pathname = "/v1/mcp-oauth/authorize";
  base.search = new URLSearchParams({ instance_id: instanceId }).toString();

  const res = await fetch(base.href, {
    method: "GET",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    const text = await res.text();
    return { data: null, error: text };
  }
  return { data: await res.json(), error: null };
}

export async function validateConnectionAction(
  url: string,
  headers: Record<string, string>
) {
  const token = await getAuthToken();
  const res = await fetch(
    `${env.API_URL}/v1/mcp-server-instances/validate-connection`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ url, headers }),
    }
  );
  if (!res.ok) {
    const text = await res.text();
    return { data: null, error: text };
  }
  return { data: await res.json(), error: null };
}

// Project Actions
export async function listProjectsAction() {
  return await listProjects();
}

export async function getProjectAction(projectId: string) {
  return await getProject(projectId);
}

export async function createProjectAction(project: {
  name: string;
  description?: string | null;
  instructions?: string | null;
}) {
  return await createProject(project);
}

export async function updateProjectAction(
  projectId: string,
  project: {
    name?: string | null;
    description?: string | null;
    instructions?: string | null;
  }
) {
  return await updateProject(projectId, project);
}

export async function deleteProjectAction(projectId: string) {
  return await deleteProject(projectId);
}

export async function addSkillToProjectAction(
  projectId: string,
  skillId: string
) {
  return await addSkillToProject(projectId, skillId);
}

export async function removeSkillFromProjectAction(
  projectId: string,
  skillId: string
) {
  return await removeSkillFromProject(projectId, skillId);
}

export async function addAgentToProjectAction(
  projectId: string,
  agentId: string
) {
  return await addAgentToProject(projectId, agentId);
}

export async function removeAgentFromProjectAction(
  projectId: string,
  agentId: string
) {
  return await removeAgentFromProject(projectId, agentId);
}

export async function addMcpInstanceToProjectAction(
  projectId: string,
  mcpInstanceId: string
) {
  return await addMcpInstanceToProject(projectId, mcpInstanceId);
}

export async function removeMcpInstanceFromProjectAction(
  projectId: string,
  mcpInstanceId: string
) {
  return await removeMcpInstanceFromProject(projectId, mcpInstanceId);
}

export async function listProjectFilesAction(projectId: string) {
  return await listProjectFiles(projectId);
}

export async function uploadProjectFileAction(
  projectId: string,
  formData: FormData
) {
  // Validate projectId as UUID to prevent path traversal / SSRF
  if (!/^[a-f0-9-]{36}$/.test(projectId)) {
    return { data: null, error: { detail: "Invalid project ID" } };
  }

  const authToken = await getAuthToken();
  // Build URL safely via URL API — base is a trusted server-only env var
  const base = new URL(env.API_URL);
  base.pathname = `/v1/projects/${encodeURIComponent(projectId)}/files`;

  const response = await fetch(base.href, {
    method: "POST",
    headers: {
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
    },
    body: formData,
  });

  if (!response.ok) {
    const errorData = await response
      .json()
      .catch(() => ({ detail: "Upload failed" }));
    return { data: null, error: errorData };
  }

  const data = await response.json();
  return { data, error: null };
}

export async function downloadProjectFileAction(
  projectId: string,
  filePath: string
) {
  return await downloadProjectFile(projectId, filePath);
}

export async function deleteProjectFileAction(
  projectId: string,
  filePath: string
) {
  return await deleteProjectFile(projectId, filePath);
}

export async function listWorkspaceFilesAction() {
  return await listWorkspaceFiles();
}

export async function downloadWorkspaceFileAction(filePath: string) {
  return await downloadWorkspaceFile(filePath);
}

export async function workspaceFileHistoryAction(filePath: string) {
  return await workspaceFileHistory(filePath);
}

export async function previewOpenAPISpecAction(body: {
  spec_url?: string;
  spec_json?: string;
}) {
  return await previewOpenAPISpec(body);
}

export async function initMCPOAuthConnectAction(
  instanceId: string,
  returnTo: string = ""
) {
  if (!isUUID(instanceId)) {
    return { error: "Invalid instance ID" };
  }
  const { env } = await import("@/env");
  const { getAuthToken } = await import("./getAuthToken");
  const authToken = await getAuthToken();

  const params = new URLSearchParams({ instance_id: instanceId });
  if (returnTo) params.set("return_to", returnTo);
  const base = new URL(env.API_URL);
  base.pathname = "/v1/mcp-oauth/authorize";
  base.search = params.toString();

  const resp = await fetch(base.href, {
    headers: {
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
    },
    redirect: "manual",
  });

  if (!resp.ok) {
    const body = await resp.text();
    return { error: body };
  }

  const data = await resp.json();
  return { authorize_url: data.authorize_url };
}

// Wallet actions
export async function getAgentWalletAction(agentId: string) {
  return await getAgentWallet(agentId);
}

export async function createAgentWalletAction(agentId: string, body: unknown) {
  return await createAgentWallet(agentId, body);
}

export async function updateAgentWalletAction(agentId: string, body: unknown) {
  return await updateAgentWallet(agentId, body);
}

export async function deleteAgentWalletAction(agentId: string) {
  return await deleteAgentWallet(agentId);
}

export async function getAgentWalletBalanceAction(agentId: string) {
  return await getAgentWalletBalance(agentId);
}

export async function getAgentWalletPaymentsAction(
  agentId: string,
  params?: {
    protocol?: string;
    status?: string;
    page?: number;
    page_size?: number;
  }
) {
  return await getAgentWalletPayments(agentId, params);
}

export async function fundAgentWalletAction(agentId: string, body: unknown) {
  return await fundAgentWallet(agentId, body);
}

export async function getWorkspaceSettingsAction() {
  try {
    const data = await getWorkspaceSettings();
    return { data, error: null };
  } catch (err) {
    return {
      data: null,
      error:
        err instanceof Error
          ? err.message
          : "Failed to load workspace settings",
    };
  }
}

export async function updateWorkspaceSettingsAction(
  monthly_cap_usd: number | null
) {
  try {
    const data = await updateWorkspaceSettings(monthly_cap_usd);
    return { data, error: null };
  } catch (err) {
    return {
      data: null,
      error:
        err instanceof Error
          ? err.message
          : "Failed to update workspace settings",
    };
  }
}

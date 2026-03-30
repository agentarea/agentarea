"use server";

import {
  getAgent,
  listAgents,
  listModelInstances,
  getModelSpec,
  listModelSpecs,
  testModelInstance,
  pauseAgentTask,
  resumeAgentTask,
  cancelAgentTask,
  getAllTasks,
  getTask,
  getAgentTaskStatus,
  createSkill,
  getSkill,
  getSkillContent,
  getSkillFiles,
  getSkillFile,
  updateSkill,
  deleteSkill,
  getMCPHealthStatus,
  checkMCPServerInstanceConfiguration,
  createMCPServer,
  listSkills,
  createMCPServerInstance,
  getMCPServerInstance,
  updateMCPServerInstance,
  listAgentTasks,
  listProviderSpecs,
  listProviderSpecsWithModels,
  createProviderConfig,
  updateProviderConfig,
  createModelInstance,
  deleteModelInstance,
  discoverModels,
  discoverModelsPreview,
  listMCPAuthConfigs,
  createMCPAuthConfig,
  resolveEscalation,
  listSkillMembers,
  addSkillMember,
  removeSkillMember,
  flattenSkill,
  discoverMCPInstanceTools,
  getNetworkTopology,
  exportWorkspace,
  importWorkspace,
  enableTrigger,
  disableTrigger,
  deleteTrigger,
  listMCPServers,
  getOpenAPIConnection,
  deleteOpenAPIConnection,
  discoverOpenAPITools,
  testOpenAPIConnection,
  createOpenAPIConnection,
  previewOpenAPISpec,
  listCompoundMCPs,
  getCompoundMCP,
  createCompoundMCP,
  updateCompoundMCP,
  deleteCompoundMCP,
  listCompoundMCPMembers,
  addCompoundMCPMember,
  removeCompoundMCPMember,
  listMCPServerInstances,
  listProjects,
  getProject,
  createProject,
  updateProject,
  deleteProject,
  addSkillToProject,
  removeSkillFromProject,
  addAgentToProject,
  removeAgentFromProject,
  addMcpInstanceToProject,
  removeMcpInstanceFromProject,
  listProjectFiles,
  uploadProjectFile,
  downloadProjectFile,
  deleteProjectFile,
} from "@/lib/api";
import { env } from "@/env";
import { getAuthToken } from "@/lib/getAuthToken";
import type { components } from "@/api/schema";

export async function getAgentAction(agentId: string) {
  return await getAgent(agentId);
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
  json_spec: Record<string, any>;
}) {
  return await checkMCPServerInstanceConfiguration(checkRequest);
}

export async function createMCPServerAction(
  server: components["schemas"]["MCPServerCreate"]
) {
  return await createMCPServer(server);
}

export async function listSkillsAction() {
  return await listSkills();
}

export async function createMCPServerInstanceAction(
  instance: components["schemas"]["MCPServerInstanceCreateRequest"]
) {
  return await createMCPServerInstance(instance);
}

export async function getMCPServerInstanceAction(instanceId: string) {
  return await getMCPServerInstance(instanceId);
}

export async function updateMCPServerInstanceAction(
  instanceId: string,
  instance: components["schemas"]["MCPServerInstanceUpdate"]
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
  config: components["schemas"]["ProviderConfigCreate"]
) {
  return await createProviderConfig(config);
}

export async function updateProviderConfigAction(
  configId: string,
  config: components["schemas"]["ProviderConfigUpdate"]
) {
  return await updateProviderConfig(configId, config);
}

export async function createModelInstanceAction(
  instance: components["schemas"]["ModelInstanceCreate"]
) {
  return await createModelInstance(instance);
}

export async function deleteModelInstanceAction(instanceId: string) {
  return await deleteModelInstance(instanceId);
}

export async function discoverModelsAction(configId: string) {
  return await discoverModels(configId);
}

export async function discoverModelsPreviewAction(body: {
  provider_key: string;
  api_key: string;
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
  config?: Record<string, any>;
  credentials?: Record<string, any>;
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
  skill: { name?: string | null; description?: string | null; content?: string | null }
) {
  return await updateSkill(skillId, skill);
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
  return await resolveEscalation(agentId, taskId, escalationId, approved, comment);
}

export async function listSkillMembersAction(skillId: string) {
  return await listSkillMembers(skillId);
}

export async function addSkillMemberAction(skillId: string, childSkillId: string) {
  return await addSkillMember(skillId, childSkillId);
}

export async function removeSkillMemberAction(skillId: string, childSkillId: string) {
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

export async function getOpenAPIConnectionAction(connectionId: string) {
  return await getOpenAPIConnection(connectionId);
}

export async function deleteOpenAPIConnectionAction(connectionId: string) {
  return await deleteOpenAPIConnection(connectionId);
}

export async function discoverOpenAPIToolsAction(connectionId: string) {
  return await discoverOpenAPITools(connectionId);
}

export async function testOpenAPIConnectionAction(connectionId: string) {
  return await testOpenAPIConnection(connectionId);
}

export async function createOpenAPIConnectionAction(body: Parameters<typeof createOpenAPIConnection>[0]) {
  return await createOpenAPIConnection(body);
}

// Compound MCP Actions
export async function listCompoundMCPsAction() {
  return await listCompoundMCPs();
}

export async function getCompoundMCPAction(compoundId: string) {
  return await getCompoundMCP(compoundId);
}

export async function createCompoundMCPAction(body: Parameters<typeof createCompoundMCP>[0]) {
  return await createCompoundMCP(body);
}

export async function updateCompoundMCPAction(compoundId: string, body: Parameters<typeof updateCompoundMCP>[1]) {
  return await updateCompoundMCP(compoundId, body);
}

export async function deleteCompoundMCPAction(compoundId: string) {
  return await deleteCompoundMCP(compoundId);
}

export async function listCompoundMCPMembersAction(compoundId: string) {
  return await listCompoundMCPMembers(compoundId);
}

export async function addCompoundMCPMemberAction(compoundId: string, body: Parameters<typeof addCompoundMCPMember>[1]) {
  return await addCompoundMCPMember(compoundId, body);
}

export async function removeCompoundMCPMemberAction(compoundId: string, instanceId: string) {
  return await removeCompoundMCPMember(compoundId, instanceId);
}

export async function listMCPServerInstancesAction() {
  return await listMCPServerInstances();
}

export async function startBundleProxyAction(instanceId: string) {
  const token = await getAuthToken();
  const res = await fetch(
    `${env.API_URL}/v1/mcp-server-instances/${instanceId}/start-bundle`,
    {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    }
  );
  if (!res.ok) {
    const text = await res.text();
    return { data: null, error: text };
  }
  return { data: await res.json(), error: null };
}

export async function stopBundleProxyAction(instanceId: string) {
  const token = await getAuthToken();
  const res = await fetch(
    `${env.API_URL}/v1/mcp-server-instances/${instanceId}/stop-bundle`,
    {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
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
  return await createProject(project as any);
}

export async function updateProjectAction(
  projectId: string,
  project: { name?: string | null; description?: string | null; instructions?: string | null }
) {
  return await updateProject(projectId, project as any);
}

export async function deleteProjectAction(projectId: string) {
  return await deleteProject(projectId);
}

export async function addSkillToProjectAction(projectId: string, skillId: string) {
  return await addSkillToProject(projectId, skillId);
}

export async function removeSkillFromProjectAction(projectId: string, skillId: string) {
  return await removeSkillFromProject(projectId, skillId);
}

export async function addAgentToProjectAction(projectId: string, agentId: string) {
  return await addAgentToProject(projectId, agentId);
}

export async function removeAgentFromProjectAction(projectId: string, agentId: string) {
  return await removeAgentFromProject(projectId, agentId);
}

export async function addMcpInstanceToProjectAction(projectId: string, mcpInstanceId: string) {
  return await addMcpInstanceToProject(projectId, mcpInstanceId);
}

export async function removeMcpInstanceFromProjectAction(projectId: string, mcpInstanceId: string) {
  return await removeMcpInstanceFromProject(projectId, mcpInstanceId);
}

export async function listProjectFilesAction(projectId: string) {
  return await listProjectFiles(projectId);
}

export async function uploadProjectFileAction(projectId: string, formData: FormData) {
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
    const errorData = await response.json().catch(() => ({ detail: "Upload failed" }));
    return { data: null, error: errorData };
  }

  const data = await response.json();
  return { data, error: null };
}

export async function downloadProjectFileAction(projectId: string, filePath: string) {
  return await downloadProjectFile(projectId, filePath);
}

export async function deleteProjectFileAction(projectId: string, filePath: string) {
  return await deleteProjectFile(projectId, filePath);
}

export async function previewOpenAPISpecAction(body: {
  spec_url?: string;
  spec_json?: string;
}) {
  return await previewOpenAPISpec(body);
}

export async function initMCPOAuthConnectAction(instanceId: string, returnTo: string = "") {
  const { env } = await import("@/env");
  const { getAuthToken } = await import("./getAuthToken");
  const apiUrl = env.API_URL;
  const authToken = await getAuthToken();

  const params = new URLSearchParams({ instance_id: instanceId });
  if (returnTo) params.set("return_to", returnTo);

  const resp = await fetch(
    `${apiUrl}/v1/mcp-oauth/authorize?${params}`,
    {
      headers: {
        ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      },
      redirect: "manual",
    }
  );

  if (!resp.ok) {
    const body = await resp.text();
    return { error: body };
  }

  const data = await resp.json();
  return { authorize_url: data.authorize_url };
}

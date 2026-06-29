"use server";

import type {
  AgentResponse,
  AnalyzeRequest,
  ImportPreview,
  InstallRequest,
  InstallResult,
  ModelInstanceResponse,
  RegistryItemResponse,
  SkillFileResponse,
} from "@/api/client/types.gen";
import {
  zAgentUpdate,
  zAnalyzeBundleV1BundlesAnalyzePostBody,
  zAnalyzeBundleV1BundlesAnalyzePostResponse,
  zGetAgentV1AgentsAgentIdGetResponse,
  zGetSkillContentV1SkillsSkillIdContentGetResponse,
  zInstallAgentV1AgentsAgentIdInstallPostResponse,
  zInstallBundleV1BundlesInstallPostBody,
  zInstallBundleV1BundlesInstallPostResponse,
  zInstallSkillV1SkillsSkillIdInstallPostResponse,
  zListAgentsV1AgentsGetResponse,
  zListModelInstancesV1ModelInstancesGetResponse,
  zListRegistriesV1RegistriesGetResponse,
  zListRegistryItemsV1RegistriesRegistryIdItemsGetResponse,
  zListSkillFilesV1SkillsSkillIdFilesGetResponse,
  zUpdateAgentV1AgentsAgentIdPatchResponse,
} from "@/api/client/zod.gen";
import {
  analyzeBundle,
  getAgent,
  getSkillContent,
  getSkillFile,
  getSkillFiles,
  installAgent,
  installBundle,
  installSkill,
  listAgents,
  listModelInstances,
  listRegistries,
  listRegistryItems,
  updateAgent,
} from "@/lib/api";
import { z } from "zod";
import { PAGE, TYPE_KEYS, type CatalogType } from "./catalog-data";

export type AgentLite = { id: string; name: string };
export type WorkspaceModel = Pick<
  ModelInstanceResponse,
  "id" | "model_name" | "model_display_name" | "provider_name" | "provider_icon_url"
>;

function errorMessage(error: unknown, fallback: string): string {
  if (!error) return fallback;
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  if (typeof error === "object" && "detail" in error) {
    const detail = (error as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (
      detail &&
      typeof detail === "object" &&
      "message" in detail &&
      typeof (detail as { message?: unknown }).message === "string"
    ) {
      return (detail as { message: string }).message;
    }
    if (Array.isArray(detail)) {
      return detail
        .map((item) =>
          item && typeof item === "object" && "msg" in item
            ? String((item as { msg: unknown }).msg)
            : String(item)
        )
        .join(", ");
    }
  }
  return fallback;
}

function assertCatalogType(type: CatalogType): CatalogType {
  if (!TYPE_KEYS.includes(type)) {
    throw new Error("Invalid catalog type");
  }
  return type;
}

export async function fetchCatalogPageAction(
  type: CatalogType,
  offset: number
): Promise<RegistryItemResponse[]> {
  const registryType = assertCatalogType(type);
  const { data: registriesData, error: registriesError } = await listRegistries({
    registry_type: registryType,
    active_only: true,
  });
  if (registriesError || !registriesData) {
    throw new Error(errorMessage(registriesError, "Failed to load registries"));
  }

  const registries = zListRegistriesV1RegistriesGetResponse.parse(registriesData);
  const lists = await Promise.all(
    registries.map(async (registry) => {
      const { data, error } = await listRegistryItems(registry.id, {
        limit: PAGE,
        offset,
      });
      if (error || !data) {
        throw new Error(errorMessage(error, "Failed to load catalog items"));
      }
      return zListRegistryItemsV1RegistriesRegistryIdItemsGetResponse.parse(data);
    })
  );

  return lists.flat();
}

export async function analyzeBundleAction(
  input: AnalyzeRequest
): Promise<ImportPreview> {
  const body = zAnalyzeBundleV1BundlesAnalyzePostBody.parse(input);
  const { data, error } = await analyzeBundle(body);
  if (error || !data) {
    throw new Error(errorMessage(error, "Analyze failed"));
  }
  return zAnalyzeBundleV1BundlesAnalyzePostResponse.parse(data);
}

export async function installBundleAction(
  input: InstallRequest
): Promise<InstallResult> {
  const body = zInstallBundleV1BundlesInstallPostBody.parse(input);
  const { data, error } = await installBundle(body);
  if (error || !data) {
    throw new Error(errorMessage(error, "Install failed"));
  }
  return zInstallBundleV1BundlesInstallPostResponse.parse(data);
}

export async function installCatalogAgentAction(
  agentId: string
): Promise<AgentResponse> {
  const { data, error } = await installAgent(agentId);
  if (error || !data) {
    throw new Error(errorMessage(error, "Install failed"));
  }
  return zInstallAgentV1AgentsAgentIdInstallPostResponse.parse(data);
}

export async function listWorkspaceAgentsAction(): Promise<AgentLite[]> {
  const { data, error } = await listAgents();
  if (error || !data) {
    throw new Error(errorMessage(error, "Failed to load agents"));
  }
  const agents = zListAgentsV1AgentsGetResponse.parse(data);
  return agents.map((agent) => ({ id: agent.id, name: agent.name }));
}

export async function listActiveModelInstancesAction(): Promise<WorkspaceModel[]> {
  const { data, error } = await listModelInstances({ is_active: true });
  if (error || !data) {
    throw new Error(errorMessage(error, "Failed to load models"));
  }
  return zListModelInstancesV1ModelInstancesGetResponse.parse(data).map((model) => ({
    id: model.id,
    model_name: model.model_name,
    model_display_name: model.model_display_name,
    provider_name: model.provider_name,
    provider_icon_url: model.provider_icon_url,
  }));
}

export async function installCatalogSkillAction(skillId: string): Promise<string> {
  const { data, error } = await installSkill(skillId);
  if (error || !data) {
    throw new Error(errorMessage(error, "Install failed"));
  }
  return zInstallSkillV1SkillsSkillIdInstallPostResponse.parse(data).id;
}

export async function addCatalogSkillToAgentAction(
  skillId: string,
  agentId: string
): Promise<string> {
  const tenantSkillId = await installCatalogSkillAction(skillId);
  const { data: agentData, error: agentError } = await getAgent(agentId);
  if (agentError || !agentData) {
    throw new Error(errorMessage(agentError, "Could not load agent"));
  }

  const agent = zGetAgentV1AgentsAgentIdGetResponse.parse(agentData);
  const currentSkillIds = (agent.skills ?? [])
    .map((skill) => (typeof skill.id === "string" ? skill.id : null))
    .filter((id): id is string => Boolean(id));
  const body = zAgentUpdate.parse({
    skill_ids: Array.from(new Set([...currentSkillIds, tenantSkillId])),
  });
  const { data: updatedData, error: updateError } = await updateAgent(agentId, body);
  if (updateError || !updatedData) {
    throw new Error(errorMessage(updateError, "Could not attach skill"));
  }

  zUpdateAgentV1AgentsAgentIdPatchResponse.parse(updatedData);
  return tenantSkillId;
}

export async function listSkillFilesAction(
  skillId: string
): Promise<SkillFileResponse[]> {
  const { data, error } = await getSkillFiles(skillId);
  if (error || !data) {
    throw new Error(errorMessage(error, "Could not load skill files"));
  }
  return zListSkillFilesV1SkillsSkillIdFilesGetResponse.parse(data).files;
}

export async function getSkillMarkdownAction(skillId: string): Promise<string> {
  const { data, error } = await getSkillContent(skillId);
  if (error || !data) {
    throw new Error(errorMessage(error, "Could not load skill content"));
  }
  return zGetSkillContentV1SkillsSkillIdContentGetResponse.parse(data).content;
}

export async function getSkillFileUrlAction(
  skillId: string,
  path: string
): Promise<string> {
  const { data, error } = await getSkillFile(skillId, path, { redirect: false });
  if (error || !data) {
    throw new Error(errorMessage(error, "Could not load skill file"));
  }
  return z.object({ url: z.string() }).parse(data).url;
}

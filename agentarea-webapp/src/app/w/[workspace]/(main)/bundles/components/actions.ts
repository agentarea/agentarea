"use server";

import { z } from "zod";
import type {
  AgentResponse,
  AnalyzeRequest,
  CatalogConnectionPreflight,
  CatalogConnectionRequest,
  CatalogConnectionResponse,
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
  zBrowseCatalogV1RegistriesCatalogBrowseGetResponse,
  zCatalogConnectionPreflight,
  zCatalogConnectionRequest,
  zCatalogConnectionResponse,
  zGetAgentV1AgentsAgentIdGetResponse,
  zGetCatalogItemV1RegistriesCatalogItemsItemIdGetResponse,
  zGetSkillContentV1SkillsSkillIdContentGetResponse,
  zInstallAgentV1AgentsAgentIdInstallPostResponse,
  zInstallBundleV1BundlesInstallPostBody,
  zInstallBundleV1BundlesInstallPostResponse,
  zInstallSkillV1SkillsSkillIdInstallPostResponse,
  zListAgentsV1AgentsGetResponse,
  zListModelInstancesV1ModelInstancesGetResponse,
  zListSkillFilesV1SkillsSkillIdFilesGetResponse,
  zUpdateAgentV1AgentsAgentIdPatchResponse,
} from "@/api/client/zod.gen";
import {
  analyzeBundle,
  browseCatalog,
  connectCatalogItem,
  getAgent,
  getCatalogItem,
  getSkillContent,
  getSkillFile,
  getSkillFiles,
  installAgent,
  installBundle,
  installSkill,
  listAgents,
  listModelInstances,
  preflightCatalogConnection,
  updateAgent,
} from "@/lib/api";
import {
  PAGE,
  REGISTRY_TYPE,
  TYPE_KEYS,
  type CatalogProtocol,
  type CatalogType,
} from "./catalog-data";

export type AgentLite = { id: string; name: string };
export type WorkspaceModel = Pick<
  ModelInstanceResponse,
  | "id"
  | "model_name"
  | "model_display_name"
  | "provider_name"
  | "provider_icon_url"
  | "is_active"
  | "managed_by"
  | "tags"
>;

// The reusable-secret list lives in @/lib/server-actions, where every Connect
// flow imports it from directly. Re-exporting it through here is illegal in a
// "use server" module — only async function declarations may be exported — and
// it also dragged this whole module into the bundle of anything that wanted
// one function out of it.

export type ActionResult<T> = { data?: T; error?: unknown; status?: number };

/** A response that does not match the contract is a failure, with the path. */
function checked<S extends z.ZodTypeAny>(
  schema: S,
  value: unknown,
  status?: number
): ActionResult<z.infer<S>> {
  const parsed = schema.safeParse(value);
  if (parsed.success) return { data: parsed.data, status };
  return {
    error: {
      detail: parsed.error.issues.map((issue) => ({
        msg: `${issue.path.join(".") || "response"}: ${issue.message}`,
      })),
    },
    status,
  };
}

function assertCatalogType(type: CatalogType): CatalogType {
  if (!TYPE_KEYS.includes(type)) {
    throw new Error("Invalid catalog type");
  }
  return type;
}

export type CatalogPageResult = {
  items: RegistryItemResponse[];
  /** Items matching the filters across the whole catalog, not just this page. */
  total: number;
  categories: { value: string; count: number }[];
  protocols: { value: string; count: number }[];
};

/**
 * One page of a catalog type, filtered/sorted/paged by the server.
 *
 * Only used for infinite-scroll appends -- the first page of every filter
 * combination is server-rendered by the explore page itself.
 */
export async function fetchCatalogPageAction(params: {
  type: CatalogType;
  offset: number;
  q?: string;
  category?: string;
  protocol?: CatalogProtocol;
  sort?: string;
}): Promise<ActionResult<CatalogPageResult>> {
  const { items, total, categories, protocols, error, status } =
    await browseCatalog({
      registryType: REGISTRY_TYPE[assertCatalogType(params.type)],
      q: params.q,
      category: params.category,
      protocol: params.protocol,
      sort: params.sort,
      limit: PAGE,
      offset: params.offset,
    });
  if (error) return { error, status };
  const parsed = checked(
    zBrowseCatalogV1RegistriesCatalogBrowseGetResponse,
    { items, total, categories, protocols },
    status
  );
  if (!parsed.data) return { error: parsed.error, status: parsed.status };
  return {
    data: {
      items: parsed.data.items,
      total: parsed.data.total,
      categories: parsed.data.categories,
      protocols: parsed.data.protocols ?? [],
    },
    status,
  };
}

export async function fetchCatalogItemAction(
  itemId: string
): Promise<ActionResult<RegistryItemResponse>> {
  const { data, error, status } = await getCatalogItem(itemId);
  if (error || !data) return { error, status };
  return checked(
    zGetCatalogItemV1RegistriesCatalogItemsItemIdGetResponse,
    data,
    status
  );
}

export async function catalogConnectionPreflightAction(
  itemId: string
): Promise<ActionResult<CatalogConnectionPreflight>> {
  const { data, error, status } = await preflightCatalogConnection(itemId);
  if (error || !data) return { error, status };
  return checked(zCatalogConnectionPreflight, data, status);
}

export async function connectCatalogConnectionAction(
  itemId: string,
  input: CatalogConnectionRequest
): Promise<ActionResult<CatalogConnectionResponse>> {
  const body = checked(zCatalogConnectionRequest, input);
  if (!body.data) return { error: body.error, status: body.status };
  const { data, error, status } = await connectCatalogItem(itemId, body.data);
  if (error || !data) return { error, status };
  return checked(zCatalogConnectionResponse, data, status);
}

export async function analyzeBundleAction(
  input: AnalyzeRequest
): Promise<ActionResult<ImportPreview>> {
  const body = checked(zAnalyzeBundleV1BundlesAnalyzePostBody, input);
  if (!body.data) return { error: body.error, status: body.status };
  const { data, error, status } = await analyzeBundle(body.data);
  if (error || !data) return { error, status };
  return checked(zAnalyzeBundleV1BundlesAnalyzePostResponse, data, status);
}

export async function installBundleAction(
  input: InstallRequest
): Promise<ActionResult<InstallResult>> {
  const body = checked(zInstallBundleV1BundlesInstallPostBody, input);
  if (!body.data) return { error: body.error, status: body.status };
  const { data, error, status } = await installBundle(body.data);
  if (error || !data) return { error, status };
  return checked(zInstallBundleV1BundlesInstallPostResponse, data, status);
}

export async function installCatalogAgentAction(
  agentId: string
): Promise<ActionResult<AgentResponse>> {
  const { data, error, status } = await installAgent(agentId);
  if (error || !data) return { error, status };
  return checked(zInstallAgentV1AgentsAgentIdInstallPostResponse, data, status);
}

export async function listWorkspaceAgentsAction(): Promise<
  ActionResult<AgentLite[]>
> {
  const { data, error, status } = await listAgents();
  if (error || !data) return { error, status };
  const agents = checked(zListAgentsV1AgentsGetResponse, data, status);
  if (!agents.data) return { error: agents.error, status: agents.status };
  return {
    data: agents.data.map((agent) => ({ id: agent.id, name: agent.name })),
    status,
  };
}

export async function listActiveModelInstancesAction() {
  const result = await listModelInstances({ is_active: true });
  const data: WorkspaceModel[] | undefined = result.data
    ? zListModelInstancesV1ModelInstancesGetResponse
        .parse(result.data)
        .map((model) => ({
          id: model.id,
          model_name: model.model_name,
          model_display_name: model.model_display_name,
          provider_name: model.provider_name,
          provider_icon_url: model.provider_icon_url,
          is_active: model.is_active,
          managed_by: model.managed_by,
          tags: model.tags,
        }))
    : undefined;
  return { data, error: result.error, status: result.status };
}

/** Resolves to the tenant skill id the install created. */
export async function installCatalogSkillAction(
  skillId: string
): Promise<ActionResult<string>> {
  const { data, error, status } = await installSkill(skillId);
  if (error || !data) return { error, status };
  const skill = checked(
    zInstallSkillV1SkillsSkillIdInstallPostResponse,
    data,
    status
  );
  if (!skill.data) return { error: skill.error, status: skill.status };
  return { data: skill.data.id, status };
}

export async function addCatalogSkillToAgentAction(
  skillId: string,
  agentId: string
): Promise<ActionResult<string>> {
  const installed = await installCatalogSkillAction(skillId);
  if (!installed.data)
    return { error: installed.error, status: installed.status };
  const tenantSkillId = installed.data;

  const agentRes = await getAgent(agentId);
  if (agentRes.error || !agentRes.data) {
    return { error: agentRes.error, status: agentRes.status };
  }
  const agent = checked(
    zGetAgentV1AgentsAgentIdGetResponse,
    agentRes.data,
    agentRes.status
  );
  if (!agent.data) return { error: agent.error, status: agent.status };

  const currentSkillIds = (agent.data.skills ?? [])
    .map((skill) => (typeof skill.id === "string" ? skill.id : null))
    .filter((id): id is string => Boolean(id));
  const body = checked(zAgentUpdate, {
    skill_ids: Array.from(new Set([...currentSkillIds, tenantSkillId])),
  });
  if (!body.data) return { error: body.error, status: body.status };
  const updated = await updateAgent(agentId, body.data);
  if (updated.error || !updated.data) {
    return { error: updated.error, status: updated.status };
  }
  const parsed = checked(
    zUpdateAgentV1AgentsAgentIdPatchResponse,
    updated.data,
    updated.status
  );
  if (!parsed.data) return { error: parsed.error, status: parsed.status };
  return { data: tenantSkillId, status: updated.status };
}

export async function listSkillFilesAction(skillId: string) {
  const result = await getSkillFiles(skillId);
  const data: SkillFileResponse[] | undefined = result.data
    ? zListSkillFilesV1SkillsSkillIdFilesGetResponse.parse(result.data).files
    : undefined;
  return { data, error: result.error, status: result.status };
}

export async function getSkillMarkdownAction(skillId: string) {
  const result = await getSkillContent(skillId);
  const data = result.data
    ? zGetSkillContentV1SkillsSkillIdContentGetResponse.parse(result.data)
        .content
    : undefined;
  return { data, error: result.error, status: result.status };
}

export async function getSkillFileUrlAction(skillId: string, path: string) {
  const result = await getSkillFile(skillId, path, { redirect: false });
  const data = result.data
    ? z.object({ url: z.string() }).parse(result.data).url
    : undefined;
  return { data, error: result.error, status: result.status };
}

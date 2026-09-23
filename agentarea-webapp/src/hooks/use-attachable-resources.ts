"use client";

import { useCallback, useEffect, useState } from "react";
import type {
  McpServerResponse,
  SecretResponse,
  SkillResponse,
  WorkspaceFileInfo,
} from "@/api/client/types.gen";
import type { McpInstance, McpServer } from "@/lib/mcp/resolveMcpRef";
import {
  listMCPServerInstancesAction,
  listMCPServersAction,
  listSkillsAction,
  listWorkspaceFilesAction,
  listWorkspaceSecretsAction,
} from "@/lib/server-actions";

/** Which fetch failed, so a picker can report only its own bad news. */
export type AttachableKind = "skills" | "mcps" | "files" | "secrets";

export interface AttachableResources {
  skills: SkillResponse[];
  /** Configured MCP instances — what a task, client or project can attach. */
  mcpInstances: McpInstance[];
  /** Server specs, needed to resolve an instance's display name and icon. */
  mcpServers: McpServer[];
  /** Only populated when asked for; task surfaces attach these too. */
  files: WorkspaceFileInfo[];
  secrets: SecretResponse[];
  loading: boolean;
  failed: AttachableKind[];
  refresh: () => void;
  /** Bumped by `refresh`, for consumers that key their own fetches off it. */
  revision: number;
}

export interface AttachableResourcesOptions {
  /** Opt in so screens that only attach skills and MCP make two calls, not four. */
  withFiles?: boolean;
  withSecrets?: boolean;
}

/** The skills and MCP servers any screen can attach to something.
 *
 * Every attach surface needs the same three lists, and each used to fetch them
 * itself with its own loading flag and error handling — which is how the same
 * picker ended up showing different things in different places. Screens now
 * call this once and hand the result to the pickers.
 */
export function useAttachableResources({
  withFiles = false,
  withSecrets = false,
}: AttachableResourcesOptions = {}): AttachableResources {
  const [skills, setSkills] = useState<SkillResponse[]>([]);
  const [mcpInstances, setMcpInstances] = useState<McpInstance[]>([]);
  const [mcpServers, setMcpServers] = useState<McpServer[]>([]);
  const [files, setFiles] = useState<WorkspaceFileInfo[]>([]);
  const [secrets, setSecrets] = useState<SecretResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState<AttachableKind[]>([]);
  const [revision, setRevision] = useState(0);

  const refresh = useCallback(() => setRevision((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    async function load() {
      const [skillsResult, instancesResult, serversResult, filesResult, secretsResult] =
        await Promise.allSettled([
          listSkillsAction(),
          listMCPServerInstancesAction(),
          listMCPServersAction({ page_size: 100 }),
          withFiles ? listWorkspaceFilesAction() : Promise.resolve(null),
          withSecrets ? listWorkspaceSecretsAction() : Promise.resolve(null),
        ]);
      if (cancelled) return;

      const broke = (result: PromiseSettledResult<{ error?: unknown } | null>) =>
        result.status === "rejected" || Boolean(result.value?.error);

      setSkills(
        skillsResult.status === "fulfilled"
          ? ((skillsResult.value.data as SkillResponse[]) ?? [])
          : []
      );
      setMcpInstances(
        instancesResult.status === "fulfilled"
          ? (instancesResult.value.data ?? [])
          : []
      );
      setMcpServers(
        serversResult.status === "fulfilled"
          ? normalizeServers(serversResult.value.data)
          : []
      );
      setFiles(
        filesResult.status === "fulfilled"
          ? (filesResult.value?.data?.files ?? [])
          : []
      );
      setSecrets(
        secretsResult.status === "fulfilled" && Array.isArray(secretsResult.value)
          ? secretsResult.value.filter((secret) => !secret.owner)
          : []
      );
      setFailed([
        ...(broke(skillsResult) ? (["skills"] as const) : []),
        // The picker lists instances, so only that call failing makes MCP
        // unusable; a missing spec costs an icon, not the entry itself.
        ...(broke(instancesResult) ? (["mcps"] as const) : []),
        ...(withFiles && broke(filesResult) ? (["files"] as const) : []),
        ...(withSecrets && secretsResult.status === "rejected"
          ? (["secrets"] as const)
          : []),
      ]);
      setLoading(false);
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [revision, withFiles, withSecrets]);

  return {
    skills,
    mcpInstances,
    mcpServers,
    files,
    secrets,
    loading,
    failed,
    refresh,
    revision,
  };
}

/** The servers endpoint answers with a bare array or a paginated envelope. */
function normalizeServers(data: unknown): McpServer[] {
  if (Array.isArray(data)) return data as McpServer[];
  const items = (data as { items?: McpServerResponse[] } | undefined)?.items;
  return items ?? [];
}

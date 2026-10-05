"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import type {
  AgentResponse,
  ProjectFileInfo,
  ProjectResponse,
} from "@/api/client";
import type { AttachmentItem } from "@/components/AttachmentSection";
import EmptyState from "@/components/EmptyState";
import { useAttachableResources } from "@/hooks/use-attachable-resources";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { resolveMcpRef } from "@/lib/mcp/resolveMcpRef";
import {
  getProjectAction,
  listAgentsAction,
  listProjectFilesAction,
} from "@/lib/server-actions";
import ProjectOverviewSkeleton from "./components/ProjectOverviewSkeleton";
import ProjectOverviewView from "./components/ProjectOverviewView";

export default function ProjectOverviewPage() {
  const params = useParams();
  const projectId = params.id as string;

  const t = useTranslations("ProjectOverviewPage");
  const tCommon = useTranslations("Common");
  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [allAgents, setAllAgents] = useState<AgentResponse[]>([]);
  const [agentsError, setAgentsError] = useState<string | null>(null);
  const [files, setFiles] = useState<ProjectFileInfo[]>([]);
  const [filesError, setFilesError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const {
    skills: allSkills,
    mcpInstances: allMcpInstances,
    mcpServers,
    loading: resourcesLoading,
  } = useAttachableResources();

  // Refetch after an attachment change: a failure throws so the card shows it.
  const fetchProject = useCallback(async () => {
    const result = await getProjectAction(projectId);
    if (result.error || !result.data) {
      throw new Error(apiErrorMessage(result, t("loadFailed")));
    }
    setProject(result.data);
  }, [projectId, t]);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setLoadError(null);
      setAgentsError(null);
      setFilesError(null);
      try {
        const [projectRes, agentsRes, filesRes] = await Promise.all([
          getProjectAction(projectId),
          listAgentsAction(),
          // Files are one card of the page: their failure stays in that card.
          listProjectFilesAction(projectId).catch((err: unknown) => ({
            data: undefined,
            error: err,
          })),
        ]);
        if (projectRes.error || !projectRes.data) {
          setLoadError(apiErrorMessage(projectRes, t("loadFailed")));
        } else {
          setProject(projectRes.data);
        }
        if (agentsRes.error || !agentsRes.data) {
          setAgentsError(apiErrorMessage(agentsRes, t("agentsLoadFailed")));
        } else {
          setAllAgents(agentsRes.data);
        }
        if (filesRes.error) {
          setFilesError(apiErrorMessage(filesRes, t("filesLoadFailed")));
        } else {
          setFiles(
            (filesRes.data as { files?: ProjectFileInfo[] } | undefined)
              ?.files ?? []
          );
        }
      } catch (err) {
        console.error("Failed to load project", err);
        setLoadError(`${t("loadFailed")}: ${formatApiError(err)}`);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [projectId, t, attempt]);

  if (loading) {
    return <ProjectOverviewSkeleton />;
  }

  if (loadError || !project) {
    return (
      <EmptyState
        title={t("loadFailed")}
        description={loadError ?? undefined}
        action={{
          label: tCommon("retry"),
          onClick: () => setAttempt((n) => n + 1),
        }}
      />
    );
  }

  const instanceIconSrc = (instance: AttachmentItem) => {
    const resolved = resolveMcpRef(instance.id, allMcpInstances, mcpServers);
    return resolved.status === "unresolved" ? undefined : resolved.iconSrc;
  };

  return (
    <ProjectOverviewView
      project={project}
      allAgents={allAgents}
      allSkills={allSkills}
      allMcpInstances={allMcpInstances}
      resourcesLoading={resourcesLoading}
      instanceIconSrc={instanceIconSrc}
      agentsError={agentsError}
      files={files}
      filesError={filesError}
      onRetry={() => setAttempt((n) => n + 1)}
      onChanged={fetchProject}
    />
  );
}

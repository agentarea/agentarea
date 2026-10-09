"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useFileBrowserState } from "@/components/files/file-browser";
import { apiErrorDetail, formatApiError } from "@/lib/api-errors";
import { apiProxyUrl } from "@/lib/api-proxy-url";
import { listTaskArtifactsAction } from "@/lib/server-actions";
import { useTaskContext } from "../TaskContext";
import TaskArtifactsView, { type ArtifactListing } from "./TaskArtifactsView";

export default function TaskArtifactsPage() {
  const t = useTranslations("TaskArtifactsPage");
  const { task, loading: taskLoading, error: taskError } = useTaskContext();
  const [listing, setListing] = useState<ArtifactListing>({ kind: "loading" });
  // Path -> download URL: the browser asks for a file by its path.
  const [downloadUrls, setDownloadUrls] = useState<Map<string, string>>(
    new Map()
  );
  const [refreshing, setRefreshing] = useState(false);
  const [browserState, setBrowserState] = useFileBrowserState(
    `task-artifacts:${task?.id ?? "pending"}`
  );

  const loadArtifacts = useCallback(async () => {
    if (!task) return;
    setRefreshing(true);
    try {
      const result = await listTaskArtifactsAction(task.agent_id, task.id);
      // 404 is a task with nowhere artifacts were ever kept: none published.
      if (result.error && result.status !== 404) {
        setListing({
          kind: "error",
          message: apiErrorDetail(result, t("loadFailed")),
        });
        return;
      }
      const artifacts = result.error ? [] : (result.data ?? []);
      setDownloadUrls(
        new Map(
          artifacts.map((artifact) => [
            artifact.path,
            apiProxyUrl(artifact.download_url),
          ])
        )
      );
      setListing({
        kind: "ready",
        files: artifacts.map((artifact) => ({
          path: artifact.path,
          size: artifact.size,
          content_type: artifact.content_type,
          last_modified: artifact.created_at,
        })),
      });
    } catch (err) {
      setListing({ kind: "error", message: formatApiError(err) });
    } finally {
      setRefreshing(false);
    }
  }, [task, t]);

  useEffect(() => {
    void loadArtifacts();
  }, [loadArtifacts]);

  const fetchUrl = useCallback(
    async (path: string) => ({ data: downloadUrls.get(path) ?? null }),
    [downloadUrls]
  );

  return (
    <TaskArtifactsView
      taskId={task?.id ?? null}
      taskError={taskLoading ? null : (taskError ?? (task ? null : ""))}
      listing={taskLoading ? { kind: "loading" } : listing}
      refreshing={refreshing}
      onRefresh={() => void loadArtifacts()}
      fetchUrl={fetchUrl}
      browserState={browserState}
      onBrowserStateChange={setBrowserState}
    />
  );
}

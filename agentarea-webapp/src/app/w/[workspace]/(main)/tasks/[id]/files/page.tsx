"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useFileBrowserState } from "@/components/files/file-browser";
import { useWorkspaceSlug } from "@/hooks/useWorkspaceNavigation";
import { apiErrorDetail, formatApiError } from "@/lib/api-errors";
import { listTaskSandboxFilesAction } from "@/lib/server-actions";
import { taskSandboxFileUrl } from "@/lib/task-files";
import { useTaskContext } from "../TaskContext";
import TaskFilesView, { type SandboxListing } from "./TaskFilesView";

export default function TaskFilesPage() {
  const t = useTranslations("TaskFilesPage");
  const { task, loading: taskLoading, error: taskError } = useTaskContext();
  const workspaceSlug = useWorkspaceSlug();
  const [listing, setListing] = useState<SandboxListing>({ kind: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  // The task arrives a render later; the strip restores once its key is known.
  const [browserState, setBrowserState] = useFileBrowserState(
    `task:${task?.id ?? "pending"}`
  );

  const loadFiles = useCallback(async () => {
    if (!task) return;
    setRefreshing(true);
    try {
      const result = await listTaskSandboxFilesAction(task.agent_id, task.id);
      if (result.error) {
        // 404 is a task with no sandbox yet, 410 one whose sandbox has
        // expired: both are where a sandbox's life stands, not failures.
        // Every other status is a real error and must say what went wrong.
        setListing(
          result.status === 404
            ? { kind: "missing" }
            : result.status === 410
              ? { kind: "expired" }
              : {
                  kind: "error",
                  message: apiErrorDetail(result, t("loadFailed")),
                }
        );
        return;
      }
      // A sandbox listing carries names only: leaving size and date out keeps
      // the listing honest instead of reporting every file as zero bytes.
      setListing({
        kind: "ready",
        files: (result.data?.items ?? []).map((item) => ({ path: item.path })),
      });
    } catch (err) {
      setListing({ kind: "error", message: formatApiError(err) });
    } finally {
      setRefreshing(false);
    }
  }, [task, t]);

  useEffect(() => {
    void loadFiles();
  }, [loadFiles]);

  const fetchUrl = useCallback(
    async (path: string) => ({
      data: task
        ? taskSandboxFileUrl(task.agent_id, task.id, path, workspaceSlug)
        : null,
    }),
    [task, workspaceSlug]
  );

  return (
    <TaskFilesView
      taskId={task?.id ?? null}
      taskError={taskLoading ? null : (taskError ?? (task ? null : ""))}
      listing={taskLoading ? { kind: "loading" } : listing}
      refreshing={refreshing}
      onRefresh={() => void loadFiles()}
      fetchUrl={fetchUrl}
      browserState={browserState}
      onBrowserStateChange={setBrowserState}
    />
  );
}

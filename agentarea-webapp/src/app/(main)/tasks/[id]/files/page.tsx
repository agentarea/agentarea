"use client";

import { useCallback, useEffect, useState } from "react";
import { Files, RefreshCw } from "lucide-react";
import {
  FileBrowser,
  useFileBrowserState,
  type BrowsedFile,
} from "@/components/files/file-browser";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { apiErrorMessage } from "@/lib/api-errors";
import { listTaskSandboxFilesAction } from "@/lib/server-actions";
import { useTaskContext } from "../TaskContext";

function encodeFilePath(path: string): string {
  return path
    .split("/")
    .filter(Boolean)
    .map((part) => encodeURIComponent(part))
    .join("/");
}

export default function TaskFilesPage() {
  const { task, loading: taskLoading, error: taskError } = useTaskContext();
  const [files, setFiles] = useState<BrowsedFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // The task arrives a render later; the strip restores once its key is known.
  const [browserState, setBrowserState] = useFileBrowserState(
    `task:${task?.id ?? "pending"}`
  );

  const loadFiles = useCallback(async () => {
    if (!task) return;
    setLoading(true);
    setError(null);
    try {
      const result = await listTaskSandboxFilesAction(task.agent_id, task.id);
      if (result.error) {
        setFiles([]);
        // 410 is the expected end of a sandbox's life, not a failure — every
        // other status is a real error and must say what actually went wrong.
        setError(
          result.status === 410
            ? "This sandbox has expired. Published artifacts remain available."
            : apiErrorMessage(result, "Could not load sandbox files")
        );
        return;
      }
      // A sandbox listing carries names only: leaving size and date out keeps
      // the listing honest instead of reporting every file as zero bytes.
      setFiles((result.data?.items ?? []).map((item) => ({ path: item.path })));
    } finally {
      setLoading(false);
    }
  }, [task]);

  useEffect(() => {
    void loadFiles();
  }, [loadFiles]);

  const fetchUrl = useCallback(
    async (path: string) => {
      if (!task) return null;
      return `/api/proxy/v1/agents/${encodeURIComponent(
        task.agent_id
      )}/tasks/${encodeURIComponent(task.id)}/sandbox/files/${encodeFilePath(
        path
      )}`;
    },
    [task]
  );

  if (taskLoading || loading) {
    return (
      <div className="flex h-[calc(100vh-12rem)]" aria-hidden="true">
        <div className="w-[28%] space-y-2 border-r p-3">
          {Array.from({ length: 10 }).map((_, index) => (
            <Skeleton key={index} className="h-4 w-3/4" />
          ))}
        </div>
        <div className="flex-1 p-4">
          <Skeleton className="h-5 w-48" />
        </div>
      </div>
    );
  }

  if (taskError || !task) {
    return (
      <div className="py-12 text-center text-muted-foreground">
        <Files className="mx-auto mb-4 h-16 w-16 opacity-50" />
        <p>{taskError || "Task not found"}</p>
      </div>
    );
  }

  return (
    <FileBrowser
      files={files}
      state={browserState}
      onChange={setBrowserState}
      fetchUrl={fetchUrl}
      error={error}
      onRetry={() => void loadFiles()}
      emptyMessage="No files exist in this live sandbox yet."
      className="h-[calc(100vh-12rem)]"
      title={
        <div>
          <h2 className="text-sm font-medium">Live sandbox files</h2>
          <p className="text-xs text-muted-foreground">
            Ephemeral files are visible only while the task sandbox exists.
          </p>
        </div>
      }
      actions={
        <Button size="xs" variant="outline" onClick={() => void loadFiles()}>
          <RefreshCw className="mr-1.5" />
          Refresh
        </Button>
      }
    />
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";
import { Files, RefreshCw } from "lucide-react";
import { FileBrowser, type BrowsedFile } from "@/components/files/file-browser";
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
      setFiles(
        (result.data?.items ?? []).map((item) => ({
          path: item.path,
          size: 0,
          content_type: null,
          last_modified: null,
        }))
      );
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
    <div className="flex h-[calc(100vh-12rem)] flex-col">
      <div className="flex items-center justify-between border-b px-4 py-2">
        <div>
          <h2 className="text-sm font-medium">Live sandbox files</h2>
          <p className="text-xs text-muted-foreground">
            Ephemeral files are visible only while the task sandbox exists.
          </p>
        </div>
        <Button size="xs" variant="outline" onClick={() => void loadFiles()}>
          <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
          Refresh
        </Button>
      </div>
      {error ? (
        <div className="p-6 text-sm text-muted-foreground">{error}</div>
      ) : (
        <FileBrowser
          files={files}
          fetchUrl={fetchUrl}
          emptyMessage="No files exist in this live sandbox yet."
          className="flex-1"
        />
      )}
    </div>
  );
}

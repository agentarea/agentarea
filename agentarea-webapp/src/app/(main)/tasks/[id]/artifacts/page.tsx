"use client";

import { useCallback, useEffect, useState } from "react";
import { Download, FileText, RefreshCw } from "lucide-react";
import type { TaskArtifactItem } from "@/api/client/types.gen";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { listTaskArtifactsAction } from "@/lib/server-actions";
import { useTaskContext } from "../TaskContext";

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KiB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MiB`;
}

export default function TaskArtifactsPage() {
  const { task, loading: taskLoading, error: taskError } = useTaskContext();
  const [artifacts, setArtifacts] = useState<TaskArtifactItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadArtifacts = useCallback(async () => {
    if (!task) return;
    setLoading(true);
    setError(null);
    try {
      const result = await listTaskArtifactsAction(task.agent_id, task.id);
      if (result.error) {
        setArtifacts([]);
        setError("Artifacts are temporarily unavailable.");
        return;
      }
      setArtifacts(result.data ?? []);
    } finally {
      setLoading(false);
    }
  }, [task]);

  useEffect(() => {
    void loadArtifacts();
  }, [loadArtifacts]);

  if (taskLoading || loading) {
    return (
      <div className="space-y-2 p-4" aria-hidden="true">
        {Array.from({ length: 5 }).map((_, index) => (
          <Skeleton key={index} className="h-16 w-full rounded-lg" />
        ))}
      </div>
    );
  }

  if (taskError || !task) {
    return (
      <div className="py-12 text-center text-muted-foreground">
        <FileText className="mx-auto mb-4 h-16 w-16 opacity-50" />
        <p>{taskError || "Task not found"}</p>
      </div>
    );
  }

  return (
    <div className="main-content">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold">Artifacts</h3>
          <p className="note">
            Durable files explicitly published by the agent from its sandbox.
          </p>
        </div>
        <Button
          size="xs"
          variant="outline"
          onClick={() => void loadArtifacts()}
        >
          <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
          Refresh
        </Button>
      </div>

      {error ? (
        <div className="py-12 text-center text-muted-foreground">{error}</div>
      ) : artifacts.length > 0 ? (
        <div className="space-y-3">
          {artifacts.map((artifact) => (
            <div
              key={artifact.id}
              className="flex items-center justify-between rounded-lg border p-4"
            >
              <div className="flex min-w-0 items-center gap-3">
                <FileText className="h-8 w-8 shrink-0 text-primary" />
                <div className="min-w-0">
                  <p className="truncate font-medium">{artifact.name}</p>
                  <p className="truncate text-sm text-muted-foreground">
                    {artifact.path} · {formatBytes(artifact.size)}
                  </p>
                </div>
              </div>
              <Button variant="outline" size="sm" className="gap-1" asChild>
                <a href={`/api/proxy${artifact.download_url}`}>
                  <Download className="h-4 w-4" />
                  Download
                </a>
              </Button>
            </div>
          ))}
        </div>
      ) : (
        <div className="py-12 text-center">
          <FileText className="mx-auto mb-4 h-16 w-16 text-muted-foreground opacity-50" />
          <h3 className="mb-2 text-lg font-semibold">No artifacts</h3>
          <p className="text-muted-foreground">
            Temporary sandbox files stay in Files. Outputs appear here only
            after the agent publishes them.
          </p>
        </div>
      )}
    </div>
  );
}

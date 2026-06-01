"use client";

import { useCallback, useEffect, useState } from "react";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { FileBrowser, type BrowsedFile } from "@/components/files/file-browser";
import {
  listWorkspaceFilesAction,
  downloadWorkspaceFileAction,
  workspaceFileHistoryAction,
} from "@/lib/server-actions";

export default function WorkspaceFilesPage() {
  const [files, setFiles] = useState<BrowsedFile[]>([]);
  const [directories, setDirectories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const { data } = await listWorkspaceFilesAction();
        setFiles((data as any)?.files || []);
        setDirectories((data as any)?.directories || []);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  const fetchUrl = useCallback(async (path: string) => {
    const { data } = await downloadWorkspaceFileAction(path);
    return (data as any)?.url ?? null;
  }, []);

  const fetchHistory = useCallback(async (path: string) => {
    const { data } = await workspaceFileHistoryAction(path);
    return (data as any)?.events ?? [];
  }, []);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col">
      <div className="border-b px-6 py-3">
        <h1 className="text-lg font-semibold">Files</h1>
        <p className="text-sm text-muted-foreground">
          All files stored in your workspace, including ones produced by agents.
        </p>
      </div>
      <FileBrowser
        files={files}
        directories={directories}
        fetchUrl={fetchUrl}
        fetchHistory={fetchHistory}
        emptyMessage="No files in this workspace yet."
        className="flex-1"
      />
    </div>
  );
}

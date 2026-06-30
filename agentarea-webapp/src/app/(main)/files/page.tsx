"use client";

import { useCallback, useEffect, useState } from "react";
import ContentBlock from "@/components/ContentBlock";
import { FileBrowser, type BrowsedFile } from "@/components/files/file-browser";
import { Skeleton } from "@/components/ui/skeleton";
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
    if (!data?.url) return null;
    try {
      const { pathname } = new URL(data.url);
      return `/api/proxy${pathname}`;
    } catch {
      return null;
    }
  }, []);

  const fetchHistory = useCallback(async (path: string) => {
    const { data } = await workspaceFileHistoryAction(path);
    return (data as any)?.events ?? [];
  }, []);

  return (
    <ContentBlock
      header={{ breadcrumb: [{ label: "Files" }] }}
      className="p-0 overflow-hidden"
    >
      {loading ? (
        <FileBrowserSkeleton />
      ) : (
        <FileBrowser
          files={files}
          directories={directories}
          fetchUrl={fetchUrl}
          fetchHistory={fetchHistory}
          emptyMessage="No files in this workspace yet."
          className="h-full"
        />
      )}
    </ContentBlock>
  );
}

// Mirrors FileBrowser's two-panel layout: a file-tree column + an empty editor.
function FileBrowserSkeleton() {
  return (
    <div className="flex h-full" aria-hidden="true">
      <div className="w-[28%] shrink-0 space-y-1.5 border-r border-border p-3">
        {Array.from({ length: 12 }).map((_, i) => (
          <div
            key={i}
            className="flex items-center gap-2"
            style={{ paddingLeft: `${(i % 3) * 14}px` }}
          >
            <Skeleton className="h-3.5 w-3.5 shrink-0 rounded-sm" />
            <Skeleton className="h-3.5" style={{ width: `${50 + ((i * 13) % 40)}%` }} />
          </div>
        ))}
      </div>
      <div className="flex-1 p-4">
        <Skeleton className="h-5 w-48" />
      </div>
    </div>
  );
}

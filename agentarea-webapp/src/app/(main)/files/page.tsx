"use client";

import { useCallback, useEffect, useState } from "react";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import ContentBlock from "@/components/ContentBlock";
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

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  return (
    <ContentBlock
      header={{ breadcrumb: [{ label: "Files" }] }}
      className="p-0 overflow-hidden"
    >
      <FileBrowser
        files={files}
        directories={directories}
        fetchUrl={fetchUrl}
        fetchHistory={fetchHistory}
        emptyMessage="No files in this workspace yet."
        className="h-full"
      />
    </ContentBlock>
  );
}

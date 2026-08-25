"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Upload, Loader2 } from "lucide-react";
import ContentBlock from "@/components/ContentBlock";
import { Button } from "@/components/ui/button";
import { FileBrowser, type BrowsedFile } from "@/components/files/file-browser";
import type { ArtifactEvent } from "@/components/files/file-viewer";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/use-toast";
import {
  listWorkspaceFilesAction,
  uploadWorkspaceFileAction,
  downloadWorkspaceFileAction,
  workspaceFileHistoryAction,
} from "@/lib/server-actions";

export default function WorkspaceFilesPage() {
  const { toast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<BrowsedFile[]>([]);
  const [directories, setDirectories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);

  const fetchFiles = useCallback(async () => {
    const { data } = await listWorkspaceFilesAction();
    const payload = data as
      | { files?: BrowsedFile[]; directories?: string[] }
      | null;
    setFiles(payload?.files ?? []);
    setDirectories(payload?.directories ?? []);
  }, []);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        await fetchFiles();
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [fetchFiles]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const { error } = await uploadWorkspaceFileAction(formData);
      if (error) {
        toast({
          title: "Upload failed",
          description: (error as { detail?: string })?.detail || "Upload failed",
          variant: "destructive",
        });
        return;
      }
      await fetchFiles();
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

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
    return (data as { events?: ArtifactEvent[] })?.events ?? [];
  }, []);

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: "Files" }],
        controls: (
          <>
            <Button
              size="xs"
              variant="outline"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
            >
              {uploading ? (
                <Loader2 className="mr-1.5 animate-spin" />
              ) : (
                <Upload className="mr-1.5" />
              )}
              Upload File
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              onChange={handleUpload}
            />
          </>
        ),
      }}
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

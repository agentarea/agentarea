"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Upload, FolderUp, Loader2 } from "lucide-react";
import ContentBlock from "@/components/ContentBlock";
import { Button } from "@/components/ui/button";
import { FileBrowser, type BrowsedFile } from "@/components/files/file-browser";
import type { ArtifactEvent } from "@/components/files/file-viewer";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/use-toast";
import {
  listWorkspaceFilesAction,
  uploadWorkspaceFileAction,
  deleteWorkspaceFileAction,
  downloadWorkspaceFileAction,
  workspaceFileHistoryAction,
} from "@/lib/server-actions";

export default function WorkspaceFilesPage() {
  const { toast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
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
    const selected = Array.from(e.target.files ?? []);
    const input = e.target;
    if (selected.length === 0) return;
    setUploading(true);
    try {
      const failed: string[] = [];
      for (const file of selected) {
        const formData = new FormData();
        formData.append("file", file);
        // webkitRelativePath is set for directory picks and carries the folder
        // structure the user chose; a plain file pick lands at the root.
        const relativePath = (file as File & { webkitRelativePath?: string })
          .webkitRelativePath;
        if (relativePath) formData.append("path", relativePath);
        const { error } = await uploadWorkspaceFileAction(formData);
        if (error) failed.push(file.name);
      }
      if (failed.length > 0) {
        toast({
          title: "Upload failed",
          description: `${failed.length} of ${selected.length} files failed: ${failed.join(", ")}`,
          variant: "destructive",
        });
      }
      await fetchFiles();
    } finally {
      setUploading(false);
      input.value = "";
    }
  };

  const handleDelete = async (file: BrowsedFile) => {
    if (
      !window.confirm(
        `Move "${file.path}" to the trash? It stays recoverable through the API.`
      )
    )
      return;
    const { error } = await deleteWorkspaceFileAction(file.path);
    if (error) {
      toast({
        title: "Delete failed",
        description: (error as { detail?: string })?.detail || "Delete failed",
        variant: "destructive",
      });
      return;
    }
    await fetchFiles();
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
              Upload Files
            </Button>
            <Button
              size="xs"
              variant="outline"
              onClick={() => folderInputRef.current?.click()}
              disabled={uploading}
            >
              <FolderUp className="mr-1.5 h-3.5 w-3.5" />
              Upload Folder
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={handleUpload}
            />
            <input
              ref={folderInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={handleUpload}
              {...({
                webkitdirectory: "",
                directory: "",
              } as Record<string, string>)}
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
          onDelete={handleDelete}
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

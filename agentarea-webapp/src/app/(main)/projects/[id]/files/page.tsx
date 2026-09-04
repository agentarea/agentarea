"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { Upload, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/use-toast";
import { FileBrowser, type BrowsedFile } from "@/components/files/file-browser";
import type { ArtifactEvent } from "@/components/files/file-viewer";
import {
  listProjectFilesAction,
  uploadProjectFileAction,
  downloadProjectFileAction,
  workspaceFileHistoryAction,
} from "@/lib/server-actions";

export default function ProjectFilesPage() {
  const params = useParams();
  const projectId = params.id as string;
  const { toast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [files, setFiles] = useState<BrowsedFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);

  const fetchFiles = useCallback(async () => {
    const { data } = await listProjectFilesAction(projectId);
    setFiles((data as { files?: BrowsedFile[] } | undefined)?.files || []);
  }, [projectId]);

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
      const { error } = await uploadProjectFileAction(projectId, formData);
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

  const fetchUrl = useCallback(
    async (path: string) => {
      const { data } = await downloadProjectFileAction(projectId, path);
      const fileData = data as { url?: string } | undefined;
      if (!fileData?.url) return null;
      try {
        const { pathname } = new URL(fileData.url);
        return `/api/proxy${pathname}`;
      } catch {
        return null;
      }
    },
    [projectId]
  );

  const fetchHistory = useCallback(
    async (path: string) => {
      const { data } = await workspaceFileHistoryAction(
        `projects/${projectId}/${path}`
      );
      return (data as { events?: ArtifactEvent[] } | undefined)?.events ?? [];
    },
    [projectId]
  );

  if (loading) {
    return (
      <div className="flex h-[calc(100vh-8rem)] flex-col" aria-hidden="true">
        <div className="flex items-center justify-between border-b px-4 py-2">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-7 w-28 rounded-md" />
        </div>
        <div className="flex-1 space-y-2 p-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="flex items-center gap-2">
              <Skeleton className="h-4 w-4 rounded-sm" />
              <Skeleton
                className="h-4"
                style={{ width: `${40 + ((i * 11) % 40)}%` }}
              />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col">
      <div className="flex items-center justify-between border-b px-4 py-2">
        <h2 className="text-sm font-medium">Files ({files.length})</h2>
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
      </div>

      <FileBrowser
        files={files}
        fetchUrl={fetchUrl}
        fetchHistory={fetchHistory}
        emptyMessage="No files uploaded yet."
        className="flex-1"
      />
    </div>
  );
}

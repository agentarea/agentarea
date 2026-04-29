"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { Upload, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { useToast } from "@/hooks/use-toast";
import { FileBrowser, type BrowsedFile } from "@/components/files/file-browser";
import {
  listProjectFilesAction,
  uploadProjectFileAction,
  downloadProjectFileAction,
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
    setFiles((data as any)?.files || []);
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
          description: (error as any)?.detail || "Upload failed",
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
      return (data as any)?.url ?? null;
    },
    [projectId]
  );

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <LoadingSpinner />
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
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <Upload className="mr-1.5 h-3.5 w-3.5" />
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
        emptyMessage="No files uploaded yet."
        className="flex-1"
      />
    </div>
  );
}

"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { Upload, Trash2, Download, Loader2, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { useToast } from "@/hooks/use-toast";
import {
  listProjectFilesAction,
  uploadProjectFileAction,
  deleteProjectFileAction,
  downloadProjectFileAction,
} from "@/lib/server-actions";

interface FileInfo {
  key: string;
  path: string;
  size: number;
  last_modified: string;
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function ProjectFilesPage() {
  const params = useParams();
  const projectId = params.id as string;
  const { toast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [files, setFiles] = useState<FileInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [deletingKey, setDeletingKey] = useState<string | null>(null);

  const fetchFiles = async () => {
    const { data } = await listProjectFilesAction(projectId);
    setFiles((data as any)?.files || []);
  };

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
  }, [projectId]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);

      const { error } = await uploadProjectFileAction(projectId, formData);
      if (error) {
        toast({ title: "Upload failed", description: (error as any)?.detail || "Upload failed", variant: "destructive" });
        return;
      }
      toast({ title: "File uploaded", variant: "success" });
      await fetchFiles();
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleDelete = async (filePath: string, fileKey: string) => {
    setDeletingKey(fileKey);
    try {
      const { error } = await deleteProjectFileAction(projectId, filePath);
      if (error) {
        toast({ title: "Delete failed", description: (error as any)?.detail || "Delete failed", variant: "destructive" });
        return;
      }
      toast({ title: "File deleted" });
      await fetchFiles();
    } finally {
      setDeletingKey(null);
    }
  };

  const handleDownload = async (filePath: string, fileName: string) => {
    const { data, error } = await downloadProjectFileAction(projectId, filePath);
    if (error || !data) {
      toast({ title: "Download failed", variant: "destructive" });
      return;
    }
    const url = (data as any)?.url;
    if (url) {
      const a = document.createElement("a");
      a.href = url;
      a.download = fileName;
      a.click();
    }
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
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

      {files.length === 0 ? (
        <p className="text-sm text-muted-foreground">No files uploaded yet.</p>
      ) : (
        <ul className="space-y-1">
          {files.map((file) => (
            <li
              key={file.key}
              className="flex items-center justify-between rounded border px-3 py-2 text-sm"
            >
              <div className="flex items-center gap-2 min-w-0">
                <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="truncate">{file.path}</span>
                <span className="text-xs text-muted-foreground shrink-0">
                  {formatBytes(file.size)}
                </span>
              </div>
              <div className="flex items-center gap-1 shrink-0 ml-2">
                <Button
                  size="xs"
                  variant="ghost"
                  onClick={() => handleDownload(file.path, file.path.split("/").pop() || file.path)}
                >
                  <Download className="h-3.5 w-3.5" />
                </Button>
                <Button
                  size="xs"
                  variant="ghost"
                  onClick={() => handleDelete(file.path, file.key)}
                  disabled={deletingKey === file.key}
                >
                  {deletingKey === file.key ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="h-3.5 w-3.5 text-destructive" />
                  )}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

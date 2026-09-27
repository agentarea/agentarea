"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import { Loader2, Upload } from "lucide-react";
import {
  FileBrowser,
  useFileBrowserState,
  type BrowsedFile,
} from "@/components/files/file-browser";
import FormError from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { apiProxyUrl } from "@/lib/api-proxy-url";
import {
  downloadProjectFileAction,
  listProjectFilesAction,
  uploadProjectFileAction,
  workspaceFileHistoryAction,
} from "@/lib/server-actions";

export default function ProjectFilesPage() {
  const params = useParams();
  const projectId = params.id as string;
  const t = useTranslations("ProjectFilesPage");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [files, setFiles] = useState<BrowsedFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [browserState, setBrowserState] = useFileBrowserState(
    `project:${projectId}`
  );

  const fetchFiles = useCallback(async () => {
    setLoadError(null);
    try {
      const result = await listProjectFilesAction(projectId);
      if (result.error) {
        setLoadError(apiErrorMessage(result, t("loadFailed")));
        return;
      }
      setFiles(
        (result.data as { files?: BrowsedFile[] } | undefined)?.files || []
      );
    } catch (err) {
      console.error("Failed to load project files", err);
      setLoadError(`${t("loadFailed")}: ${formatApiError(err)}`);
    }
  }, [projectId, t]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      await fetchFiles();
    } finally {
      setLoading(false);
    }
  }, [fetchFiles]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const result = await uploadProjectFileAction(projectId, formData);
      if (result.error) {
        setUploadError(
          apiErrorMessage(result, t("uploadFailed", { name: file.name }))
        );
        return;
      }
      await fetchFiles();
    } catch (err) {
      console.error("Failed to upload project file", err);
      setUploadError(
        `${t("uploadFailed", { name: file.name })}: ${formatApiError(err)}`
      );
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const fetchUrl = useCallback(
    async (path: string) => {
      const result = await downloadProjectFileAction(projectId, path);
      const fileData = result.data as { url?: string } | undefined;
      return {
        ...result,
        data: fileData?.url ? apiProxyUrl(fileData.url) : null,
      };
    },
    [projectId]
  );

  const fetchHistory = useCallback(
    async (path: string) => {
      const result = await workspaceFileHistoryAction(
        `projects/${projectId}/${path}`
      );
      return { ...result, data: result.data?.events };
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
    <>
      {uploadError && <FormError className="m-4 mb-0">{uploadError}</FormError>}
      <FileBrowser
        files={files}
        state={browserState}
        onChange={setBrowserState}
        fetchUrl={fetchUrl}
        fetchHistory={fetchHistory}
        error={loadError}
        onRetry={() => void load()}
        emptyMessage={t("empty")}
        className="h-[calc(100vh-8rem)]"
        title={
          <h2 className="text-sm font-medium">
            {t("title", { count: files.length })}
          </h2>
        }
        actions={
          <Button
            size="xs"
            variant="outline"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading || Boolean(loadError)}
          >
            {uploading ? (
              <Loader2 className="mr-1.5 animate-spin" />
            ) : (
              <Upload className="mr-1.5" />
            )}
            {t("upload")}
          </Button>
        }
      />
      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        onChange={handleUpload}
      />
    </>
  );
}

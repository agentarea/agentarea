"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { ChevronDown, FolderUp, Upload } from "lucide-react";
import BaseModal from "@/components/BaseModal";
import ContentBlock from "@/components/ContentBlock";
import {
  FileBrowser,
  type FileBrowserState,
} from "@/components/files/file-browser";
import type { BrowsedFile } from "@/components/files/file-tree";
import { useFileTabs } from "@/components/files/use-file-tabs";
import FormError from "@/components/FormError";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { apiProxyUrl } from "@/lib/api-proxy-url";
import type { DroppedFile } from "@/lib/file-drop";
import {
  digestFile,
  MAX_UPLOADS_PER_PLAN,
  putPlanned,
} from "@/lib/presigned-upload";
import {
  createWorkspaceDirectoryAction,
  deleteWorkspaceFileAction,
  downloadWorkspaceFileAction,
  listWorkspaceFilesAction,
  moveWorkspaceFileAction,
  planWorkspaceUploadsAction,
  workspaceFileHistoryAction,
} from "@/lib/server-actions";

export default function WorkspaceFilesPage() {
  const t = useTranslations("FilesPage");
  const router = useWorkspaceRouter();
  const searchParams = useSearchParams();
  const currentFolder = searchParams.get("folder") || "";
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const uploadFolderRef = useRef("");
  const [files, setFiles] = useState<BrowsedFile[]>([]);
  const [directories, setDirectories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [moving, setMoving] = useState(false);
  const [folderDialog, setFolderDialog] = useState(false);
  const [folderName, setFolderName] = useState("");
  const [folderError, setFolderError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<BrowsedFile | null>(null);

  const fetchFiles = useCallback(async () => {
    setLoadError(null);
    try {
      const result = await listWorkspaceFilesAction();
      if (result.error || !result.data) {
        setLoadError(apiErrorMessage(result, t("loadFailed")));
        return;
      }
      setFiles(result.data.files);
      setDirectories(result.data.directories ?? []);
    } catch (err) {
      console.error("Failed to load workspace files", err);
      setLoadError(`${t("loadFailed")}: ${formatApiError(err)}`);
    } finally {
      setLoading(false);
    }
  }, [t]);
  useEffect(() => {
    void fetchFiles();
  }, [fetchFiles]);

  // The folder stays in the URL — it is a place, and the back button should
  // walk it. The open tabs do not: they are remembered per browser instead, so
  // the address bar holds one short link however many files are open.
  const linkedFile = useRef(searchParams.get("file"));
  const [tabs, setTabs] = useFileTabs("workspace", linkedFile.current);
  const browserState: FileBrowserState = { folder: currentFolder, tabs };
  const setBrowserState = useCallback(
    (next: FileBrowserState) => {
      setTabs(next.tabs);
      if (next.folder === currentFolder) return;
      const params = new URLSearchParams(searchParams.toString());
      if (next.folder) params.set("folder", next.folder);
      else params.delete("folder");
      router.push(`/files${params.size ? `?${params}` : ""}`, {
        scroll: false,
      });
    },
    [currentFolder, router, searchParams, setTabs]
  );
  // A link naming a file has done its job once that file is a tab; leaving it
  // in the address bar would reopen it on every later reload.
  useEffect(() => {
    if (!searchParams.has("file")) return;
    const params = new URLSearchParams(searchParams.toString());
    params.delete("file");
    router.replace(`/files${params.size ? `?${params}` : ""}`, {
      scroll: false,
    });
  }, [searchParams, router]);

  const chooseUpload = (folder: boolean) => {
    uploadFolderRef.current = currentFolder;
    (folder ? folderInputRef : fileInputRef).current?.click();
  };
  const openNewFolder = () => {
    setFolderName("");
    setFolderError(null);
    setFolderDialog(true);
  };
  const uploadFiles = useCallback(
    async (selected: DroppedFile[], destination: string) => {
      if (!selected.length) return;
      setUploading(true);
      setActionError(null);
      const failed: string[] = [];
      try {
        const digested: (DroppedFile & { path: string; sha256: string })[] = [];
        for (const { file, relativePath } of selected) {
          try {
            digested.push({
              file,
              relativePath,
              path: [destination, relativePath].filter(Boolean).join("/"),
              sha256: (await digestFile(file)).hex,
            });
          } catch (err) {
            console.error("Failed to read workspace file", err);
            failed.push(`${relativePath} (${formatApiError(err)})`);
          }
        }
        for (
          let start = 0;
          start < digested.length;
          start += MAX_UPLOADS_PER_PLAN
        ) {
          const batch = digested.slice(start, start + MAX_UPLOADS_PER_PLAN);
          try {
            const { data, error } = await planWorkspaceUploadsAction(
              batch.map(({ file, path, sha256 }) => ({
                path,
                sha256,
                content_type: file.type || null,
              }))
            );
            if (error || !data) {
              for (const { relativePath } of batch)
                failed.push(`${relativePath} (${formatApiError(error)})`);
              continue;
            }
            for (const [index, planned] of data.uploads.entries()) {
              const { file, relativePath } = batch[index];
              if (planned.status === "unchanged") continue;
              if (planned.status === "error") {
                failed.push(
                  `${relativePath} (${formatApiError(planned.error)})`
                );
                continue;
              }
              try {
                await putPlanned(planned, file);
              } catch (err) {
                console.error("Failed to upload workspace file", err);
                failed.push(`${relativePath} (${formatApiError(err)})`);
              }
            }
          } catch (err) {
            console.error("Failed to plan workspace uploads", err);
            for (const { relativePath } of batch)
              failed.push(`${relativePath} (${formatApiError(err)})`);
          }
        }
        if (failed.length)
          setActionError(
            `${t("uploadFailed")}: ${t("uploadFailedDescription", {
              count: failed.length,
              total: selected.length,
              names: failed.join(", "),
            })}`
          );
        await fetchFiles();
      } finally {
        setUploading(false);
      }
    },
    [fetchFiles, t]
  );
  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const input = event.target;
    // A folder upload reports each file's path within it; a file upload does not.
    const selected = Array.from(input.files ?? []).map((file) => ({
      file,
      relativePath: file.webkitRelativePath || file.name,
    }));
    try {
      await uploadFiles(selected, uploadFolderRef.current);
    } finally {
      input.value = "";
    }
  };

  const handleMove = useCallback(
    async (source: string, destinationFolder: string) => {
      const name = source.split("/").filter(Boolean).pop() ?? source;
      const destination = [destinationFolder, name].filter(Boolean).join("/");
      if (destination === source) return;
      setMoving(true);
      setActionError(null);
      try {
        const result = await moveWorkspaceFileAction(source, destination);
        if (result.error) {
          setActionError(apiErrorMessage(result, t("moveFailed", { name })));
          return;
        }
        await fetchFiles();
      } catch (err) {
        console.error("Failed to move workspace file", err);
        setActionError(`${t("moveFailed", { name })}: ${formatApiError(err)}`);
      } finally {
        setMoving(false);
      }
    },
    [fetchFiles, t]
  );

  const handleCreateFolder = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const name = folderName.trim();
    if (
      !name ||
      name === "." ||
      name === ".." ||
      /[/\\\x00-\x1f\x7f]/.test(name)
    ) {
      setFolderError(t("invalidFolderName"));
      return;
    }
    const path = [currentFolder, name].filter(Boolean).join("/");
    if (
      files.some(
        (file) => file.path === path || file.path.startsWith(`${path}/`)
      ) ||
      directories.some(
        (directory) =>
          directory.replace(/\/$/, "") === path ||
          directory.startsWith(`${path}/`)
      )
    ) {
      setFolderError(t("folderExists"));
      return;
    }
    setCreating(true);
    setFolderError(null);
    setActionError(null);
    try {
      const result = await createWorkspaceDirectoryAction({ path });
      if (result.error || !result.data) {
        setFolderError(apiErrorMessage(result, t("createFailed")));
        return;
      }
      const created = result.data.path;
      setDirectories((previous) => [...new Set([...previous, created])]);
      setFolderDialog(false);
      setFolderName("");
      await fetchFiles();
    } catch (err) {
      console.error("Failed to create workspace folder", err);
      setFolderError(`${t("createFailed")}: ${formatApiError(err)}`);
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async () => {
    if (!pendingDelete) return;
    setActionError(null);
    try {
      const result = await deleteWorkspaceFileAction(pendingDelete.path);
      if (result.error) {
        setActionError(apiErrorMessage(result, t("deleteFailed")));
        return;
      }
      await fetchFiles();
    } catch (err) {
      console.error("Failed to delete workspace file", err);
      setActionError(`${t("deleteFailed")}: ${formatApiError(err)}`);
    }
  };
  const fetchUrl = useCallback(async (path: string) => {
    const result = await downloadWorkspaceFileAction(path);
    return {
      ...result,
      data: result.data?.url ? apiProxyUrl(result.data.url) : null,
    };
  }, []);
  const fetchHistory = useCallback(async (path: string) => {
    const result = await workspaceFileHistoryAction(path);
    return { ...result, data: result.data?.events };
  }, []);

  return (
    <ContentBlock
      header={{ breadcrumb: [{ label: t("title") }] }}
      className="min-h-0 overflow-hidden p-0"
    >
      {actionError && <FormError className="m-3 mb-0">{actionError}</FormError>}
      <FileBrowser
        files={files}
        directories={directories}
        state={browserState}
        onChange={setBrowserState}
        loading={loading}
        error={loadError}
        onRetry={() => {
          setActionError(null);
          setLoading(true);
          void fetchFiles();
        }}
        onDelete={setPendingDelete}
        fetchUrl={fetchUrl}
        fetchHistory={fetchHistory}
        onUploadFiles={uploadFiles}
        onMove={handleMove}
        onBrowseFiles={() => chooseUpload(false)}
        onBrowseFolder={() => chooseUpload(true)}
        onNewFolder={openNewFolder}
        busy={uploading || moving}
        actions={
          <div className="flex items-center">
            <Button
              size="sm"
              className="rounded-r-none"
              disabled={loading || creating || Boolean(loadError)}
              isLoading={uploading}
              onClick={() => chooseUpload(false)}
            >
              {!uploading && <Upload />}
              {uploading ? t("uploading") : t("uploadFiles")}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  size="sm"
                  className="rounded-l-none border-l border-primary-foreground/25 px-2"
                  disabled={
                    loading || uploading || creating || Boolean(loadError)
                  }
                  aria-label={t("uploadOptions")}
                >
                  <ChevronDown />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => chooseUpload(false)}>
                  <Upload className="mr-2 h-4 w-4" />
                  {t("uploadFiles")}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => chooseUpload(true)}>
                  <FolderUp className="mr-2 h-4 w-4" />
                  {t("uploadFolder")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        }
      />
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        aria-label={t("uploadFiles")}
        onChange={handleUpload}
      />
      <input
        ref={folderInputRef}
        type="file"
        multiple
        className="hidden"
        aria-label={t("uploadFolder")}
        onChange={handleUpload}
        {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
      />
      <BaseModal
        type="delete"
        title={t("deleteFile", { name: pendingDelete?.path ?? "" })}
        description={t("confirmDelete", { name: pendingDelete?.path ?? "" })}
        onConfirm={handleDelete}
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
      />
      <Dialog
        open={folderDialog}
        onOpenChange={(open) => {
          if (!creating) setFolderDialog(open);
        }}
      >
        <DialogContent>
          <form onSubmit={handleCreateFolder} className="space-y-4">
            <DialogHeader>
              <DialogTitle>{t("newFolder")}</DialogTitle>
              <DialogDescription className="break-all">
                {t("createIn", { path: currentFolder || t("allFiles") })}
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-2">
              <Label htmlFor="folder-name">{t("folderName")}</Label>
              <Input
                id="folder-name"
                autoFocus
                autoComplete="off"
                value={folderName}
                disabled={creating}
                onChange={(event) => {
                  setFolderName(event.target.value);
                  setFolderError(null);
                }}
                aria-invalid={Boolean(folderError)}
                aria-describedby={folderError ? "folder-error" : undefined}
              />
              {folderError && (
                <p
                  id="folder-error"
                  role="alert"
                  className="text-sm text-destructive"
                >
                  {folderError}
                </p>
              )}
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={creating}
                onClick={() => setFolderDialog(false)}
              >
                {t("cancel")}
              </Button>
              <Button
                type="submit"
                isLoading={creating}
                disabled={!folderName.trim()}
              >
                {t("createFolder")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </ContentBlock>
  );
}

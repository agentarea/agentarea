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
import ContentBlock from "@/components/ContentBlock";
import {
  FileBrowser,
  type FileBrowserState,
} from "@/components/files/file-browser";
import type { BrowsedFile } from "@/components/files/file-tree";
import { useFileTabs } from "@/components/files/use-file-tabs";
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
import { useToast } from "@/hooks/use-toast";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { apiProxyUrl } from "@/lib/api-proxy-url";
import type { DroppedFile } from "@/lib/file-drop";
import {
  createWorkspaceDirectoryAction,
  deleteWorkspaceFileAction,
  downloadWorkspaceFileAction,
  listWorkspaceFilesAction,
  moveWorkspaceFileAction,
  uploadWorkspaceFileAction,
  workspaceFileHistoryAction,
} from "@/lib/server-actions";

export default function WorkspaceFilesPage() {
  const t = useTranslations("FilesPage");
  const { toast } = useToast();
  const router = useWorkspaceRouter();
  const searchParams = useSearchParams();
  const currentFolder = searchParams.get("folder") || "";
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const uploadFolderRef = useRef("");
  const [files, setFiles] = useState<BrowsedFile[]>([]);
  const [directories, setDirectories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [moving, setMoving] = useState(false);
  const [folderDialog, setFolderDialog] = useState(false);
  const [folderName, setFolderName] = useState("");
  const [folderError, setFolderError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const fetchFiles = useCallback(async () => {
    setLoadError(false);
    try {
      const { data, error } = await listWorkspaceFilesAction();
      if (error || !data) throw new Error("Files unavailable");
      setFiles(data.files);
      setDirectories(data.directories ?? []);
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, []);
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
      const failed: string[] = [];
      try {
        for (const { file, relativePath } of selected) {
          try {
            const formData = new FormData();
            formData.append("file", file);
            formData.append(
              "path",
              [destination, relativePath].filter(Boolean).join("/")
            );
            const { error } = await uploadWorkspaceFileAction(formData);
            if (error) failed.push(relativePath);
          } catch {
            failed.push(relativePath);
          }
        }
        if (failed.length)
          toast({
            title: t("uploadFailed"),
            description: t("uploadFailedDescription", {
              count: failed.length,
              total: selected.length,
              names: failed.join(", "),
            }),
            variant: "destructive",
          });
        await fetchFiles();
      } finally {
        setUploading(false);
      }
    },
    [fetchFiles, t, toast]
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
      try {
        const { error } = await moveWorkspaceFileAction(source, destination);
        if (error) {
          toast({ title: t("moveFailed", { name }), variant: "destructive" });
          return;
        }
        await fetchFiles();
      } finally {
        setMoving(false);
      }
    },
    [fetchFiles, t, toast]
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
    try {
      const { data, error } = await createWorkspaceDirectoryAction({ path });
      if (error || !data) {
        setFolderError(t("createFailed"));
        return;
      }
      setDirectories((previous) => [...new Set([...previous, data.path])]);
      setFolderDialog(false);
      setFolderName("");
      await fetchFiles();
    } catch {
      setFolderError(t("createFailed"));
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (file: BrowsedFile) => {
    if (!window.confirm(t("confirmDelete", { name: file.path }))) return;
    try {
      const { error } = await deleteWorkspaceFileAction(file.path);
      if (error) throw new Error("Delete failed");
      await fetchFiles();
    } catch {
      toast({ title: t("deleteFailed"), variant: "destructive" });
    }
  };
  const fetchUrl = useCallback(async (path: string) => {
    const { data } = await downloadWorkspaceFileAction(path);
    if (!data?.url) return null;
    return apiProxyUrl(data.url);
  }, []);
  const fetchHistory = useCallback(async (path: string) => {
    const { data } = await workspaceFileHistoryAction(path);
    return data?.events ?? [];
  }, []);

  return (
    <ContentBlock
      header={{ breadcrumb: [{ label: t("title") }] }}
      className="min-h-0 overflow-hidden p-0"
    >
      <FileBrowser
        files={files}
        directories={directories}
        state={browserState}
        onChange={setBrowserState}
        loading={loading}
        error={loadError ? t("loadFailed") : null}
        onRetry={() => {
          setLoading(true);
          void fetchFiles();
        }}
        onDelete={handleDelete}
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
              disabled={loading || creating || loadError}
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
                  disabled={loading || uploading || creating || loadError}
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

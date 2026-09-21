"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useTranslations } from "next-intl";
import {
  FolderOpen,
  FolderPlus,
  FolderTree,
  FolderUp,
  Upload,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { type DroppedFile } from "@/lib/file-drop";
import { cn } from "@/lib/utils";
import { FileTabStrip } from "./file-tabs";
import {
  buildTree,
  FileTree,
  sortedChildren,
  type BrowsedFile,
  type TreeNode,
} from "./file-tree";
import {
  FileViewerContent,
  type FetchHistoryFn,
  type FetchUrlFn,
} from "./file-viewer";
import { FolderTable } from "./folder-table";
import {
  closeTab,
  FOLDER_TAB,
  openTab,
  pruneTabs,
  showFolder,
  type TabState,
} from "./tab-state";
import { useFileTabs } from "./use-file-tabs";
import { useFolderDnd } from "./use-folder-dnd";

/** Where the browser is: the folder on screen and the open tabs.
 *
 * One value rather than two so a page storing it in the URL writes a single
 * entry per change — navigating into a folder also brings its listing forward,
 * and two separate writes in one tick would clobber each other. */
export interface FileBrowserState {
  /** The folder on screen; "" is the root. */
  folder: string;
  tabs: TabState;
}

export const initialBrowserState: FileBrowserState = {
  folder: "",
  tabs: { open: [], active: null },
};

/** Browse a set of files: a tree to navigate, then the folder and any open
 * files as tabs.
 *
 * One component serves the workspace, a project and a live task sandbox, so a
 * file looks and behaves the same wherever it is opened. Every write handler
 * is optional — a read-only surface simply omits it, and the matching
 * affordance disappears with it. */
export function FileBrowser({
  files,
  directories = [],
  state,
  onChange,
  fetchUrl,
  fetchHistory,
  loading = false,
  error = null,
  onRetry,
  busy,
  title,
  actions,
  emptyMessage,
  onDelete,
  onUploadFiles,
  onMove,
  onNewFolder,
  onBrowseFiles,
  onBrowseFolder,
  className,
}: {
  files: BrowsedFile[];
  directories?: string[];
  state: FileBrowserState;
  onChange: (state: FileBrowserState) => void;
  fetchUrl: FetchUrlFn;
  fetchHistory?: FetchHistoryFn;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  /** Dims nothing, but tells assistive tech an upload or move is in flight. */
  busy?: boolean;
  /** Left side of the header row; omit for no header. */
  title?: ReactNode;
  /** Right side of the header row. */
  actions?: ReactNode;
  /** Replaces the stock description when the browser holds no files at all. */
  emptyMessage?: string;
  onDelete?: (file: BrowsedFile) => void;
  onUploadFiles?: (files: DroppedFile[], destination: string) => void;
  onMove?: (source: string, destination: string) => void;
  onNewFolder?: () => void;
  onBrowseFiles?: () => void;
  onBrowseFolder?: () => void;
  className?: string;
}) {
  const t = useTranslations("FilesPage");
  const [search, setSearch] = useState("");
  const [showTree, setShowTree] = useState(false);
  // Where the last right-click landed, or null when no menu is open. Radix has
  // no context-menu primitive installed here, so the dropdown is anchored to a
  // zero-size element parked at those coordinates — which keeps its focus
  // trapping and keyboard navigation without pulling in another package.
  const [menuAt, setMenuAt] = useState<{ x: number; y: number } | null>(null);
  const { folder, tabs } = state;
  const setTabs = (next: TabState) => onChange({ folder, tabs: next });
  const dnd = useFolderDnd({ folder, onUploadFiles, onMove });

  const root = useMemo(
    () => buildTree(files, directories),
    [files, directories]
  );
  const current = folder
    .split("/")
    .filter(Boolean)
    .reduce<TreeNode | undefined>(
      (node, part) => node?.children.get(part),
      root
    );
  const entries = (current ? sortedChildren(current) : [])
    .filter((node) =>
      node.name.toLocaleLowerCase().includes(search.toLocaleLowerCase())
    )
    .map((node) => ({ ...node, id: node.path }));
  const folderName = folder.split("/").filter(Boolean).at(-1) || t("allFiles");
  const canCreate = Boolean(onNewFolder);
  // An empty writable folder turns its whole area into the upload affordance.
  // It then owns the drag feedback, so the pane-wide overlay stands down
  // rather than drawing a second dashed rectangle on top of it.
  const showUploadZone =
    !loading && !error && !entries.length && !search && Boolean(onBrowseFiles);

  // A tab whose file has been deleted or moved away must not linger pointing
  // at nothing. Skipped while the listing is unavailable, when every path
  // would look missing.
  useEffect(() => {
    if (loading || error) return;
    const next = pruneTabs(
      state.tabs,
      files.map((file) => file.path)
    );
    if (next !== state.tabs) onChange({ ...state, tabs: next });
  }, [files, loading, error, state, onChange]);

  const navigate = (path: string) => {
    setSearch("");
    setShowTree(false);
    // Stepping into a folder is a request to see it, so the listing comes
    // forward; whatever was open stays open behind it.
    onChange({ folder: path, tabs: showFolder(tabs) });
  };
  const open = (path: string) => setTabs(openTab(tabs, path));

  return (
    <div
      className={cn("flex h-full min-h-0 min-w-0 flex-col bg-background", className)}
      aria-label={t("fileManager")}
    >
      {(title || actions) && (
        <div className="flex shrink-0 items-center justify-between gap-3 border-b px-4 py-2">
          {title}
          {actions}
        </div>
      )}
      <ResizablePanelGroup
        direction="horizontal"
        className="min-h-0 min-w-0 flex-1"
      >
        <ResizablePanel
          id="files-tree"
          order={1}
          defaultSize={22}
          minSize={12}
          maxSize={40}
          className={cn("bg-muted/20", showTree ? "block" : "hidden md:block")}
        >
          <aside
            aria-label={t("fileTree")}
            className="h-full overflow-auto p-2"
          >
            <div className="flex items-center justify-between gap-1 pb-1 pl-2 pr-1 pt-1">
              <span className="text-xs text-muted-foreground">
                {t("workspace")}
              </span>
              {canCreate && (
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-6 w-6 text-muted-foreground"
                        aria-label={t("newFolder")}
                        onClick={onNewFolder}
                      >
                        <FolderPlus className="h-4 w-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side="right">
                      {t("newFolder")}
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              )}
            </div>
            <button
              type="button"
              onClick={() => navigate("")}
              aria-current={!folder ? "location" : undefined}
              {...dnd.folderTarget("")}
              className={cn(
                "flex w-full items-center gap-2 rounded px-2 py-2 text-left text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring",
                !folder
                  ? "bg-primary/10 font-medium text-primary"
                  : "hover:bg-muted",
                dnd.hoveredFolder === "" && "outline outline-2 outline-primary"
              )}
            >
              <FolderOpen className="h-4 w-4 shrink-0" />
              {t("allFiles")}
            </button>
            <FileTree
              files={files}
              directories={directories}
              selectedPath={tabs.active}
              onSelect={(file) => open(file.path)}
              selectedFolder={folder}
              onSelectFolder={navigate}
              nodeProps={dnd.entryProps}
              className="border-0"
            />
          </aside>
        </ResizablePanel>
        <ResizableHandle
          withHandle
          className={cn(showTree ? "flex" : "hidden md:flex")}
        />
        <ResizablePanel
          id="files-content"
          order={2}
          minSize={30}
          className="flex min-h-0 min-w-0 flex-col"
        >
          <Tabs
            value={tabs.active ?? FOLDER_TAB}
            onValueChange={(value) =>
              setTabs(
                value === FOLDER_TAB ? showFolder(tabs) : openTab(tabs, value)
              )
            }
            className="flex min-h-0 flex-1 flex-col"
          >
            <div className="flex shrink-0 items-stretch border-b bg-muted/30">
              <Button
                size="icon"
                variant="ghost"
                className="h-9 w-9 shrink-0 rounded-none border-r md:hidden"
                aria-label={t("toggleTree")}
                aria-expanded={showTree}
                onClick={() => setShowTree(!showTree)}
              >
                <FolderTree />
              </Button>
              <FileTabStrip
                folderLabel={folderName}
                open={tabs.open}
                active={tabs.active}
                onClose={(path) => setTabs(closeTab(tabs, path))}
              />
            </div>
            <TabsContent
              value={FOLDER_TAB}
              forceMount
              className={cn(
                "mt-0 min-h-0 focus-visible:ring-0",
                tabs.active === null ? "flex flex-1 flex-col" : "hidden"
              )}
            >
              <section
                {...dnd.paneProps}
                onDragOver={(event) => {
                  dnd.paneProps.onDragOver(event);
                  // A folder target stops the event before it gets here, so
                  // reaching this point means the cursor is over open space.
                  dnd.clearHover();
                }}
                onContextMenu={(event) => {
                  if (!canCreate) return;
                  event.preventDefault();
                  setMenuAt({ x: event.clientX, y: event.clientY });
                }}
                className="relative min-h-0 flex-1 overflow-auto p-4"
                aria-label={t("folderContents")}
                aria-busy={loading || busy}
              >
                {dnd.isDragging &&
                  dnd.hoveredFolder === null &&
                  !showUploadZone && (
                    <div className="pointer-events-none absolute inset-2 z-10 flex items-center justify-center rounded border-2 border-dashed border-primary bg-primary/5">
                      <p className="rounded bg-background px-3 py-1.5 text-sm font-medium">
                        {t("dropToUpload", { path: folderName })}
                      </p>
                    </div>
                  )}
                {error ? (
                  <div
                    role="alert"
                    className="flex flex-wrap items-center gap-3 rounded border border-destructive/30 p-4 text-sm"
                  >
                    <span>{error}</span>
                    {onRetry && (
                      <Button variant="outline" size="sm" onClick={onRetry}>
                        {t("retry")}
                      </Button>
                    )}
                  </div>
                ) : (
                  <FolderTable
                    entries={entries}
                    search={search}
                    onSearchChange={setSearch}
                    onOpen={(entry) =>
                      entry.file ? open(entry.file.path) : navigate(entry.path)
                    }
                    onDelete={onDelete}
                    entryProps={dnd.entryProps}
                    loading={loading}
                    onBrowseFiles={onBrowseFiles}
                    showUploadZone={showUploadZone}
                    isDragging={dnd.isDragging}
                    emptyMessage={folder ? undefined : emptyMessage}
                  />
                )}
              </section>
            </TabsContent>
            {/* No forceMount here, unlike the folder above: Radix drops the
                inactive ones, so a session with many tabs open holds one
                viewer and one file in memory rather than all of them. The
                cost is re-reading a file when its tab comes back. */}
            {tabs.open.map((path) => {
              const file = files.find((item) => item.path === path);
              return (
                <TabsContent
                  key={path}
                  value={path}
                  // The display class has to be conditional. Radix keeps an
                  // empty div for a tab it has shown before and marks it with
                  // the `hidden` attribute, but a `flex` class outranks
                  // `[hidden]` in Tailwind's cascade — a constant `flex` here
                  // leaves those empty panels visible, and `flex-1` then hands
                  // each of them an equal share of the height.
                  className={cn(
                    "mt-0 min-h-0 overflow-hidden focus-visible:ring-0",
                    path === tabs.active ? "flex flex-1" : "hidden"
                  )}
                >
                  {file && (
                    <FileViewerContent
                      file={file}
                      fetchUrl={fetchUrl}
                      fetchHistory={fetchHistory}
                      onDelete={onDelete}
                      onClose={() => setTabs(closeTab(tabs, path))}
                    />
                  )}
                </TabsContent>
              );
            })}
          </Tabs>
        </ResizablePanel>
      </ResizablePanelGroup>
      <DropdownMenu
        open={menuAt !== null}
        onOpenChange={(isOpen) => {
          if (!isOpen) setMenuAt(null);
        }}
      >
        <DropdownMenuTrigger
          aria-hidden="true"
          tabIndex={-1}
          className="fixed h-0 w-0"
          style={{ left: menuAt?.x ?? 0, top: menuAt?.y ?? 0 }}
        />
        <DropdownMenuContent align="start" className="w-48">
          <DropdownMenuItem onSelect={() => onNewFolder?.()}>
            <FolderPlus className="mr-2 h-4 w-4" />
            {t("newFolder")}
          </DropdownMenuItem>
          {onBrowseFiles && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => onBrowseFiles()}>
                <Upload className="mr-2 h-4 w-4" />
                {t("uploadFiles")}
              </DropdownMenuItem>
            </>
          )}
          {onBrowseFolder && (
            <DropdownMenuItem onSelect={() => onBrowseFolder()}>
              <FolderUp className="mr-2 h-4 w-4" />
              {t("uploadFolder")}
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

/** Hold the browser's position: the folder for this visit, the tabs for good.
 *
 * `surface` separates one set of tabs from another — a project's from another
 * project's, and both from the workspace. A page that also wants the folder in
 * its URL builds the same shape from search params instead. */
export function useFileBrowserState(
  surface: string
): [FileBrowserState, (next: FileBrowserState) => void] {
  const [folder, setFolder] = useState("");
  const [tabs, setTabs] = useFileTabs(surface);
  const state = useMemo(() => ({ folder, tabs }), [folder, tabs]);
  const update = useCallback(
    (next: FileBrowserState) => {
      setFolder(next.folder);
      setTabs(next.tabs);
    },
    [setTabs]
  );
  return [state, update];
}

export type { BrowsedFile, FetchUrlFn, FetchHistoryFn };

"use client";

import { useState } from "react";
import {
  ChevronRight,
  FileText,
  Folder,
  FolderOpen,
  Trash2,
} from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

/** A file to browse. Wider than the workspace listing it usually comes from:
 * a live sandbox reports names only, so everything but the path may be absent
 * and the listing shows a dash rather than inventing a zero-byte file. */
export interface BrowsedFile {
  path: string;
  size?: number | null;
  content_type?: string | null;
  last_modified?: string | null;
}

export interface TreeNode {
  name: string;
  path: string;
  isFile: boolean;
  file?: BrowsedFile;
  children: Map<string, TreeNode>;
}

/** Extra attributes for a rendered node, e.g. to make it a drop target.
 * The tree only spreads what it is given; it knows nothing about dragging. */
export type NodeProps = (node: TreeNode) => React.HTMLAttributes<HTMLElement>;

export function buildTree(
  files: BrowsedFile[],
  directories: string[] = []
): TreeNode {
  const root: TreeNode = {
    name: "",
    path: "",
    isFile: false,
    children: new Map(),
  };
  for (const file of files) {
    const parts = file.path.split("/").filter(Boolean);
    let node = root;
    parts.forEach((part, idx) => {
      const isLeaf = idx === parts.length - 1;
      let child = node.children.get(part);
      if (!child) {
        child = {
          name: part,
          path: parts.slice(0, idx + 1).join("/"),
          isFile: isLeaf,
          children: new Map(),
        };
        node.children.set(part, child);
      }
      if (isLeaf) {
        child.isFile = true;
        child.file = file;
      }
      node = child;
    });
  }
  // Synthesize folder nodes for empty directories (e.g. fresh projects with
  // no files yet). buildTree's normal path only creates folders implied by
  // file paths.
  for (const dir of directories) {
    const parts = dir.split("/").filter(Boolean);
    let node = root;
    parts.forEach((part, idx) => {
      let child = node.children.get(part);
      if (!child) {
        child = {
          name: part,
          path: parts.slice(0, idx + 1).join("/"),
          isFile: false,
          children: new Map(),
        };
        node.children.set(part, child);
      }
      node = child;
    });
  }
  return root;
}

export function sortedChildren(node: TreeNode): TreeNode[] {
  return Array.from(node.children.values()).sort((a, b) => {
    if (a.isFile !== b.isFile) return a.isFile ? 1 : -1;
    return a.name.localeCompare(b.name);
  });
}

/** Opt-in modes a picker passes down the tree; the file browser sets neither. */
type PickProps = {
  /** Picked paths: files get a checkbox and a click toggles them. */
  checkedPaths?: string[];
  /** Open every folder, e.g. while a search narrows the files. */
  expandAll?: boolean;
  /** With `checkedPaths`: folders get a checkbox that picks every file under them. */
  onCheckFolder?: (paths: string[], checked: boolean) => void;
};

/** Every file path under a folder, however deep. */
function filesUnder(node: TreeNode): string[] {
  return Array.from(node.children.values()).flatMap((child) =>
    child.isFile ? [child.path] : filesUnder(child)
  );
}

function FileRow({
  node,
  depth,
  onSelect,
  selectedPath,
  onDelete,
  nodeProps,
  checkedPaths,
}: {
  node: TreeNode;
  depth: number;
  onSelect: (file: BrowsedFile) => void;
  selectedPath: string | null;
  onDelete?: (file: BrowsedFile) => void;
  nodeProps?: NodeProps;
} & PickProps) {
  const file = node.file;
  if (!file) return null;
  const isSelected = selectedPath === file.path;
  const checked = checkedPaths?.includes(file.path);
  const { className: extraClassName, ...extra } = nodeProps?.(node) ?? {};
  return (
    <div
      {...extra}
      className={cn(
        "group flex w-full items-center rounded transition-colors hover:bg-muted",
        isSelected && "bg-muted",
        extraClassName
      )}
    >
      <button
        type="button"
        onClick={() => onSelect(file)}
        aria-pressed={checked}
        className="flex min-w-0 flex-1 items-center gap-2 px-2 py-1 text-left text-sm"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate">{node.name}</span>
      </button>
      {checked !== undefined && (
        // Beside the row's button, not in it: a checkbox is a button too. The
        // row stays the control for the keyboard; the box mirrors it.
        <Checkbox
          checked={checked}
          onCheckedChange={() => onSelect(file)}
          tabIndex={-1}
          aria-hidden
          className="mr-2 shrink-0"
        />
      )}
      {onDelete && (
        <button
          type="button"
          onClick={() => onDelete(file)}
          aria-label={`Delete ${node.name}`}
          className="mr-1 hidden shrink-0 rounded p-1 text-muted-foreground hover:text-destructive group-hover:block focus-visible:block"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}

function FolderRow({
  node,
  depth,
  onSelect,
  selectedPath,
  onDelete,
  onSelectFolder,
  selectedFolder,
  nodeProps,
  checkedPaths,
  expandAll,
  onCheckFolder,
}: {
  node: TreeNode;
  depth: number;
  onSelect: (file: BrowsedFile) => void;
  selectedPath: string | null;
  onDelete?: (file: BrowsedFile) => void;
  onSelectFolder?: (path: string) => void;
  selectedFolder?: string;
  nodeProps?: NodeProps;
} & PickProps) {
  // A folder holding a picked file starts open, so the pick is in view.
  const [open, setOpen] = useState(
    () =>
      depth < 1 ||
      Boolean(checkedPaths?.some((path) => path.startsWith(`${node.path}/`)))
  );
  const containsSelection = Boolean(
    selectedFolder?.startsWith(`${node.path}/`)
  );
  const expanded = open || containsSelection || Boolean(expandAll);
  const folderPaths = checkedPaths && onCheckFolder ? filesUnder(node) : null;
  const folderCheck = folderPaths && {
    paths: folderPaths,
    all: folderPaths.every((path) => checkedPaths?.includes(path)),
    some: folderPaths.some((path) => checkedPaths?.includes(path)),
  };
  const { className: extraClassName, ...extra } = nodeProps?.(node) ?? {};
  return (
    <Collapsible open={expanded} onOpenChange={setOpen}>
      {onSelectFolder ? (
        <div
          {...extra}
          className={cn(
            "flex items-center rounded hover:bg-muted",
            selectedFolder === node.path &&
              "bg-primary/10 text-primary dark:text-primary-foreground",
            extraClassName
          )}
        >
          <CollapsibleTrigger asChild>
            <button
              type="button"
              aria-label={node.name}
              className="flex size-11 shrink-0 items-center justify-center rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring md:size-6"
              style={{ marginLeft: `${depth * 16}px` }}
            >
              <ChevronRight
                className={cn(
                  "h-3.5 w-3.5 text-muted-foreground transition-transform duration-200 motion-reduce:transition-none",
                  expanded && "rotate-90"
                )}
              />
            </button>
          </CollapsibleTrigger>
          <button
            type="button"
            onClick={() => {
              setOpen(true);
              onSelectFolder(node.path);
            }}
            aria-current={selectedFolder === node.path ? "location" : undefined}
            className="flex min-w-0 flex-1 items-center gap-2 rounded py-1.5 pr-2 text-left text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
            title={node.path}
          >
            {expanded ? (
              <FolderOpen className="h-4 w-4 shrink-0 text-primary/80" />
            ) : (
              <Folder className="h-4 w-4 shrink-0 text-primary/80" />
            )}
            <span className="truncate">{node.name}</span>
          </button>
        </div>
      ) : (
        <div
          className={cn(
            "flex w-full items-center rounded",
            folderCheck && "hover:bg-muted"
          )}
        >
          <CollapsibleTrigger asChild>
            <button
              type="button"
              {...extra}
              className={cn(
                "flex min-h-11 min-w-0 flex-1 items-center gap-1.5 rounded px-2 py-1 text-left text-sm md:min-h-6",
                !folderCheck && "hover:bg-muted",
                extraClassName
              )}
              style={{ paddingLeft: `${depth * 16 + 4}px` }}
            >
              <ChevronRight
                className={cn(
                  "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
                  expanded && "rotate-90"
                )}
              />
              {expanded ? (
                <FolderOpen className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              ) : (
                <Folder className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              )}
              <span className="truncate font-medium">{node.name}</span>
              <span className="text-xs text-muted-foreground">
                {node.children.size}
              </span>
            </button>
          </CollapsibleTrigger>
          {folderCheck && (
            // Beside the fold button, not in it: a checkbox is a button too.
            <Checkbox
              checked={folderCheck.all}
              indeterminate={!folderCheck.all && folderCheck.some}
              onCheckedChange={() =>
                onCheckFolder?.(folderCheck.paths, !folderCheck.all)
              }
              aria-label={node.name}
              className="mr-2 shrink-0"
            />
          )}
        </div>
      )}
      {/* The sidebar's own fold: the folder's contents slide to their
          measured height instead of jumping in. */}
      <CollapsibleContent className="aa-collapsible">
        {sortedChildren(node).map((child) =>
          child.isFile ? (
            <FileRow
              key={child.path}
              node={child}
              depth={depth + 1}
              onSelect={onSelect}
              selectedPath={selectedPath}
              onDelete={onDelete}
              nodeProps={nodeProps}
              checkedPaths={checkedPaths}
            />
          ) : (
            <FolderRow
              onSelectFolder={onSelectFolder}
              selectedFolder={selectedFolder}
              key={child.path}
              node={child}
              depth={depth + 1}
              onSelect={onSelect}
              selectedPath={selectedPath}
              onDelete={onDelete}
              nodeProps={nodeProps}
              checkedPaths={checkedPaths}
              expandAll={expandAll}
              onCheckFolder={onCheckFolder}
            />
          )
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}

export function FileTree({
  files,
  directories = [],
  onSelect,
  selectedPath,
  onDelete,
  onSelectFolder,
  selectedFolder,
  className,
  nodeProps,
  checkedPaths,
  expandAll,
  onCheckFolder,
}: {
  files: BrowsedFile[];
  directories?: string[];
  onSelect: (file: BrowsedFile) => void;
  selectedPath: string | null;
  onDelete?: (file: BrowsedFile) => void;
  onSelectFolder?: (path: string) => void;
  selectedFolder?: string;
  className?: string;
  nodeProps?: NodeProps;
} & PickProps) {
  const root = buildTree(files, directories);
  const top = sortedChildren(root);
  return (
    <div className={cn("rounded border py-1", className)}>
      {top.map((child) =>
        child.isFile ? (
          <FileRow
            key={child.path}
            node={child}
            depth={0}
            onSelect={onSelect}
            selectedPath={selectedPath}
            onDelete={onDelete}
            nodeProps={nodeProps}
            checkedPaths={checkedPaths}
          />
        ) : (
          <FolderRow
            onSelectFolder={onSelectFolder}
            selectedFolder={selectedFolder}
            key={child.path}
            node={child}
            depth={0}
            onSelect={onSelect}
            selectedPath={selectedPath}
            onDelete={onDelete}
            nodeProps={nodeProps}
            checkedPaths={checkedPaths}
            expandAll={expandAll}
            onCheckFolder={onCheckFolder}
          />
        )
      )}
    </div>
  );
}

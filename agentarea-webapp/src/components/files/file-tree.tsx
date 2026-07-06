"use client";

import { useState } from "react";
import { ChevronRight, FileText, Folder, FolderOpen } from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

export interface BrowsedFile {
  path: string;
  size: number;
  content_type?: string | null;
  last_modified?: string | null;
}

interface TreeNode {
  name: string;
  path: string;
  isFile: boolean;
  file?: BrowsedFile;
  children: Map<string, TreeNode>;
}

function buildTree(files: BrowsedFile[], directories: string[] = []): TreeNode {
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

function sortedChildren(node: TreeNode): TreeNode[] {
  return Array.from(node.children.values()).sort((a, b) => {
    if (a.isFile !== b.isFile) return a.isFile ? 1 : -1;
    return a.name.localeCompare(b.name);
  });
}

function FileRow({
  node,
  depth,
  onSelect,
  selectedPath,
}: {
  node: TreeNode;
  depth: number;
  onSelect: (file: BrowsedFile) => void;
  selectedPath: string | null;
}) {
  const file = node.file;
  if (!file) return null;
  const isSelected = selectedPath === file.path;
  return (
    <button
      type="button"
      onClick={() => onSelect(file)}
      className={cn(
        "flex w-full items-center gap-2 rounded px-2 py-1 text-left text-sm transition-colors hover:bg-muted",
        isSelected && "bg-muted"
      )}
      style={{ paddingLeft: `${depth * 16 + 8}px` }}
    >
      <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <span className="truncate flex-1">{node.name}</span>
    </button>
  );
}

function FolderRow({
  node,
  depth,
  onSelect,
  selectedPath,
}: {
  node: TreeNode;
  depth: number;
  onSelect: (file: BrowsedFile) => void;
  selectedPath: string | null;
}) {
  const [open, setOpen] = useState(depth < 1);
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <button
          type="button"
          className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-sm hover:bg-muted"
          style={{ paddingLeft: `${depth * 16 + 4}px` }}
        >
          <ChevronRight
            className={cn(
              "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
              open && "rotate-90"
            )}
          />
          {open ? (
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
      <CollapsibleContent>
        {sortedChildren(node).map((child) =>
          child.isFile ? (
            <FileRow
              key={child.path}
              node={child}
              depth={depth + 1}
              onSelect={onSelect}
              selectedPath={selectedPath}
            />
          ) : (
            <FolderRow
              key={child.path}
              node={child}
              depth={depth + 1}
              onSelect={onSelect}
              selectedPath={selectedPath}
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
}: {
  files: BrowsedFile[];
  directories?: string[];
  onSelect: (file: BrowsedFile) => void;
  selectedPath: string | null;
}) {
  const root = buildTree(files, directories);
  const top = sortedChildren(root);
  return (
    <div className="rounded border py-1">
      {top.map((child) =>
        child.isFile ? (
          <FileRow
            key={child.path}
            node={child}
            depth={0}
            onSelect={onSelect}
            selectedPath={selectedPath}
          />
        ) : (
          <FolderRow
            key={child.path}
            node={child}
            depth={0}
            onSelect={onSelect}
            selectedPath={selectedPath}
          />
        )
      )}
    </div>
  );
}

"use client";

import { useState } from "react";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { FileTree, type BrowsedFile } from "./file-tree";
import { FileTabs } from "./file-tabs";
import type { FetchUrlFn } from "./file-viewer";

export function FileBrowser({
  files,
  directories = [],
  fetchUrl,
  emptyMessage = "No files yet.",
  className = "h-[calc(100vh-12rem)]",
}: {
  files: BrowsedFile[];
  directories?: string[];
  fetchUrl: FetchUrlFn;
  emptyMessage?: string;
  className?: string;
}) {
  const [openFiles, setOpenFiles] = useState<BrowsedFile[]>([]);
  const [activePath, setActivePath] = useState<string | null>(null);

  const handleSelect = (file: BrowsedFile) => {
    setOpenFiles((prev) =>
      prev.some((f) => f.path === file.path) ? prev : [...prev, file]
    );
    setActivePath(file.path);
  };

  const handleClose = (path: string) => {
    setOpenFiles((prev) => {
      const next = prev.filter((f) => f.path !== path);
      if (activePath === path) {
        const idx = prev.findIndex((f) => f.path === path);
        const fallback = next[idx] ?? next[idx - 1] ?? null;
        setActivePath(fallback?.path ?? null);
      }
      return next;
    });
  };

  if (files.length === 0 && directories.length === 0) {
    return (
      <p className="p-6 text-sm text-muted-foreground">{emptyMessage}</p>
    );
  }

  return (
    <ResizablePanelGroup direction="horizontal" className={className}>
      <ResizablePanel defaultSize={28} minSize={18} maxSize={50}>

        <div className="h-full overflow-auto p-2">
          <FileTree
            files={files}
            directories={directories}
            onSelect={handleSelect}
            selectedPath={activePath}
          />
        </div>

      </ResizablePanel>
      <ResizableHandle withHandle />
      <ResizablePanel defaultSize={72}>
        <FileTabs
          openFiles={openFiles}
          activePath={activePath}
          onActivate={setActivePath}
          onClose={handleClose}
          fetchUrl={fetchUrl}
        />
      </ResizablePanel>
    </ResizablePanelGroup>
  );
}

export type { BrowsedFile, FetchUrlFn };

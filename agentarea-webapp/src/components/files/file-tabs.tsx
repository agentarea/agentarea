"use client";

import { X } from "lucide-react";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";
import { FileViewerContent, type FetchUrlFn } from "./file-viewer";
import type { BrowsedFile } from "./file-tree";

export function FileTabs({
  openFiles,
  activePath,
  onActivate,
  onClose,
  fetchUrl,
}: {
  openFiles: BrowsedFile[];
  activePath: string | null;
  onActivate: (path: string) => void;
  onClose: (path: string) => void;
  fetchUrl: FetchUrlFn;
}) {
  if (openFiles.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Select a file to preview it.
      </div>
    );
  }

  return (
    <Tabs
      value={activePath ?? undefined}
      onValueChange={onActivate}
      className="flex h-full flex-col"
    >
      <TabsPrimitive.List
        className="flex h-9 shrink-0 items-stretch overflow-x-auto border-b bg-muted/30"
      >
        {openFiles.map((file) => {
          const isActive = file.path === activePath;
          const fileName = file.path.split("/").pop() || file.path;
          return (
            <div
              key={file.path}
              className={cn(
                "group flex items-center gap-1.5 border-r pl-3 pr-1.5 text-sm",
                isActive ? "bg-background" : "bg-transparent hover:bg-background/60"
              )}
            >
              <TabsPrimitive.Trigger
                value={file.path}
                className={cn(
                  "flex items-center gap-1.5 outline-none",
                  isActive ? "text-foreground" : "text-muted-foreground"
                )}
              >
                <span className="truncate max-w-[180px]" title={file.path}>
                  {fileName}
                </span>
              </TabsPrimitive.Trigger>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onClose(file.path);
                }}
                className="rounded p-0.5 text-muted-foreground opacity-60 hover:bg-muted hover:opacity-100"
                aria-label={`Close ${fileName}`}
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          );
        })}
      </TabsPrimitive.List>

      {openFiles.map((file) => (
        <TabsContent
          key={file.path}
          value={file.path}
          className="mt-0 flex-1 overflow-hidden focus-visible:ring-0"
        >
          <FileViewerContent file={file} fetchUrl={fetchUrl} />
        </TabsContent>
      ))}
    </Tabs>
  );
}

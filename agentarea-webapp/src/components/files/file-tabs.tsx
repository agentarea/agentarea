"use client";

import { useTranslations } from "next-intl";
import { FileText, Folder, X } from "lucide-react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";
import { FOLDER_TAB } from "./tab-state";

/** The strip above the browser's content: the folder, then each open file.
 *
 * Must be rendered inside a Radix `Tabs` whose value is the folder sentinel or
 * an open file's path. The folder tab has no close button — it is where the
 * browser returns when the last file closes. */
export function FileTabStrip({
  folderLabel,
  open,
  active,
  onClose,
}: {
  folderLabel: string;
  open: string[];
  /** The focused file, or null while the folder tab is showing. */
  active: string | null;
  onClose: (path: string) => void;
}) {
  const t = useTranslations("FilesPage");
  return (
    <TabsPrimitive.List
      aria-label={t("openFiles")}
      className="flex h-9 min-w-0 flex-1 items-stretch overflow-x-auto"
    >
      <TabsPrimitive.Trigger
        value={FOLDER_TAB}
        className={cn(
          "flex shrink-0 items-center gap-1.5 border-r px-3 text-sm outline-none",
          active === null
            ? "bg-background text-foreground"
            : "text-muted-foreground hover:bg-background/60"
        )}
      >
        <Folder className="h-3.5 w-3.5 shrink-0 text-primary/80" />
        <span className="max-w-[180px] truncate">{folderLabel}</span>
      </TabsPrimitive.Trigger>
      {open.map((path) => {
        const name = path.split("/").pop() || path;
        const isActive = path === active;
        return (
          <div
            key={path}
            className={cn(
              "flex shrink-0 items-center gap-1.5 border-r pl-3 pr-1.5 text-sm",
              isActive ? "bg-background" : "hover:bg-background/60"
            )}
          >
            <TabsPrimitive.Trigger
              value={path}
              className={cn(
                "flex items-center gap-1.5 outline-none",
                isActive ? "text-foreground" : "text-muted-foreground"
              )}
            >
              <FileText className="h-3.5 w-3.5 shrink-0" />
              <span className="max-w-[180px] truncate" title={path}>
                {name}
              </span>
            </TabsPrimitive.Trigger>
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                onClose(path);
              }}
              className="rounded p-0.5 text-muted-foreground opacity-60 hover:bg-muted hover:opacity-100"
              aria-label={t("closeTab", { name })}
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        );
      })}
    </TabsPrimitive.List>
  );
}

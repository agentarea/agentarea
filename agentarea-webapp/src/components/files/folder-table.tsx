"use client";

import type { HTMLAttributes } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { FileText, Folder, FolderOpen, Search, Trash2, Upload, X } from "lucide-react";
import EmptyState from "@/components/EmptyState/EmptyState";
import { TableSkeleton } from "@/components/Skeleton";
import Table from "@/components/Table/Table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { formatFileSize } from "@/utils/fileUtils";
import type { BrowsedFile, TreeNode } from "./file-tree";

export type FolderEntry = TreeNode & { id: string };

/** One folder's contents: the size and date columns the tree cannot show.
 *
 * It is the first tab of the browser rather than a permanent pane, so opening
 * a file does not squeeze it into a third column. */
export function FolderTable({
  entries,
  search,
  onSearchChange,
  onOpen,
  onDelete,
  entryProps,
  loading,
  onBrowseFiles,
  showUploadZone,
  isDragging,
  emptyMessage,
}: {
  entries: FolderEntry[];
  search: string;
  onSearchChange: (value: string) => void;
  onOpen: (entry: TreeNode) => void;
  /** Omitted where the folder is read-only. */
  onDelete?: (file: BrowsedFile) => void;
  entryProps: (entry: TreeNode) => HTMLAttributes<HTMLElement>;
  loading: boolean;
  /** Open the file picker; omitted where the folder is read-only. */
  onBrowseFiles?: () => void;
  /** Whether an empty folder offers its whole area as the upload target. The
   * browser decides, because its pane-wide overlay must stand down for it. */
  showUploadZone: boolean;
  /** Whether something is being dragged over the surrounding pane. */
  isDragging: boolean;
  /** Replaces the stock description when the whole browser has no files. */
  emptyMessage?: string;
}) {
  const t = useTranslations("FilesPage");
  const tCommon = useTranslations("Common");
  const format = useFormatter();

  const entryButton = (entry: TreeNode) => (
    <button
      type="button"
      onClick={() => onOpen(entry)}
      title={entry.name}
      className="flex w-full min-w-0 items-center gap-3 rounded py-1 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
    >
      {entry.isFile ? (
        <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
      ) : (
        <Folder className="h-4 w-4 shrink-0 fill-primary/10 text-primary/80" />
      )}
      <span className="min-w-0 max-w-[40vw] truncate md:max-w-sm">
        {entry.name}
      </span>
    </button>
  );

  return (
    <>
      <div className="relative mb-3 w-full max-w-xs">
        <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
        <Input
          aria-label={t("search")}
          placeholder={t("search")}
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          className="h-8 pl-8 pr-8 text-xs"
        />
        {search && (
          <button
            type="button"
            aria-label={t("clearSearch")}
            onClick={() => onSearchChange("")}
            className="absolute right-2 top-2 rounded"
          >
            <X className="h-4 w-4 text-muted-foreground" />
          </button>
        )}
      </div>
      {loading ? (
        <TableSkeleton
          rows={6}
          columns={[
            { header: t("name"), cellClassName: "w-full", barClassName: "h-4 w-56" },
            {
              header: t("modified"),
              headerClassName: "hidden lg:table-cell",
              cellClassName: "hidden lg:table-cell",
              barClassName: "h-4 w-24",
            },
            {
              header: t("size"),
              headerClassName: "text-right",
              cellClassName: "text-right",
              barClassName: "ml-auto h-4 w-12",
            },
            { header: "", barClassName: "h-7 w-7 rounded-md" },
          ]}
        />
      ) : entries.length ? (
        <Table<FolderEntry>
          data={entries}
          rowProps={entryProps}
          columns={[
            {
              header: t("name"),
              accessor: "name",
              render: (_, entry) => entry && entryButton(entry),
              cellClassName: "w-full",
            },
            {
              header: t("modified"),
              accessor: "modified",
              headerClassName: "hidden lg:table-cell",
              cellClassName:
                "hidden whitespace-nowrap text-xs text-muted-foreground lg:table-cell",
              render: (_, entry) =>
                entry?.file?.last_modified
                  ? format.dateTime(new Date(entry.file.last_modified), {
                      dateStyle: "medium",
                    })
                  : "—",
            },
            {
              header: t("size"),
              accessor: "size",
              headerClassName: "text-right",
              cellClassName:
                "whitespace-nowrap text-right text-xs tabular-nums text-muted-foreground",
              render: (_, entry) => {
                if (!entry?.file) return t("folder");
                const size = entry.file.size;
                // A live sandbox lists names without sizes; saying "0 B" there
                // would read as an empty file rather than an unknown one.
                return typeof size === "number" ? formatFileSize(size) : "—";
              },
            },
            {
              header: "",
              accessor: "actions",
              render: (_, entry) =>
                entry?.file &&
                onDelete && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-muted-foreground hover:text-destructive"
                    aria-label={t("deleteFile", { name: entry.name })}
                    onClick={() => entry.file && onDelete(entry.file)}
                  >
                    <Trash2 />
                  </Button>
                ),
            },
          ]}
        />
      ) : showUploadZone ? (
        <button
          type="button"
          onClick={onBrowseFiles}
          className={cn(
            "flex w-full flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed py-16 text-center transition-colors hover:border-primary/50 hover:bg-primary/5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring",
            isDragging && "border-primary bg-primary/5"
          )}
        >
          <Upload className="h-7 w-7 text-muted-foreground" />
          <span className="text-sm font-medium">{t("dropOrBrowse")}</span>
          <span className="text-xs text-muted-foreground">
            {t("emptyDescription")}
          </span>
        </button>
      ) : (
        <EmptyState
          icons={[FolderOpen]}
          title={search ? t("noResults") : t("emptyFolder")}
          description={
            search ? t("trySearch") : (emptyMessage ?? t("emptyDescription"))
          }
          className="border-0 bg-transparent py-12 shadow-none"
          action={
            search
              ? { label: tCommon("clearSearch"), onClick: () => onSearchChange("") }
              : undefined
          }
        />
      )}
    </>
  );
}

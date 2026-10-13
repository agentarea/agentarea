"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ArrowUpRight } from "lucide-react";
import type { WorkspaceFileInfo } from "@/api/client/types.gen";
import EmptyState from "@/components/EmptyState";
import { FileTree } from "@/components/files/file-tree";
import SearchInput from "@/components/SearchInput/SearchInput";
import { MenuSectionLabel } from "@/components/ui/menu-row";
import {
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import Link from "@/components/WorkspaceLink";
import { useWorkspacePath } from "@/hooks/useWorkspaceNavigation";
import { PICKER_BARE_EMPTY_STATE, PickerRowsSkeleton } from "./PickerRow";

/**
 * The inside of a "pick workspace files" sheet, laid out like the task's
 * attach sheet: a search, the workspace's file tree with a checkbox per file,
 * and nothing to confirm. A picked file stays in the tree, ticked, so it can
 * be unticked where it was ticked.
 */
export function FilePickerPanel({
  title,
  description,
  files,
  selected,
  onChange,
  loading,
  failed,
  onRefresh,
}: {
  title: string;
  description: string;
  files: WorkspaceFileInfo[];
  /** Picked paths. */
  selected: string[];
  onChange: (next: string[]) => void;
  loading: boolean;
  failed: boolean;
  onRefresh: () => void;
}) {
  const t = useTranslations("Pickers");
  const tCommon = useTranslations("Common");
  const inWorkspace = useWorkspacePath();
  const [query, setQuery] = useState("");

  // A picked file the workspace no longer lists still has to be unpickable.
  const paths = [
    ...files.map((file) => file.path),
    ...selected.filter((path) => !files.some((file) => file.path === path)),
  ];
  const needle = query.trim().toLowerCase();
  const visible = needle
    ? paths.filter((path) => path.toLowerCase().includes(needle))
    : paths;
  const toggle = (path: string) =>
    onChange(
      selected.includes(path)
        ? selected.filter((item) => item !== path)
        : [...selected, path]
    );

  const emptyState = (props: {
    title: string;
    description?: string;
    action?: { label: string; onClick: () => void };
  }) => (
    <div className="flex h-full flex-col justify-center">
      <EmptyState className={PICKER_BARE_EMPTY_STATE} {...props} />
    </div>
  );

  let body;
  if (loading) {
    body = <PickerRowsSkeleton />;
  } else if (failed) {
    body = emptyState({
      title: t("loadFailed"),
      action: { label: t("refresh"), onClick: onRefresh },
    });
  } else if (!paths.length) {
    body = emptyState({
      title: t("emptyFilesTitle"),
      description: t("emptyFilesHint"),
      action: {
        label: t("uploadFiles"),
        // A new tab: leaving would drop the form being filled in.
        onClick: () =>
          window.open(inWorkspace("/files"), "_blank", "noopener,noreferrer"),
      },
    });
  } else if (!visible.length) {
    body = emptyState({
      title: t("nothingFoundTitle"),
      description: t("nothingFound", { query }),
    });
  } else {
    body = (
      <>
        <div className="px-3">
          <MenuSectionLabel>
            {t("filesHeading")} ({visible.length})
          </MenuSectionLabel>
        </div>
        {/* Our file tree, in its picking mode: folders fold, files tick. */}
        <div className="px-3">
          <FileTree
            files={visible.map((path) => ({ path }))}
            onSelect={(file) => toggle(file.path)}
            selectedPath={null}
            checkedPaths={selected}
            // A folder's box picks or drops every file under it at once.
            onCheckFolder={(paths, checked) =>
              onChange(
                checked
                  ? [...selected, ...paths.filter((p) => !selected.includes(p))]
                  : selected.filter((p) => !paths.includes(p))
              )
            }
            // While a search narrows the files, every match is shown.
            expandAll={Boolean(needle)}
            className="border-0 py-0"
          />
        </div>
      </>
    );
  }

  return (
    <>
      <SheetHeader className="space-y-1 border-b px-5 pb-4 pr-12 pt-5 text-left">
        <SheetTitle className="text-[15px]">{title}</SheetTitle>
        <SheetDescription className="text-xs">{description}</SheetDescription>
      </SheetHeader>

      {/* The subheader's 42px band: the search carries its own padding. */}
      <div className="flex h-[42px] shrink-0 items-center border-b px-5">
        <SearchInput
          delay={150}
          onDebouncedChange={setQuery}
          placeholder={tCommon("search")}
        />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-2">{body}</div>

      <div className="flex items-center justify-between gap-3 border-t px-5 py-3">
        <Link
          href="/files"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
        >
          {t("manageFilesLink")}
          <ArrowUpRight className="h-3 w-3" />
        </Link>
        <span className="note">{t("appliesInstantly")}</span>
      </div>
    </>
  );
}

"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { RefreshCw } from "lucide-react";
import { SelectableList } from "@/components/SelectableList/SelectableList";
import { Button } from "@/components/ui/button";

/**
 * The states every attach list shares: loading, failed, empty-with-a-way-out,
 * and the list itself. Each surface used to spell these out again, which is how
 * they drifted into saying different things about the same data.
 */
export function ResourcePicker<T extends { id: string }>({
  items,
  selectedIds,
  onAdd,
  onRemove,
  extractTitle,
  extractIconSrc,
  prefix,
  loading,
  failed,
  onRefresh,
  emptyText,
  manageText,
  manageHref,
}: {
  items: T[];
  selectedIds: string[];
  onAdd: (item: T) => void;
  onRemove: (item: T) => void;
  extractTitle: (item: T) => ReactNode;
  extractIconSrc?: (item: T) => string;
  prefix: string;
  loading: boolean;
  failed: boolean;
  onRefresh: () => void;
  /** Shown when nothing is available — paired with the link that fixes that. */
  emptyText: string;
  manageText: string;
  manageHref: string;
}) {
  const t = useTranslations("Pickers");

  const refresh = (
    <Button
      type="button"
      variant="ghost"
      size="xs"
      className="gap-1.5 px-1.5 text-xs text-muted-foreground hover:text-foreground"
      onClick={onRefresh}
    >
      <RefreshCw className="h-3.5 w-3.5" />
      {t("refresh")}
    </Button>
  );

  if (loading) return <p className="note">{t("loading")}</p>;

  if (failed) {
    return (
      <div className="space-y-2">
        <p role="alert" className="text-xs text-destructive">
          {t("loadFailed")}
        </p>
        {refresh}
      </div>
    );
  }

  if (!items.length) {
    return (
      <div className="space-y-2">
        <p className="note">{emptyText}</p>
        <div className="flex flex-wrap items-center gap-2">
          <Link
            href={manageHref}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-primary hover:underline"
          >
            {manageText}
          </Link>
          {refresh}
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-0 overflow-y-auto pb-6">
      <SelectableList
        items={items}
        prefix={prefix}
        selectedIds={selectedIds}
        extractTitle={extractTitle}
        extractIconSrc={extractIconSrc}
        onAdd={onAdd}
        onRemove={onRemove}
        disableExpand
      />
      {refresh}
    </div>
  );
}

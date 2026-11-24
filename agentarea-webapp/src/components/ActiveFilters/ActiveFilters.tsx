"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";

export interface ActiveFilter {
  /** Unique within the row: a filter with several values gets one per value. */
  id: string;
  /** What is filtered, e.g. "Source": shown only when there is no icon to say it. */
  label: string;
  /** The value it is filtered by. */
  value: ReactNode;
  /** The value's 14px glyph, the one its option shows in the subheader. */
  icon?: ReactNode;
  onRemove: () => void;
}

/**
 * The filters a list is narrowed by, as a quiet row of chips in the toolbar's
 * own shape (h-6, the pressed ToolbarButton's fill): the value and its glyph,
 * a cross that removes it, and "clear all" once there are two. The glyph
 * names the filter (a status, a stream, a source's logo); a filter without
 * one shows its label. Renders nothing when no filter is on.
 */
export default function ActiveFilters({
  filters,
  onClearAll,
}: {
  filters: ActiveFilter[];
  onClearAll: () => void;
}) {
  const t = useTranslations("Common");
  if (filters.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-1">
      {filters.map((filter) => (
        <span
          key={filter.id}
          title={filter.label}
          className="inline-flex h-6 max-w-xs items-center gap-1 rounded-md bg-muted pl-1.5 text-[12px] text-foreground/80"
        >
          {filter.icon ?? (
            <span className="shrink-0 text-muted-foreground">
              {filter.label}
            </span>
          )}
          <span className="min-w-0 truncate">{filter.value}</span>
          <button
            type="button"
            aria-label={t("removeFilter", { label: filter.label })}
            onClick={filter.onRemove}
            className="inline-flex h-6 w-5 shrink-0 items-center justify-center rounded-r-md text-muted-foreground hover:text-foreground"
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
      {filters.length > 1 && (
        <Button
          size="xs"
          variant="ghost"
          className="px-1.5 text-muted-foreground"
          onClick={onClearAll}
        >
          {t("clearAll")}
        </Button>
      )}
    </div>
  );
}

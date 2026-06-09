"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Filter, SlidersHorizontal } from "lucide-react";
import HeaderTabs from "@/components/HeaderTabs";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { CollectionViewMode } from "./types";

export interface CollectionTab {
  value: string;
  label: string;
  count?: number;
}

export interface DisplayMenuOption {
  value: string;
  label: string;
  icon: ReactNode;
}

export interface CollectionToolbarProps {
  /** Left-aligned tab strip (e.g. source / status), with optional counts. */
  tabs?: CollectionTab[];
  activeTab?: string;
  onTabChange?: (value: string) => void;

  /** Filter toggle — rendered immediately after the tabs. Omit `onToggleFilter`
   *  to hide it. */
  filterLabel?: string;
  filterActive?: boolean;
  onToggleFilter?: () => void;

  /** Optional inline node (e.g. a search box) rendered after the tabs/filter,
   *  growing to fill the space before the Display + view segment. */
  searchSlot?: ReactNode;

  /** Display popover (grouping + ordering). Rendered on the right when either
   *  option list is provided. */
  displayLabel?: string;
  groupingLabel?: string;
  groupOptions?: DisplayMenuOption[];
  group?: string;
  onGroupChange?: (value: string) => void;
  orderingLabel?: string;
  orderOptions?: DisplayMenuOption[];
  order?: string;
  onOrderChange?: (value: string) => void;

  /** List / grid segment (right edge). */
  view: CollectionViewMode;
  onViewChange: (value: CollectionViewMode) => void;
  listLabel?: string;
  gridLabel?: string;

  className?: string;
}

/**
 * The shared collection toolbar: a left tab strip + Filter toggle, then the
 * Display popover and a list/grid segment pushed to the right. Used by every
 * Linear-style collection page (Skills, Agents, …) so the chrome stays
 * identical. The page owns the applied-filter row below it (build it with the
 * exported `FilterSelect`).
 */
export default function CollectionToolbar({
  tabs,
  activeTab,
  onTabChange,
  filterLabel,
  filterActive,
  onToggleFilter,
  searchSlot,
  displayLabel,
  groupingLabel,
  groupOptions,
  group,
  onGroupChange,
  orderingLabel,
  orderOptions,
  order,
  onOrderChange,
  view,
  onViewChange,
  listLabel,
  gridLabel,
  className,
}: CollectionToolbarProps) {
  // Generic chrome labels default to the shared, translated "Collection"
  // namespace so every page renders identical (localized) toolbar text.
  const t = useTranslations("Collection");
  const filterText = filterLabel ?? t("filter");
  const displayText = displayLabel ?? t("display");
  const groupingText = groupingLabel ?? t("grouping");
  const orderingText = orderingLabel ?? t("ordering");
  const listText = listLabel ?? t("listView");
  const gridText = gridLabel ?? t("gridView");

  const hasDisplay =
    (groupOptions?.length ?? 0) > 0 || (orderOptions?.length ?? 0) > 0;

  return (
    <div
      className={cn(
        "flex h-[42px] shrink-0 items-center gap-1.5 border-b border-zinc-200 px-4 dark:border-zinc-700",
        className
      )}
    >
      {tabs && tabs.length > 0 && (
        <div className="no-scrollbar flex min-w-0 items-center gap-0.5 overflow-x-auto">
          {tabs.map((tab) => (
            <button
              key={tab.value}
              type="button"
              onClick={() => onTabChange?.(tab.value)}
              className={cn(
                "inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2 text-[12.5px] font-medium transition-colors",
                activeTab === tab.value
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
              )}
            >
              {tab.label}
              {tab.count != null && (
                <span className="text-[11px] text-muted-foreground/70">
                  {tab.count}
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      {/* Filter — sits right after the tabs */}
      {onToggleFilter && (
        <>
          {tabs && tabs.length > 0 && (
            <div className="mx-1 h-[18px] w-px shrink-0 bg-zinc-200 dark:bg-zinc-700" />
          )}
          <button
            type="button"
            onClick={onToggleFilter}
            className={cn(
              "inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2 text-[12.5px] font-normal transition-colors",
              filterActive
                ? "bg-muted text-foreground"
                : "text-foreground/80 hover:bg-muted/60"
            )}
          >
            <Filter className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="collection-btn-label">{filterText}</span>
          </button>
        </>
      )}

      {/* optional inline search (or other) slot */}
      {searchSlot && (
        <>
          {(tabs?.length || onToggleFilter) && (
            <div className="mx-1 h-[18px] w-px shrink-0 bg-zinc-200 dark:bg-zinc-700" />
          )}
          <div className="min-w-0 flex-1">{searchSlot}</div>
        </>
      )}

      {/* spacer pushes Display + segment to the right edge */}
      {!searchSlot && <div className="flex-1" />}

      {hasDisplay && (
        <Popover>
          <PopoverTrigger asChild>
            <button
              type="button"
              className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2 text-[12.5px] font-normal text-foreground/80 transition-colors hover:bg-muted/60"
            >
              <SlidersHorizontal className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="collection-btn-label">{displayText}</span>
            </button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-52 p-1.5">
            {groupOptions && groupOptions.length > 0 && (
              <>
                <p className="px-2 pb-1 pt-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground/70">
                  {groupingText}
                </p>
                {groupOptions.map((opt) => (
                  <MenuRow
                    key={opt.value}
                    icon={opt.icon}
                    label={opt.label}
                    selected={group === opt.value}
                    onClick={() => onGroupChange?.(opt.value)}
                  />
                ))}
              </>
            )}
            {groupOptions?.length && orderOptions?.length ? (
              <div className="my-1 h-px bg-border" />
            ) : null}
            {orderOptions && orderOptions.length > 0 && (
              <>
                <p className="px-2 pb-1 pt-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground/70">
                  {orderingText}
                </p>
                {orderOptions.map((opt) => (
                  <MenuRow
                    key={opt.value}
                    icon={opt.icon}
                    label={opt.label}
                    selected={order === opt.value}
                    onClick={() => onOrderChange?.(opt.value)}
                  />
                ))}
              </>
            )}
          </PopoverContent>
        </Popover>
      )}

      <HeaderTabs
        className="ml-1 shrink-0"
        value={view}
        onChange={(v) => onViewChange(v as CollectionViewMode)}
        tabs={[
          { value: "list", label: listText },
          { value: "grid", label: gridText },
        ]}
      />
    </div>
  );
}

function MenuRow({
  icon,
  label,
  selected,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-[12.5px]",
        selected ? "text-primary" : "text-foreground/80 hover:bg-muted"
      )}
    >
      <span className={selected ? "text-primary" : "text-muted-foreground"}>
        {icon}
      </span>
      {label}
    </button>
  );
}

/** Compact select used to build a page's applied-filter row beneath the toolbar. */
export function FilterSelect({
  value,
  placeholder,
  active,
  onValueChange,
  children,
}: {
  value: string;
  placeholder: string;
  active: boolean;
  onValueChange: (v: string) => void;
  children: ReactNode;
}) {
  return (
    <Select value={value} onValueChange={onValueChange}>
      <SelectTrigger
        className={cn(
          "h-6 w-auto gap-1.5 rounded-md border border-border bg-background px-2 text-xs font-normal shadow-none focus:ring-0",
          active ? "font-medium text-foreground" : "text-muted-foreground"
        )}
      >
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>{children}</SelectContent>
    </Select>
  );
}

/** Wrapper for the applied-filter row that sits directly under the toolbar. */
export function CollectionFilterRow({ children }: { children: ReactNode }) {
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-zinc-200 px-3.5 py-2 dark:border-zinc-700">
      {children}
    </div>
  );
}

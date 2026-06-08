"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { cn } from "@/lib/utils";
import CollectionCard from "./CollectionCard";
import CollectionRow from "./CollectionRow";
import type {
  CollectionGroup,
  CollectionItem,
  CollectionSection,
  CollectionViewMode,
  CollectionViewProps,
} from "./types";

function gridStyle(min: number): React.CSSProperties {
  return { gridTemplateColumns: `repeat(auto-fill, minmax(${min}px, 1fr))` };
}

function Grid({
  items,
  gridMinWidth,
  gridClassName,
}: {
  items: CollectionItem[];
  gridMinWidth: number;
  gridClassName?: string;
}) {
  return (
    <div className={cn("grid gap-3", gridClassName)} style={gridStyle(gridMinWidth)}>
      {items.map((item) => (
        <CollectionCard key={item.id} item={item} />
      ))}
    </div>
  );
}

function FlatList({ items }: { items: CollectionItem[] }) {
  return (
    <div>
      {items.map((item) => (
        <CollectionRow key={item.id} item={item} />
      ))}
    </div>
  );
}

function GroupedList({
  groups,
  collapsible,
}: {
  groups: CollectionGroup[];
  collapsible: boolean;
}) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  return (
    <div>
      {groups
        .filter((g) => g.items.length > 0)
        .map((g) => (
          <div key={g.key}>
            <button
              type="button"
              onClick={() =>
                collapsible &&
                setCollapsed((p) => ({ ...p, [g.key]: !p[g.key] }))
              }
              className={cn(
                "collection-hatch sticky top-0 z-[2] flex h-9 w-full items-center gap-2 border-b border-zinc-100 px-4 dark:border-zinc-800/70",
                !collapsible && "cursor-default"
              )}
            >
              {collapsible && (
                <ChevronDown
                  className={cn(
                    "h-3.5 w-3.5 text-muted-foreground transition-transform",
                    collapsed[g.key] && "-rotate-90"
                  )}
                />
              )}
              <span
                className="h-[9px] w-[9px] rounded-[3px]"
                style={{ backgroundColor: g.color }}
              />
              <span className="text-[12.5px] font-semibold">{g.label}</span>
              <span className="rounded-full bg-muted px-[7px] text-[11.5px] leading-[17px] text-muted-foreground">
                {g.items.length}
              </span>
            </button>
            {!collapsed[g.key] &&
              g.items.map((item) => <CollectionRow key={item.id} item={item} />)}
          </div>
        ))}
    </div>
  );
}

/** Renders one block (a whole collection or a single section). */
function Body({
  view,
  items,
  groups,
  gridMinWidth,
  gridClassName,
  collapsibleGroups,
  bleed,
  emptyState,
}: {
  view: CollectionViewMode;
  items?: CollectionItem[];
  groups?: CollectionGroup[];
  gridMinWidth: number;
  gridClassName?: string;
  collapsibleGroups: boolean;
  bleed?: boolean;
  emptyState?: React.ReactNode;
}) {
  const flat = items ?? groups?.flatMap((g) => g.items) ?? [];
  if (flat.length === 0) return <>{emptyState ?? null}</>;

  if (view === "grid") {
    return (
      <Grid items={flat} gridMinWidth={gridMinWidth} gridClassName={gridClassName} />
    );
  }
  const list = groups ? (
    <GroupedList groups={groups} collapsible={collapsibleGroups} />
  ) : (
    <FlatList items={flat} />
  );
  // Run rows edge-to-edge by cancelling the surrounding page gutter (px-4).
  return bleed ? <div className="-mx-4">{list}</div> : list;
}

export default function CollectionView({
  view,
  items,
  groups,
  sections,
  isLoading,
  error,
  emptyState,
  gridMinWidth = 264,
  containerQuery = true,
  collapsibleGroups = true,
  gridClassName,
  bleed,
  className,
}: CollectionViewProps) {
  let content: React.ReactNode;

  if (isLoading) {
    content = (
      <div className="flex h-64 items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  } else if (error) {
    content = (
      <div className="flex h-64 items-center justify-center text-destructive">
        {error}
      </div>
    );
  } else if (sections) {
    content = (
      <div className="flex flex-col">
        {sections.map((section: CollectionSection) => (
          <section key={section.id}>
            {section.title != null && (
              <div className="mb-3 mt-5 flex items-center gap-3 px-4 first:mt-0">
                <h2 className="whitespace-nowrap text-[13px] font-semibold text-foreground">
                  {section.title}
                </h2>
                <div className="h-px flex-1 bg-zinc-200 dark:bg-zinc-700" />
              </div>
            )}
            <Body
              view={view}
              items={section.items}
              groups={section.groups}
              gridMinWidth={gridMinWidth}
              gridClassName={gridClassName}
              collapsibleGroups={collapsibleGroups}
              bleed={bleed}
              emptyState={section.emptyState ?? emptyState}
            />
          </section>
        ))}
      </div>
    );
  } else {
    content = (
      <Body
        view={view}
        items={items}
        groups={groups}
        gridMinWidth={gridMinWidth}
        gridClassName={gridClassName}
        collapsibleGroups={collapsibleGroups}
        bleed={bleed}
        emptyState={emptyState}
      />
    );
  }

  return (
    <div className={cn(containerQuery && "collection-cq", className)}>
      {content}
    </div>
  );
}

"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import { CARD_GRID_DENSE } from "@/lib/collectionGrids";
import { cn } from "@/lib/utils";
import TriggerCard from "./TriggerCard";
import {
  findTriggerCatalogEntry,
  getTriggerDisplayName,
  getTriggerSourceKey,
  renderTriggerIcon,
  type EnrichedTrigger,
  type TriggerCatalogEntry,
} from "./triggerDisplay";
import TriggersTable from "./TriggersTable";

export type TriggersGroupBy = "channel" | "none";

interface TriggersListProps {
  triggers: EnrichedTrigger[];
  catalog: TriggerCatalogEntry[];
  viewMode: "grid" | "table";
  searchQuery: string;
  groupBy: TriggersGroupBy;
}

interface TriggerGroup {
  key: string;
  label: string;
  entry?: TriggerCatalogEntry;
  sample: EnrichedTrigger;
  items: EnrichedTrigger[];
}

export default function TriggersList({
  triggers,
  catalog,
  viewMode,
  searchQuery,
  groupBy,
}: TriggersListProps) {
  const t = useTranslations("TriggersPage");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  // Groups that actually have triggers come first (largest first); empty
  // catalog entries are not rendered at all.
  const groups = useMemo<TriggerGroup[] | null>(() => {
    if (groupBy !== "channel" || viewMode !== "table") return null;
    const map = new Map<string, TriggerGroup>();
    for (const trigger of triggers) {
      const entry = findTriggerCatalogEntry(trigger, catalog);
      const key = getTriggerSourceKey(entry, trigger);
      const existing = map.get(key);
      if (existing) {
        existing.items.push(trigger);
      } else {
        map.set(key, {
          key,
          label: getTriggerDisplayName(trigger, entry),
          entry: entry ?? undefined,
          sample: trigger,
          items: [trigger],
        });
      }
    }
    return [...map.values()].sort(
      (a, b) =>
        b.items.length - a.items.length || a.label.localeCompare(b.label)
    );
  }, [groupBy, viewMode, triggers, catalog]);

  const hasTriggers = triggers.length > 0;

  if (!hasTriggers && !searchQuery) {
    return (
      <EmptyState
        title={t("noTriggers")}
        description={t("noTriggersDescription")}
        iconsType="triggers"
      />
    );
  }

  if (!hasTriggers && searchQuery) {
    return (
      <EmptyState
        title={t("noMatchingTriggers")}
        description={t("noMatchingTriggersDescription", { query: searchQuery })}
        iconsType="triggers"
      />
    );
  }

  if (viewMode === "grid") {
    return (
      <div className={CARD_GRID_DENSE}>
        {triggers.map((trigger) => (
          <TriggerCard key={trigger.id} trigger={trigger} catalog={catalog} />
        ))}
      </div>
    );
  }

  if (!groups) {
    return <TriggersTable triggers={triggers} catalog={catalog} />;
  }

  return (
    <div className="flex flex-col gap-1">
      {groups.map((group) => (
        <div key={group.key}>
          <button
            type="button"
            onClick={() =>
              setCollapsed((prev) => ({
                ...prev,
                [group.key]: !prev[group.key],
              }))
            }
            className="flex h-9 w-full items-center gap-2 px-1 text-left"
          >
            <ChevronDown
              className={cn(
                "h-3.5 w-3.5 text-muted-foreground transition-transform",
                collapsed[group.key] && "-rotate-90"
              )}
            />
            <span className="text-muted-foreground">
              {renderTriggerIcon(group.entry, group.sample, "h-3.5 w-3.5")}
            </span>
            <span className="text-[12.5px] font-semibold">{group.label}</span>
            <span className="rounded-full bg-muted px-[7px] text-[11.5px] leading-[17px] text-muted-foreground">
              {group.items.length}
            </span>
          </button>
          {!collapsed[group.key] && (
            <TriggersTable
              triggers={group.items}
              catalog={catalog}
              hideChannelColumn
            />
          )}
        </div>
      ))}
    </div>
  );
}

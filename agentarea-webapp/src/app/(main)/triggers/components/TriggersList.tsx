"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import EmptyState from "@/components/EmptyState";
import { GroupHeader } from "@/components/ui/group-header";
import { CARD_GRID_DENSE } from "@/lib/collectionGrids";
import TriggerCard from "./TriggerCard";
import {
  findTriggerCatalogEntry,
  getTriggerColor,
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
      <div className={`p-4 ${CARD_GRID_DENSE}`}>
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
    <div className="flex flex-col">
      {groups.map((group) => (
        <div key={group.key}>
          <GroupHeader
            label={group.label}
            count={group.items.length}
            color={getTriggerColor(group.entry, group.sample)}
            icon={renderTriggerIcon(group.entry, group.sample, "h-3.5 w-3.5")}
            collapsed={collapsed[group.key]}
            sticky={false}
            onToggle={() =>
              setCollapsed((prev) => ({
                ...prev,
                [group.key]: !prev[group.key],
              }))
            }
          />
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

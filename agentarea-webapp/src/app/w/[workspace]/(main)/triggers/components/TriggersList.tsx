"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { ChevronDown } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import { CARD_GRID_DENSE } from "@/lib/collectionGrids";
import { cn } from "@/lib/utils";
import TriggerCard from "./TriggerCard";
import {
  getTriggerDisplayName,
  renderTriggerIcon,
  type EnrichedTrigger,
} from "./triggerDisplay";
import TriggersTable from "./TriggersTable";
import TriggersEmptyState from "./TriggersEmptyState";

export type TriggersGroupBy = "channel" | "none";

interface TriggersListProps {
  triggers: EnrichedTrigger[];
  /** Triggers in the workspace before the type filter and search. */
  totalCount: number;
  viewMode: "grid" | "table";
  searchQuery: string;
  groupBy: TriggersGroupBy;
}

interface TriggerGroup {
  key: string;
  label: string;
  sample: EnrichedTrigger;
  items: EnrichedTrigger[];
}

export default function TriggersList({
  triggers,
  totalCount,
  viewMode,
  searchQuery,
  groupBy,
}: TriggersListProps) {
  const t = useTranslations("TriggersPage");
  const tCommon = useTranslations("Common");
  const searchParams = useSearchParams();
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  // Groups that actually have triggers come first (largest first); empty
  // catalog entries are not rendered at all.
  const groups = useMemo<TriggerGroup[] | null>(() => {
    if (groupBy !== "channel" || viewMode !== "table") return null;
    const map = new Map<string, TriggerGroup>();
    for (const trigger of triggers) {
      const key = trigger.trigger_type;
      const existing = map.get(key);
      if (existing) {
        existing.items.push(trigger);
      } else {
        map.set(key, {
          key,
          label: getTriggerDisplayName(trigger, (type) => t(`type.${type}`)),
          sample: trigger,
          items: [trigger],
        });
      }
    }
    return [...map.values()].sort(
      (a, b) =>
        b.items.length - a.items.length || a.label.localeCompare(b.label)
    );
  }, [groupBy, viewMode, triggers, t]);

  const hasTriggers = triggers.length > 0;

  if (totalCount === 0) {
    return <TriggersEmptyState />;
  }

  if (!hasTriggers && searchQuery) {
    return (
      <EmptyState
        title={t("noMatchingTriggers")}
        description={t("noMatchingTriggersDescription", { query: searchQuery })}
        iconsType="triggers"
        action={{ label: tCommon("clearSearch"), href: "/triggers" }}
      />
    );
  }

  // The workspace has triggers, just none of the selected type.
  if (!hasTriggers) {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("type");
    const query = params.toString();
    return (
      <EmptyState
        title={t("noTriggersOfType")}
        description={t("noTriggersOfTypeDescription")}
        iconsType="triggers"
        action={{
          label: t("showAllTriggers"),
          href: query ? `/triggers?${query}` : "/triggers",
        }}
      />
    );
  }

  if (viewMode === "grid") {
    return (
      <div className={CARD_GRID_DENSE}>
        {triggers.map((trigger) => (
          <TriggerCard key={trigger.id} trigger={trigger} />
        ))}
      </div>
    );
  }

  if (!groups) {
    return <TriggersTable triggers={triggers} />;
  }

  return (
    // The header's 36px band is taller than its label: pulled up by the
    // difference, the first label sits on the page's top padding, where an
    // ungrouped table's edge would.
    <div className="-mt-2.5 flex flex-col gap-1">
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
              {renderTriggerIcon(group.sample, "h-3.5 w-3.5")}
            </span>
            <span className="text-[12.5px] font-semibold">{group.label}</span>
            <span className="rounded-full bg-muted px-[7px] text-[11.5px] leading-[17px] text-muted-foreground">
              {group.items.length}
            </span>
          </button>
          {!collapsed[group.key] && (
            <TriggersTable
              triggers={group.items}
              hideChannelColumn
            />
          )}
        </div>
      ))}
    </div>
  );
}

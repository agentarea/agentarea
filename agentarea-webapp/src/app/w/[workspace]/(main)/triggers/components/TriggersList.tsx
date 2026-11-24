"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import EmptyState from "@/components/EmptyState";
import { CollapsibleGroup } from "@/components/ui/group-header";
import { CARD_GRID_DENSE } from "@/lib/collectionGrids";
import TriggerCard from "./TriggerCard";
import {
  getTriggerLane,
  LANE_ICON,
  TRIGGER_LANES,
  type EnrichedTrigger,
  type TriggerLane,
} from "./triggerDisplay";
import TriggersEmptyState from "./TriggersEmptyState";
import TriggersTable from "./TriggersTable";

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
  lane: TriggerLane;
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
  // One group per lane that has triggers, in the lanes' own order.
  const groups = useMemo<TriggerGroup[] | null>(() => {
    if (groupBy !== "channel" || viewMode !== "table") return null;
    return TRIGGER_LANES.map((lane) => ({
      lane,
      items: triggers.filter((trigger) => getTriggerLane(trigger) === lane),
    })).filter((group) => group.items.length > 0);
  }, [groupBy, viewMode, triggers]);

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

  if (viewMode === "grid") {
    return (
      <div className={CARD_GRID_DENSE}>
        {triggers.map((trigger) => (
          <TriggerCard key={trigger.id} trigger={trigger} />
        ))}
      </div>
    );
  }

  if (!groups || groups.length < 2) {
    return (
      <TriggersTable
        triggers={triggers}
        hideChannelColumn={
          new Set(triggers.map((trigger) => trigger.trigger_type)).size < 2
        }
      />
    );
  }

  // The 36px group header carries its own air above the label, so the list
  // is pulled up into the content block's top padding.
  return (
    <div className="-mt-2 flex flex-col gap-1">
      {groups.map(({ lane, items }) => {
        const Icon = LANE_ICON[lane];
        return (
          <CollapsibleGroup
            key={lane}
            variant="plain"
            label={t(`groups.${lane}`)}
            count={items.length}
            icon={<Icon className="h-3.5 w-3.5" strokeWidth={1.85} />}
          >
            <TriggersTable triggers={items} hideChannelColumn />
          </CollapsibleGroup>
        );
      })}
    </div>
  );
}

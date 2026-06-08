"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { Bot } from "lucide-react";
import CollectionView, {
  type CollectionItem,
  shortAge,
} from "@/components/CollectionView";
import EmptyState from "@/components/EmptyState";
import {
  findTriggerCatalogEntry,
  getTriggerIconComponent,
} from "./triggerDisplay";

interface TriggersListProps {
  triggers: any[];
  catalog: any[];
  viewMode: "grid" | "table";
  searchQuery: string;
}

const TRIGGER_COLOR_BY_KEY: Record<string, string> = {
  cron: "#d99a00",
  schedule: "#d99a00",
  telegram: "#5e6ad2",
  slack: "#d4519e",
  discord: "#5e6ad2",
  email: "#27a08c",
  gmail: "#27a08c",
  github: "#8a8f98",
  webhook: "#5e6ad2",
  generic: "#5e6ad2",
  event: "#d99a00",
};

function triggerColor(entry: any, trigger: any): string {
  const key = (
    entry?.id ||
    entry?.webhook_type ||
    trigger?.webhook_type ||
    trigger?.config?.webhook_type ||
    trigger?.trigger_type ||
    "webhook"
  )
    .toString()
    .toLowerCase();
  return TRIGGER_COLOR_BY_KEY[key] ?? "#5e6ad2";
}

export default function TriggersList({
  triggers,
  catalog,
  viewMode,
  searchQuery,
}: TriggersListProps) {
  const t = useTranslations("TriggersPage");
  const tStatus = useTranslations("TriggersPage.status");

  const items = useMemo<CollectionItem[]>(
    () =>
      triggers.map((trigger) => {
        const entry = findTriggerCatalogEntry(trigger, catalog);
        const color = triggerColor(entry, trigger);
        return {
          id: trigger.id,
          icon: getTriggerIconComponent(entry, trigger),
          color,
          title: trigger.name,
          description: trigger.description,
          href: `/triggers/${trigger.id}`,
          badges: [
            { label: entry?.name ?? trigger.trigger_type, color },
            ...(trigger.agent_name
              ? [{ label: trigger.agent_name, icon: Bot }]
              : []),
            {
              label: trigger.is_active
                ? tStatus("active")
                : tStatus("inactive"),
              color: trigger.is_active ? "#27a08c" : "#8a8f98",
            },
          ],
          meta: shortAge(trigger.created_at),
        };
      }),
    [triggers, catalog, tStatus]
  );

  return (
    <CollectionView
      view={viewMode === "table" ? "list" : "grid"}
      items={items}
      bleed
      emptyState={
        <EmptyState
          title={searchQuery ? t("noMatchingTriggers") : t("noTriggers")}
          description={
            searchQuery
              ? t("noMatchingTriggersDescription", { query: searchQuery })
              : t("noTriggersDescription")
          }
          iconsType="triggers"
        />
      }
    />
  );
}

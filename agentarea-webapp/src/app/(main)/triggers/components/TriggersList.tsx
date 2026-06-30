"use client";

import { useTranslations } from "next-intl";
import EmptyState from "@/components/EmptyState";
import { CARD_GRID_DENSE } from "@/lib/collectionGrids";
import TriggerCard from "./TriggerCard";
import TriggersTable from "./TriggersTable";

interface TriggersListProps {
  triggers: any[];
  catalog: any[];
  viewMode: "grid" | "table";
  searchQuery: string;
}

export default function TriggersList({
  triggers,
  catalog,
  viewMode,
  searchQuery,
}: TriggersListProps) {
  const t = useTranslations("TriggersPage");

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

  return (
    <>
      {viewMode === "grid" ? (
        <div className={CARD_GRID_DENSE}>
          {triggers.map((trigger) => (
            <TriggerCard key={trigger.id} trigger={trigger} catalog={catalog} />
          ))}
        </div>
      ) : (
        <TriggersTable triggers={triggers} catalog={catalog} />
      )}
    </>
  );
}

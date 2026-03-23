"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import TriggerCard from "./TriggerCard";
import TriggersTable from "./TriggersTable";
import TriggersEmptyState from "./TriggersEmptyState";

interface TriggersListProps {
  triggers: any[];
  viewMode: "grid" | "table";
  searchQuery: string;
}

export default function TriggersList({
  triggers,
  viewMode,
  searchQuery,
}: TriggersListProps) {
  const router = useRouter();
  const t = useTranslations("TriggersPage");

  const hasTriggers = triggers.length > 0;

  // No triggers at all (and no search query) -> Global empty state
  if (!hasTriggers && !searchQuery) {
    return (
      <TriggersEmptyState onCreateClick={() => router.push("/triggers/create")} />
    );
  }

  // No results found for search query
  if (!hasTriggers && searchQuery) {
    return (
      <div className="flex h-64 flex-col items-center justify-center text-center">
        <p className="text-lg font-medium text-muted-foreground">
          {t("noMatchingTriggers")}
        </p>
        <Button
          variant="link"
          onClick={() => router.push("/triggers")}
          className="mt-2"
        >
          Clear search
        </Button>
      </div>
    );
  }

  // Render list/grid
  return (
    <>
      {viewMode === "grid" ? (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {triggers.map((trigger) => (
            <TriggerCard key={trigger.id} trigger={trigger} />
          ))}
        </div>
      ) : (
        <TriggersTable triggers={triggers} />
      )}
    </>
  );
}

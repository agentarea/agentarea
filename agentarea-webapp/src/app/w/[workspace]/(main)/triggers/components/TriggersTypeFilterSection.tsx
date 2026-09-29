import { listTriggerCatalog } from "@/lib/api";
import {
  findTriggerCatalogEntry,
  getTriggerLane,
  type TriggerCatalogEntry,
} from "./triggerDisplay";
import { getTriggersCached } from "./triggersData";
import TriggersTypeFilter from "./TriggersTypeFilter";

/**
 * Server wrapper that computes the per-lane counts (shared, request-cached
 * trigger fetch) and renders the client-side filter tabs.
 */
export default async function TriggersTypeFilterSection({
  currentType,
}: {
  currentType: string;
}) {
  const [{ triggers }, catalogResponse] = await Promise.all([
    getTriggersCached(),
    listTriggerCatalog(),
  ]);
  const catalog = (catalogResponse.data ?? []) as TriggerCatalogEntry[];

  const lanes = triggers.map((trigger) =>
    getTriggerLane(trigger, findTriggerCatalogEntry(trigger, catalog))
  );

  const counts = {
    all: triggers.length,
    channel: lanes.filter((lane) => lane === "channel").length,
    event: lanes.filter((lane) => lane === "event").length,
    schedule: lanes.filter((lane) => lane === "schedule").length,
  };

  return <TriggersTypeFilter currentType={currentType} counts={counts} />;
}

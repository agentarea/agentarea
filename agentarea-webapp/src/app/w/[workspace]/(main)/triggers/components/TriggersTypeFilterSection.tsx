import { getTriggerLane } from "./triggerDisplay";
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
  const { triggers } = await getTriggersCached();
  const lanes = triggers.map((trigger) => getTriggerLane(trigger));

  const counts = {
    all: triggers.length,
    channel: lanes.filter((lane) => lane === "channel").length,
    event: lanes.filter((lane) => lane === "event").length,
    schedule: lanes.filter((lane) => lane === "schedule").length,
  };

  return <TriggersTypeFilter currentType={currentType} counts={counts} />;
}

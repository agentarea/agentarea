import { getTriggersCached } from "./triggersData";
import TriggersTypeFilter from "./TriggersTypeFilter";

/**
 * Server wrapper that computes the per-type counts (shared, request-cached
 * trigger fetch) and renders the client-side filter tabs.
 */
export default async function TriggersTypeFilterSection({
  currentType,
}: {
  currentType: string;
}) {
  const { triggers } = await getTriggersCached();

  const counts = {
    all: triggers.length,
    cron: triggers.filter((trigger) => trigger.trigger_type === "cron").length,
    webhook: triggers.filter((trigger) => trigger.trigger_type === "webhook")
      .length,
  };

  return <TriggersTypeFilter currentType={currentType} counts={counts} />;
}

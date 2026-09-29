import type { TriggerResponse } from "@/api/client/types.gen";
import { getTriggerLane } from "../components/triggerDisplay";
import type { TriggerCatalogEntry } from "./actions";

type ShapeInput = {
  /** The catalog entry for the chosen type, absent until the catalog loads. */
  selected?: Pick<TriggerCatalogEntry, "kind" | "backend_type" | "data_extractor"> | null;
  initialData?: Pick<
    TriggerResponse,
    "trigger_type" | "data_extractor"
  > | null;
};

/**
 * What the form is actually editing, derived once instead of re-tested inline
 * at each field.
 *
 * `isChannel` decides whether event filters and HTTP methods appear at all:
 * Telegram and its peers are harnesses, where the channel decides what an event
 * is and hands over an extracted message, so neither has anything to act on.
 */
export function triggerShape({ selected, initialData }: ShapeInput) {
  const triggerType =
    initialData?.trigger_type ?? selected?.backend_type ?? "";
  const dataExtractor = initialData?.data_extractor ?? selected?.data_extractor;

  const isChannel =
    triggerType === "webhook" &&
    getTriggerLane(
      { trigger_type: triggerType, data_extractor: dataExtractor },
      selected ?? undefined
    ) === "channel";

  return {
    triggerType,
    isChannel,
    taskTextRequired: requiresTaskText(triggerType, dataExtractor),
  };
}

/**
 * A schedule comes due carrying nothing with it, so the task text is the only
 * thing that can tell the agent what to do — and the backend rejects a schedule
 * saved without one (`trigger_service.py`, `_validate_cron_configuration`).
 *
 * Two kinds are exempt because something else supplies the text: a webhook gets
 * it from the call, and a poller works on whatever the mailbox or feed handed
 * it. Both are fallbacks rather than prefixes — `resolve_task_query` uses the
 * trigger's own text only when nothing arrived with the event.
 */
export function requiresTaskText(
  triggerType: string,
  dataExtractor?: string | null
): boolean {
  return triggerType === "cron" && !dataExtractor;
}

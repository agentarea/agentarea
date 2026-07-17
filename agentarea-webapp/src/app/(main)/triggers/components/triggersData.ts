import { cache } from "react";
import type { TriggerResponse } from "@/api/client/types.gen";
import { listTriggers } from "@/lib/api";

/**
 * Request-memoized trigger fetch. Both the type-filter counts in the toolbar
 * and the listing content read through this, so the triggers list is fetched
 * once per request (React `cache` dedupes within a single render).
 */
export const getTriggersCached = cache(async () => {
  const res = await listTriggers();
  if (res.error) {
    return { triggers: [] as TriggerResponse[], error: true };
  }
  return { triggers: (res.data ?? []) as TriggerResponse[], error: false };
});

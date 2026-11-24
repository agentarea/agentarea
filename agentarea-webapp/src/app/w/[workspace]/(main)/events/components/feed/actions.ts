"use server";

import type { FeedEventResponse } from "@/api/client/types.gen";
import { listWorkspaceEvents } from "@/lib/api";
import { feedApiQuery, type FeedState } from "@/lib/eventFeed";
import { FEED_PAGE } from "./feedData";

/** The feed's events before `before`, a page of them; null when they could not be read. */
export async function readOlderEventsAction(
  state: FeedState,
  showPlatform: boolean,
  before: number
): Promise<{ events: FeedEventResponse[]; nextBefore: number | null } | null> {
  const result = await listWorkspaceEvents({
    ...feedApiQuery(state, showPlatform),
    before,
    limit: FEED_PAGE,
  });
  if (!result.data) return null;
  return {
    events: result.data.events,
    nextBefore: result.data.next_before ?? null,
  };
}

import "server-only";
import { cache } from "react";
import { listWorkspaceEvents } from "@/lib/api";
import { feedApiQuery, type FeedState } from "@/lib/eventFeed";
import { requireApiData } from "@/lib/server-resource";

export const FEED_PAGE = 50;

// Keyed by the query's text: `cache` compares arguments by identity.
const readPage = cache(async (query: string) =>
  requireApiData(
    await listWorkspaceEvents(JSON.parse(query)),
    "workspace events"
  )
);

/** The feed's page for this view, read once per request however many parts of the page ask. */
export function readFeedPage(state: FeedState, showPlatform: boolean) {
  const before =
    state.before && /^\d+$/.test(state.before)
      ? Number(state.before)
      : undefined;
  return readPage(
    JSON.stringify({
      ...feedApiQuery(state, showPlatform),
      before,
      limit: FEED_PAGE,
    })
  );
}

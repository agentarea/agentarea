import { cache } from "react";
import { listWorkspaceEvents } from "@/lib/api";
import { feedApiQuery, type FeedState } from "@/lib/eventFeed";
import { requireApiData } from "@/lib/server-resource";

export const FEED_PAGE = 50;

/**
 * Request-memoized read of one page of the feed. The rows and the sources
 * menu in the subheader both read through it, so a view is fetched once per
 * request (React `cache` dedupes within a single render); its key is the
 * request itself, as a string.
 */
const readFeedPage = cache(async (request: string) =>
  requireApiData(
    await listWorkspaceEvents(JSON.parse(request)),
    "workspace events"
  )
);

/** The page the view shows: from `before` when an older one is open. */
export function feedPage(state: FeedState, showPlatform: boolean) {
  const before =
    state.before && /^\d+$/.test(state.before)
      ? Number(state.before)
      : undefined;
  return readFeedPage(
    JSON.stringify({
      ...feedApiQuery(state, showPlatform),
      before,
      limit: FEED_PAGE,
    })
  );
}

/**
 * Events per source under the view's other filters, as the newest page
 * counts them (only it carries the counts): the same read as the rows unless
 * an older page is open. It never fails: the toolbar is not where a failed
 * read is reported.
 */
export async function feedSourceCounts(
  state: FeedState,
  showPlatform: boolean
): Promise<{ counts: Record<string, number>; capped: boolean }> {
  try {
    const page = await feedPage({ ...state, before: undefined }, showPlatform);
    return {
      counts: page.facets?.source_types ?? {},
      capped: page.facets?.capped ?? false,
    };
  } catch {
    // The rows report a failed read on their own; the menu then just keeps
    // the picked sources.
    return { counts: {}, capped: false };
  }
}

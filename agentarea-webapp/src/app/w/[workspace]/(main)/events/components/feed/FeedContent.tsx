import { listWorkspaceEvents } from "@/lib/api";
import { feedApiQuery, type FeedState } from "@/lib/eventFeed";
import { requireApiData } from "@/lib/server-resource";
import type { SourceType } from "@/lib/sourceTypes";
import FeedFilters from "./FeedFilters";
import FeedList from "./FeedList";

const PAGE = 50;

/** The filter rail and the rows of the feed, from one read of its first page. */
export default async function FeedContent({
  state,
  streams,
  sourceTypes,
}: {
  state: FeedState;
  streams: { id: string; name: string }[];
  sourceTypes: SourceType[];
}) {
  const before =
    state.before && /^\d+$/.test(state.before)
      ? Number(state.before)
      : undefined;
  const page = requireApiData(
    await listWorkspaceEvents({ ...feedApiQuery(state), before, limit: PAGE }),
    "workspace events"
  );
  return (
    <>
      <FeedFilters
        state={state}
        facets={page.facets ?? null}
        streams={streams}
        sourceTypes={sourceTypes}
      />
      <FeedList
        initial={page.events}
        nextBefore={page.next_before ?? null}
        state={state}
        streams={streams}
        sourceTypes={sourceTypes}
      />
    </>
  );
}

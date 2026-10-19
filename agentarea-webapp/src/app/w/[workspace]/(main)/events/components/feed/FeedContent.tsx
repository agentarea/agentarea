import { listWorkspaceEvents } from "@/lib/api";
import {
  feedApiQuery,
  PLATFORM_SOURCE_TYPE,
  platformForced,
  showsPlatform,
  type FeedState,
} from "@/lib/eventFeed";
import { requireApiData } from "@/lib/server-resource";
import type { SourceType } from "@/lib/sourceTypes";
import FeedFilters from "./FeedFilters";
import FeedList from "./FeedList";

const PAGE = 50;

/** The filter rail and the rows of the feed, from one read of its first page. */
export default async function FeedContent({
  state,
  streams,
  platformStreams,
  sourceTypes,
}: {
  state: FeedState;
  streams: { id: string; name: string }[];
  platformStreams: string[];
  sourceTypes: SourceType[];
}) {
  const showPlatform = showsPlatform(state, platformStreams);
  const before =
    state.before && /^\d+$/.test(state.before)
      ? Number(state.before)
      : undefined;
  const page = requireApiData(
    await listWorkspaceEvents({
      ...feedApiQuery(state, showPlatform),
      before,
      limit: PAGE,
    }),
    "workspace events"
  );
  return (
    <>
      <FeedFilters
        state={state}
        facets={page.facets ?? null}
        streams={streams}
        sourceTypes={sourceTypes}
        platform={{
          shown: showPlatform,
          forced: platformForced(state, platformStreams),
        }}
      />
      <FeedList
        initial={page.events}
        nextBefore={page.next_before ?? null}
        state={state}
        streams={streams}
        sourceTypes={sourceTypes}
        hidesPlatform={
          !showPlatform &&
          (page.facets?.source_types[PLATFORM_SOURCE_TYPE] ?? 0) > 0
        }
      />
    </>
  );
}

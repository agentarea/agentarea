import { listWorkspaceEvents } from "@/lib/api";
import {
  feedApiQuery,
  PLATFORM_SOURCE_TYPE,
  showsPlatform,
  type FeedState,
} from "@/lib/eventFeed";
import { requireApiData } from "@/lib/server-resource";
import type { SourceType } from "@/lib/sourceTypes";
import FeedList from "./FeedList";

const PAGE = 50;

/** The rows of the feed: the first page of it under the view's filters. */
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
  );
}

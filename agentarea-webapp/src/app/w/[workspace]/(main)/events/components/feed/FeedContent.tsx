import { listAgents } from "@/lib/api";
import {
  PLATFORM_SOURCE_TYPE,
  showsPlatform,
  type FeedState,
} from "@/lib/eventFeed";
import type { SourceType } from "@/lib/sourceTypes";
import { feedPage } from "./feedData";
import FeedList from "./FeedList";

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
  const [page, agentsResult] = await Promise.all([
    feedPage(state, showPlatform),
    listAgents(),
  ]);
  const agents = (agentsResult.data ?? []).map((a) => ({
    id: a.id,
    name: a.name,
  }));
  return (
    <FeedList
      initial={page.events}
      nextBefore={page.next_before ?? null}
      state={state}
      streams={streams}
      platformStreams={platformStreams}
      sourceTypes={sourceTypes}
      agents={agents}
      hidesPlatform={
        !showPlatform &&
        (page.facets?.source_types[PLATFORM_SOURCE_TYPE] ?? 0) > 0
      }
    />
  );
}

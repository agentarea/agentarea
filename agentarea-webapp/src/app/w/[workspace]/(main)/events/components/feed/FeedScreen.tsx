import { Suspense, type ComponentProps, type ReactNode } from "react";
import ContentBlock from "@/components/ContentBlock";
import {
  feedHref,
  liveQuery,
  platformForced,
  showsPlatform,
  type FeedState,
} from "@/lib/eventFeed";
import type { SourceType } from "@/lib/sourceTypes";
import FeedContent from "./FeedContent";
import FeedEventPanelServer from "./FeedEventPanelServer";
import FeedEventSidePanel from "./FeedEventSidePanel";
import { FeedLiveProvider } from "./FeedLive";
import { FeedSelectionProvider } from "./FeedSelection";
import FeedSkeleton, { FeedEventPanelSkeleton } from "./FeedSkeleton";
import FeedToolbar from "./FeedToolbar";
import FeedToolbarServer from "./FeedToolbarServer";

/**
 * The feed with its filters, live tail and side panel: the workspace's events
 * page, and a stream's page with the stream as its filter.
 */
export default function FeedScreen({
  state,
  streams,
  platformStreams,
  sourceTypes,
  header,
  aboveList,
}: {
  state: FeedState;
  streams: { id: string; name: string }[];
  platformStreams: string[];
  sourceTypes: SourceType[];
  header: ComponentProps<typeof ContentBlock>["header"];
  /** What the page shows over the rows, e.g. a stream's sources. */
  aboveList?: ReactNode;
}) {
  const { event, ...filters } = state;
  const showPlatform = showsPlatform(state, platformStreams);
  const toolbar = {
    state,
    streams,
    platformStreams,
    sourceTypes,
    platform: {
      shown: showPlatform,
      forced: platformForced(state, platformStreams),
    },
  };

  return (
    <FeedLiveProvider query={liveQuery(state, showPlatform)}>
      <FeedSelectionProvider serverEvent={event}>
        <ContentBlock
          className="flex overflow-hidden p-0"
          header={header}
          subheader={
            <Suspense fallback={<FeedToolbar {...toolbar} facets={null} />}>
              <FeedToolbarServer {...toolbar} />
            </Suspense>
          }
        >
          <div className="min-w-0 flex-1 space-y-4 overflow-y-auto px-4 py-5">
            {aboveList}
            <Suspense key={feedHref(filters)} fallback={<FeedSkeleton />}>
              <FeedContent
                state={state}
                streams={streams}
                platformStreams={platformStreams}
                sourceTypes={sourceTypes}
              />
            </Suspense>
          </div>
          <FeedEventSidePanel
            streams={streams}
            sourceTypes={sourceTypes}
            currentStream={state.stream}
          >
            {event && (
              <Suspense key={event} fallback={<FeedEventPanelSkeleton />}>
                <FeedEventPanelServer
                  eventId={event}
                  streams={streams}
                  sourceTypes={sourceTypes}
                  currentStream={state.stream}
                />
              </Suspense>
            )}
          </FeedEventSidePanel>
        </ContentBlock>
      </FeedSelectionProvider>
    </FeedLiveProvider>
  );
}

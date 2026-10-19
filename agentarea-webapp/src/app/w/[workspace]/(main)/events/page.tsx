import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { listStreams, listStreamSourceTypes } from "@/lib/api";
import { feedHref, liveQuery, parseFeedState } from "@/lib/eventFeed";
import { requireApiData } from "@/lib/server-resource";
import FeedContent from "./components/feed/FeedContent";
import FeedEventPanel from "./components/feed/FeedEventPanel";
import FeedEventSidePanel from "./components/feed/FeedEventSidePanel";
import { FeedLiveProvider, LiveIndicator } from "./components/feed/FeedLive";
import { FeedSelectionProvider } from "./components/feed/FeedSelection";
import FeedSkeleton, {
  FEED_GRID,
  FeedEventPanelSkeleton,
} from "./components/feed/FeedSkeleton";
import StreamsMenu from "./components/feed/StreamsMenu";

export const metadata: Metadata = { title: "Events" };

/** Everything that arrived in the workspace, newest first and live, and what the platform did with it. */
export default async function EventsPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const [t, params, streamsResult, typesResult] = await Promise.all([
    getTranslations("EventsPage"),
    searchParams,
    listStreams(),
    listStreamSourceTypes(),
  ]);
  const state = parseFeedState(params);
  const streams = requireApiData(streamsResult, "streams").map((s) => ({
    id: s.id,
    name: s.name,
    kind: s.kind,
  }));
  const sourceTypes = requireApiData(typesResult, "stream source types");
  const { event, ...filters } = state;
  const filterKey = feedHref(filters);

  return (
    <FeedLiveProvider query={liveQuery(state)}>
      <FeedSelectionProvider>
        <ContentBlock
          className="flex overflow-hidden p-0"
          header={{
            breadcrumb: [{ label: t("title") }],
            description: t("description"),
            controls: (
              <>
                <LiveIndicator />
                <StreamsMenu streams={streams} />
              </>
            ),
          }}
        >
          <div className="min-w-0 flex-1 overflow-y-auto px-4 py-5">
            <div className={FEED_GRID}>
              <Suspense key={filterKey} fallback={<FeedSkeleton />}>
                <FeedContent
                  state={state}
                  streams={streams}
                  sourceTypes={sourceTypes}
                />
              </Suspense>
            </div>
          </div>
          <FeedEventSidePanel
            event={event}
            closeHref={feedHref(state, { event: undefined })}
          >
            {event && (
              <Suspense key={event} fallback={<FeedEventPanelSkeleton />}>
                <FeedEventPanel
                  eventId={event}
                  streamNames={new Map(streams.map((s) => [s.id, s.name]))}
                  sourceTypes={sourceTypes}
                />
              </Suspense>
            )}
          </FeedEventSidePanel>
        </ContentBlock>
      </FeedSelectionProvider>
    </FeedLiveProvider>
  );
}

import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { listStreams, listStreamSourceTypes } from "@/lib/api";
import {
  feedHref,
  liveQuery,
  parseFeedState,
  showsPlatform,
} from "@/lib/eventFeed";
import { isPlatformStream } from "@/lib/platformStream";
import { requireApiData } from "@/lib/server-resource";
import FeedContent from "./components/feed/FeedContent";
import FeedEventPanelServer from "./components/feed/FeedEventPanelServer";
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
  const platformStreams = streams.filter(isPlatformStream).map((s) => s.id);
  const { event, ...filters } = state;
  const filterKey = feedHref(filters);

  return (
    <FeedLiveProvider
      query={liveQuery(state, showsPlatform(state, platformStreams))}
    >
      <FeedSelectionProvider serverEvent={event}>
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
                  platformStreams={platformStreams}
                  sourceTypes={sourceTypes}
                />
              </Suspense>
            </div>
          </div>
          <FeedEventSidePanel streams={streams} sourceTypes={sourceTypes}>
            {event && (
              <Suspense key={event} fallback={<FeedEventPanelSkeleton />}>
                <FeedEventPanelServer
                  eventId={event}
                  streams={streams}
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

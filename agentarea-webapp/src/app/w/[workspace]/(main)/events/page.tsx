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
import FeedActiveFilters from "./components/feed/FeedActiveFilters";
import FeedContent from "./components/feed/FeedContent";
import FeedEventPanelServer from "./components/feed/FeedEventPanelServer";
import FeedEventSidePanel from "./components/feed/FeedEventSidePanel";
import { FeedLiveProvider } from "./components/feed/FeedLive";
import { FeedSelectionProvider } from "./components/feed/FeedSelection";
import FeedSkeleton, {
  FeedEventPanelSkeleton,
} from "./components/feed/FeedSkeleton";
import FeedToolbar from "./components/feed/FeedToolbar";

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
    // The platform's stream is named by the platform, not by a member.
    name: isPlatformStream(s) ? t("streams.platformName") : s.name,
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
          }}
          subheader={
            <FeedToolbar
              streams={streams}
              platformStreams={platformStreams}
              sourceTypes={sourceTypes}
            />
          }
        >
          <div className="min-w-0 flex-1 overflow-y-auto px-4 py-5">
            <FeedActiveFilters
              state={filters}
              streams={streams}
              platformStreams={platformStreams}
              sourceTypes={sourceTypes}
            />
            <Suspense key={filterKey} fallback={<FeedSkeleton />}>
              <FeedContent
                state={state}
                streams={streams}
                platformStreams={platformStreams}
                sourceTypes={sourceTypes}
              />
            </Suspense>
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

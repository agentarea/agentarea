import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";
import { getStreamEvent, listStreams, listStreamSourceTypes } from "@/lib/api";
import {
  feedHref,
  legacyStreamQuery,
  liveQuery,
  parseFeedState,
  showsPlatform,
} from "@/lib/eventFeed";
import { isPlatformStream } from "@/lib/platformStream";
import { requireApiData } from "@/lib/server-resource";
import { requestWorkspacePath } from "@/lib/workspace-request";
import FeedActiveFilters from "../components/feed/FeedActiveFilters";
import FeedContent from "../components/feed/FeedContent";
import FeedEventPanelServer from "../components/feed/FeedEventPanelServer";
import FeedEventSidePanel from "../components/feed/FeedEventSidePanel";
import { FeedLiveProvider } from "../components/feed/FeedLive";
import { FeedPathProvider } from "../components/feed/FeedPath";
import { FeedSelectionProvider } from "../components/feed/FeedSelection";
import FeedSkeleton, {
  FeedEventPanelSkeleton,
} from "../components/feed/FeedSkeleton";

/**
 * The stream's events: the workspace feed, the same table and side panel,
 * pinned to this stream — its URL keeps the stream out, the page names it.
 */
export default async function StreamEventsPage({
  params,
  searchParams,
}: {
  params: Promise<{ streamId: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const [{ streamId }, query, t, streamsResult, typesResult] =
    await Promise.all([
      params,
      searchParams,
      getTranslations("EventsPage"),
      listStreams(),
      listStreamSourceTypes(),
    ]);
  const { stream: _ignored, ...fromUrl } = parseFeedState(query);
  const state = { ...fromUrl, stream: streamId };
  const path = { base: `/events/${streamId}`, pinned: ["stream"] as const };
  // An old link to this page asked by `?outcome=` and named its event by its
  // sequence here: the same view, the event by its id.
  const legacy = legacyStreamQuery(query);
  if (legacy) {
    const event =
      legacy.sequence === undefined
        ? undefined
        : (await getStreamEvent(streamId, legacy.sequence)).data?.event_id;
    redirect(
      await requestWorkspacePath(
        feedHref(
          fromUrl,
          { result: legacy.result ?? fromUrl.result, before: undefined, event },
          path
        )
      )
    );
  }
  const streams = requireApiData(streamsResult, "streams").map((s) => ({
    id: s.id,
    // The platform's stream is named by the platform, not by a member.
    name: isPlatformStream(s) ? t("streams.platformName") : s.name,
    kind: s.kind,
  }));
  const sourceTypes = requireApiData(typesResult, "stream source types");
  const platformStreams = streams.filter(isPlatformStream).map((s) => s.id);
  const showPlatform = showsPlatform(state, platformStreams);
  const { event, ...filters } = state;

  return (
    <FeedPathProvider path={path}>
      <FeedLiveProvider query={liveQuery(state, showPlatform)}>
        <FeedSelectionProvider serverEvent={event}>
          <div className="min-w-0 flex-1 overflow-y-auto px-4 py-5">
            {/* Its one select, the result, says its value on its button. */}
            <FeedActiveFilters
              inToolbar={["result"]}
              state={fromUrl}
              streams={streams}
              platformStreams={platformStreams}
              sourceTypes={sourceTypes}
            />
            <Suspense
              key={feedHref(filters, {}, path)}
              fallback={<FeedSkeleton />}
            >
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
        </FeedSelectionProvider>
      </FeedLiveProvider>
    </FeedPathProvider>
  );
}

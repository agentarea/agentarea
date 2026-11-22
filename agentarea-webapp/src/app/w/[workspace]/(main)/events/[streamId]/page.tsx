import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";
import {
  getStream,
  getStreamEvent,
  listStreams,
  listStreamSourceTypes,
} from "@/lib/api";
import { feedHref, legacyStreamQuery, parseFeedState } from "@/lib/eventFeed";
import { isPlatformStream, memberSourceTypes } from "@/lib/platformStream";
import { optionalApiData, requireApiData } from "@/lib/server-resource";
import { workspacePath } from "@/lib/workspace-routes";
import FeedScreen from "../components/feed/FeedScreen";
import AddSourceDialog from "./components/AddSourceDialog";
import StreamStrip, { StreamStripSkeleton } from "./components/StreamStrip";

/** The workspace feed with this stream as its filter, under the stream's sources. */
export default async function StreamEventsPage({
  params,
  searchParams,
}: {
  params: Promise<{ workspace: string; streamId: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const [{ workspace, streamId }, query, t] = await Promise.all([
    params,
    searchParams,
    getTranslations("EventsPage"),
  ]);
  const state = { ...parseFeedState(query), stream: streamId };
  const legacy = legacyStreamQuery(query);
  if (legacy) {
    const event =
      legacy.sequence === undefined
        ? undefined
        : optionalApiData(
            await getStreamEvent(streamId, legacy.sequence),
            "stream event"
          )?.event_id;
    redirect(
      workspacePath(
        workspace,
        feedHref(state, {
          result: legacy.result,
          before: undefined,
          ...(legacy.sequence === undefined ? {} : { event }),
        })
      )
    );
  }

  const [streamResult, streamsResult, typesResult] = await Promise.all([
    getStream(streamId),
    listStreams(),
    listStreamSourceTypes(),
  ]);
  const stream = requireApiData(streamResult, "stream");
  const streams = requireApiData(streamsResult, "streams").map((s) => ({
    id: s.id,
    name: s.name,
    kind: s.kind,
  }));
  const sourceTypes = requireApiData(typesResult, "stream source types");
  const platformStreams = streams.filter(isPlatformStream).map((s) => s.id);
  const platform = isPlatformStream(stream);

  return (
    <FeedScreen
      state={state}
      streams={streams}
      platformStreams={platformStreams}
      sourceTypes={sourceTypes}
      header={{
        breadcrumb: [
          { label: t("title"), href: "/events" },
          { label: platform ? t("streams.platformName") : stream.name },
        ],
        description: platform
          ? t("streams.platformDescription")
          : stream.description || undefined,
        controls: platform ? undefined : (
          <AddSourceDialog
            streamId={streamId}
            types={memberSourceTypes(sourceTypes)}
          />
        ),
      }}
      aboveList={
        <Suspense fallback={<StreamStripSkeleton />}>
          <StreamStrip
            streamId={streamId}
            types={sourceTypes}
            streams={streams}
          />
        </Suspense>
      }
    />
  );
}

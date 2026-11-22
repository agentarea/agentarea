import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";
import { listStreams, listStreamSourceTypes } from "@/lib/api";
import { feedHref, parseFeedState } from "@/lib/eventFeed";
import { isPlatformStream } from "@/lib/platformStream";
import { requireApiData } from "@/lib/server-resource";
import { workspacePath } from "@/lib/workspace-routes";
import FeedScreen from "./components/feed/FeedScreen";

export const metadata: Metadata = { title: "Events" };

/** Everything that arrived in the workspace, newest first and live, and what the platform did with it. */
export default async function EventsPage({
  params,
  searchParams,
}: {
  params: Promise<{ workspace: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const [t, { workspace }, query, streamsResult, typesResult] =
    await Promise.all([
      getTranslations("EventsPage"),
      params,
      searchParams,
      listStreams(),
      listStreamSourceTypes(),
    ]);
  const state = parseFeedState(query);
  // A stream is its own page now; a link from before keeps working.
  if (state.stream) redirect(workspacePath(workspace, feedHref(state)));
  const streams = requireApiData(streamsResult, "streams").map((s) => ({
    id: s.id,
    name: s.name,
    kind: s.kind,
  }));
  const sourceTypes = requireApiData(typesResult, "stream source types");
  const platformStreams = streams.filter(isPlatformStream).map((s) => s.id);

  return (
    <FeedScreen
      state={state}
      streams={streams}
      platformStreams={platformStreams}
      sourceTypes={sourceTypes}
      header={{
        breadcrumb: [{ label: t("title") }],
        description: t("description"),
      }}
    />
  );
}

import { getTranslations } from "next-intl/server";
import { getStreamEventById } from "@/lib/api";
import { apiErrorMessage, getApiStatus } from "@/lib/api-errors";
import type { SourceType } from "@/lib/sourceTypes";
import FeedEventPanel from "./FeedEventPanel";

/**
 * The event a URL comes with (`?event=`), read on the server for the first
 * paint. A failed read is the panel's to say, never the page's: the feed
 * beside it stays.
 */
export default async function FeedEventPanelServer({
  eventId,
  streams,
  sourceTypes,
}: {
  eventId: string;
  streams: { id: string; name: string }[];
  sourceTypes: SourceType[];
}) {
  const [t, result] = await Promise.all([
    getTranslations("EventsPage.panel"),
    getStreamEventById(eventId),
  ]);
  const status = getApiStatus(result);
  // Gone (or never this workspace's): the panel says the event is not kept.
  const gone = status === 403 || status === 404;
  return (
    <FeedEventPanel
      eventId={eventId}
      event={result.data ?? null}
      error={
        result.data || gone
          ? undefined
          : apiErrorMessage(result, t("loadFailed"))
      }
      streams={streams}
      sourceTypes={sourceTypes}
    />
  );
}

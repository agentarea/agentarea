import { getStreamEventById } from "@/lib/api";
import { optionalApiData } from "@/lib/server-resource";
import type { SourceType } from "@/lib/sourceTypes";
import FeedEventPanel from "./FeedEventPanel";

/** The event a URL comes with (`?event=`), read on the server for the first paint. */
export default async function FeedEventPanelServer({
  eventId,
  streams,
  sourceTypes,
}: {
  eventId: string;
  streams: { id: string; name: string }[];
  sourceTypes: SourceType[];
}) {
  const event = optionalApiData(
    await getStreamEventById(eventId),
    "stream event"
  );
  return (
    <FeedEventPanel
      eventId={eventId}
      event={event}
      streams={streams}
      sourceTypes={sourceTypes}
    />
  );
}

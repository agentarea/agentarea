// An event by its id, whichever stream holds it: opened in its stream's feed.
import { redirect } from "next/navigation";
import { getStreamEventById } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import { workspacePath } from "@/lib/workspace-routes";

interface Props {
  params: Promise<{ workspace: string; eventId: string }>;
}

export default async function StreamEventByIdPage({ params }: Props) {
  const { workspace, eventId } = await params;
  const event = requireApiData(
    await getStreamEventById(eventId),
    "stream event"
  );
  redirect(
    workspacePath(
      workspace,
      `/events/${event.stream_id}?event=${encodeURIComponent(event.event_id)}`
    )
  );
}

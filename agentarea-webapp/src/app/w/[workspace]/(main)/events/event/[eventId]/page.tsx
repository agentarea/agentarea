// An event by its id, whichever stream holds it: what a forward or a cause links to.
import { redirect } from "next/navigation";
import { getStreamEventById } from "@/lib/api";
import { feedHref } from "@/lib/eventFeed";
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
      feedHref({ stream: event.stream_id, event: event.event_id })
    )
  );
}

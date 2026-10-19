// An event by its id, whichever stream holds it: what a forward or a cause links to.
import { redirect } from "next/navigation";
import { getStreamEventById } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import { workspacePath } from "@/lib/workspace-routes";
import { feedHref } from "../../[streamId]/feedHref";

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
      feedHref(event.stream_id, { outcome: "all", event: event.sequence })
    )
  );
}

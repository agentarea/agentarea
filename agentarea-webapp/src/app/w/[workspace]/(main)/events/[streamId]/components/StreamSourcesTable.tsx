import { listStreamSources } from "@/lib/api";
import { getServerSession } from "@/lib/ory/flows";
import { requireApiData } from "@/lib/server-resource";
import type { SourceType } from "@/lib/sourceTypes";
import { deleteStreamSourceAction } from "../actions";
import StreamSourcesTableView from "./StreamSourcesTableView";

/** The stream's sources, read on the server, in their table. */
export default async function StreamSourcesTable({
  streamId,
  types,
}: {
  streamId: string;
  types: SourceType[];
}) {
  const [sourcesResult, session] = await Promise.all([
    listStreamSources(streamId),
    getServerSession(),
  ]);
  const sources = requireApiData(sourcesResult, "stream sources");
  return (
    <StreamSourcesTableView
      streamId={streamId}
      sources={sources}
      types={types}
      viewerId={session?.identity?.id}
      onDelete={deleteStreamSourceAction.bind(null, streamId)}
    />
  );
}

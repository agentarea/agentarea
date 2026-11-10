import { listStreamSources } from "@/lib/api";
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
  const sources = requireApiData(
    await listStreamSources(streamId),
    "stream sources"
  );
  return (
    <StreamSourcesTableView
      sources={sources}
      types={types}
      onDelete={deleteStreamSourceAction.bind(null, streamId)}
    />
  );
}

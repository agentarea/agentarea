import { redirect } from "next/navigation";
import { getStream, listStreamSourceTypes } from "@/lib/api";
import { isPlatformStream } from "@/lib/platformStream";
import { requireApiData } from "@/lib/server-resource";
import { requestWorkspacePath } from "@/lib/workspace-request";
import StreamSourcesTable from "../components/StreamSourcesTable";

export default async function StreamSourcesPage({
  params,
}: {
  params: Promise<{ streamId: string }>;
}) {
  const { streamId } = await params;
  const [streamResult, typesResult] = await Promise.all([
    getStream(streamId),
    listStreamSourceTypes(),
  ]);
  // The platform's stream has no sources tab: its one source is fixed.
  const stream = requireApiData(streamResult, "stream");
  if (isPlatformStream(stream)) {
    redirect(await requestWorkspacePath(`/events/${streamId}`));
  }
  return (
    <div className="min-w-0 flex-1 overflow-y-auto px-4 py-5">
      <StreamSourcesTable
        streamId={streamId}
        types={requireApiData(typesResult, "stream source types")}
      />
    </div>
  );
}

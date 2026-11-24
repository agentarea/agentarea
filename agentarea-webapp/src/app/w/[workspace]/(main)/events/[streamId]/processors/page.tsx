import { getTranslations } from "next-intl/server";
import EmptyState from "@/components/EmptyState";
import { listStreams, listStreamSubscriptions } from "@/lib/api";
import { isPlatformStream } from "@/lib/platformStream";
import { requireApiData } from "@/lib/server-resource";
import ProcessorsTable from "../components/ProcessorsTable";

export default async function StreamProcessorsPage({
  params,
}: {
  params: Promise<{ streamId: string }>;
}) {
  const { streamId } = await params;
  const [t, subscriptionsResult, streamsResult] = await Promise.all([
    getTranslations("EventsPage"),
    listStreamSubscriptions(streamId),
    listStreams(),
  ]);
  const processors = requireApiData(
    subscriptionsResult,
    "stream subscriptions"
  ).filter((sub) => sub.kind === "processor");
  const streamNames = Object.fromEntries(
    requireApiData(streamsResult, "streams").map((s) => [
      s.id,
      isPlatformStream(s) ? t("streams.platformName") : s.name,
    ])
  );

  return (
    <div className="min-w-0 flex-1 overflow-y-auto px-4 py-5">
      {processors.length === 0 ? (
        <EmptyState title={t("streamPage.noProcessors")} iconsType="triggers" />
      ) : (
        <ProcessorsTable processors={processors} streamNames={streamNames} />
      )}
    </div>
  );
}

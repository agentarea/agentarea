import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import {
  getStream,
  listStreamSources,
  listStreamSourceTypes,
  listStreamSubscriptions,
} from "@/lib/api";
import { isPlatformStream, memberSourceTypes } from "@/lib/platformStream";
import { requireApiData } from "@/lib/server-resource";
import AddSourceDialog from "./components/AddSourceDialog";
import StreamDetailTabs from "./components/StreamDetailTabs";

/**
 * One stream, as a detail page like a trigger's: its name and what it is for
 * in the header, adding a source on the right, and its sections as tabs —
 * its events, where they come from, and the processors reading it.
 */
export default async function StreamLayout({
  params,
  children,
}: {
  params: Promise<{ streamId: string }>;
  children: React.ReactNode;
}) {
  const { streamId } = await params;
  const [t, streamResult, typesResult, sourcesResult, subscriptionsResult] =
    await Promise.all([
      getTranslations("EventsPage"),
      getStream(streamId),
      listStreamSourceTypes(),
      listStreamSources(streamId),
      listStreamSubscriptions(streamId),
    ]);
  const stream = requireApiData(streamResult, "stream");
  const sourceTypes = requireApiData(typesResult, "stream source types");
  const platform = isPlatformStream(stream);
  // Best-effort counts for the tab pills; a failed lookup just hides one.
  const sourceCount = sourcesResult.data?.length;
  const sourcesFailing = Boolean(
    sourcesResult.data?.some((source) => source.poll_error)
  );
  const processorCount = subscriptionsResult.data?.filter(
    (sub) => sub.kind === "processor"
  ).length;

  return (
    <ContentBlock
      className="flex overflow-hidden p-0"
      header={{
        breadcrumb: [
          { label: t("title"), href: "/events" },
          { label: t("sections.streams"), href: "/events/streams" },
          { label: platform ? t("streams.platformName") : stream.name },
        ],
        description: platform
          ? t("streams.platformDescription")
          : stream.description || undefined,
        // The platform's stream has one fixed source: nothing to add.
        controls: platform ? undefined : (
          <AddSourceDialog
            streamId={streamId}
            types={memberSourceTypes(sourceTypes)}
          />
        ),
      }}
      subheader={
        <StreamDetailTabs
          streamId={streamId}
          platform={platform}
          sourceCount={sourceCount}
          sourcesFailing={sourcesFailing}
          processorCount={processorCount}
        />
      }
    >
      {children}
    </ContentBlock>
  );
}

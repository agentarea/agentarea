import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { getStream, listStreamSourceTypes } from "@/lib/api";
import { isPlatformStream, memberSourceTypes } from "@/lib/platformStream";
import { requireApiData } from "@/lib/server-resource";
import type { DispositionFilter as Filter } from "@/lib/streamOutcome";
import AddSourceDialog from "./components/AddSourceDialog";
import DispositionFilter from "./components/DispositionFilter";
import EventDetail from "./components/EventDetail";
import EventFeed from "./components/EventFeed";
import EventFeedSkeleton from "./components/EventFeedSkeleton";
import StreamProcessors from "./components/StreamProcessors";
import StreamSources, {
  StreamSourcesSkeleton,
} from "./components/StreamSources";

const FILTERS: Filter[] = ["all", "reacted", "skipped", "error", "unheard"];

function sequenceParam(value: string | string[] | undefined) {
  return typeof value === "string" && /^\d+$/.test(value)
    ? Number(value)
    : undefined;
}

export default async function StreamEventsPage({
  params,
  searchParams,
}: {
  params: Promise<{ streamId: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const [{ streamId }, query, t] = await Promise.all([
    params,
    searchParams,
    getTranslations("EventsPage"),
  ]);
  const [streamResult, typesResult] = await Promise.all([
    getStream(streamId),
    listStreamSourceTypes(),
  ]);
  const stream = requireApiData(streamResult, "stream");
  const sourceTypes = requireApiData(typesResult, "stream source types");
  const outcome = FILTERS.find((f) => f === query.outcome) ?? "all";
  const before = sequenceParam(query.before);
  const selected = sequenceParam(query.event);
  const platform = isPlatformStream(stream);

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/events" },
          { label: platform ? t("streams.platformName") : stream.name },
        ],
        description: platform
          ? t("streams.platformDescription")
          : stream.description || undefined,
        controls: platform ? undefined : (
          <AddSourceDialog
            streamId={streamId}
            types={memberSourceTypes(sourceTypes)}
          />
        ),
      }}
      subheader={
        <SubheaderToolbar controls={<DispositionFilter current={outcome} />} />
      }
    >
      <Suspense fallback={<StreamSourcesSkeleton />}>
        <StreamSources streamId={streamId} types={sourceTypes} />
      </Suspense>
      <Suspense fallback={null}>
        <StreamProcessors streamId={streamId} />
      </Suspense>
      <div
        className={
          selected !== undefined
            ? "grid gap-4 lg:grid-cols-[minmax(0,1fr)_420px]"
            : undefined
        }
      >
        <Suspense key={`${outcome}-${before}`} fallback={<EventFeedSkeleton />}>
          <EventFeed
            streamId={streamId}
            outcome={outcome}
            before={before}
            selected={selected}
          />
        </Suspense>
        {selected !== undefined && (
          <Suspense key={selected} fallback={<EventFeedSkeleton rows={4} />}>
            <EventDetail
              streamId={streamId}
              sequence={selected}
              outcome={outcome}
              before={before}
              sourceTypes={sourceTypes}
            />
          </Suspense>
        )}
      </div>
    </ContentBlock>
  );
}

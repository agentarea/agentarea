import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { getStream } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import type { DispositionFilter as Filter } from "@/lib/streamOutcome";
import DispositionFilter from "./components/DispositionFilter";
import EventDetail from "./components/EventDetail";
import EventFeed from "./components/EventFeed";
import EventFeedSkeleton from "./components/EventFeedSkeleton";

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
  const stream = requireApiData(await getStream(streamId), "stream");
  const outcome = FILTERS.find((f) => f === query.outcome) ?? "all";
  const before = sequenceParam(query.before);
  const selected = sequenceParam(query.event);

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/events" },
          { label: stream.name },
        ],
        description: stream.description || undefined,
      }}
      subheader={
        <SubheaderToolbar controls={<DispositionFilter current={outcome} />} />
      }
    >
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
            />
          </Suspense>
        )}
      </div>
    </ContentBlock>
  );
}

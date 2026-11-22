import { getTranslations } from "next-intl/server";
import EventTime from "@/components/EventTime";
import { TextPreview } from "@/components/files/text-preview";
import { Skeleton } from "@/components/ui/skeleton";
import WorkspaceLink from "@/components/WorkspaceLink";
import { listStreamSources, listStreamSubscriptions } from "@/lib/api";
import { getServerSession } from "@/lib/ory/flows";
import { requireApiData } from "@/lib/server-resource";
import { sourceTypeBySlug, type SourceType } from "@/lib/sourceTypes";
import { deleteStreamSourceAction } from "../actions";
import ProcessorsChip from "./ProcessorsChip";
import SourceChip from "./SourceChip";

/**
 * Where the stream's events come from and what turns them into other streams'
 * events, as one row over its feed: a chip per source, opening its URL,
 * senders and delete, and one for the processors when there are any.
 */
export default async function StreamStrip({
  streamId,
  types,
  streams,
}: {
  streamId: string;
  types: SourceType[];
  streams: { id: string; name: string }[];
}) {
  const [t, tProcessors, sourcesResult, subscriptionsResult, session] =
    await Promise.all([
      getTranslations("EventsPage.sources"),
      getTranslations("EventsPage.processors"),
      listStreamSources(streamId),
      listStreamSubscriptions(streamId),
      getServerSession(),
    ]);
  const viewerId = session?.identity?.id;
  const sources = requireApiData(sourcesResult, "stream sources");
  const processors = requireApiData(
    subscriptionsResult,
    "stream subscriptions"
  ).filter((sub) => sub.kind === "processor");
  const onDelete = deleteStreamSourceAction.bind(null, streamId);
  const streamNames = new Map(streams.map((s) => [s.id, s.name]));

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-zinc-200 pb-3 dark:border-zinc-700">
      {sources.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("empty")}</p>
      ) : (
        sources.map((source) => (
          <SourceChip
            key={source.id}
            streamId={streamId}
            source={source}
            type={sourceTypeBySlug(types, source.source_type)}
            chosenByOther={
              !!source.senders_set_by && source.senders_set_by !== viewerId
            }
            onDelete={source.kind === "platform" ? undefined : onDelete}
            polledAt={
              source.polled_at ? (
                <EventTime value={source.polled_at} style="dateTime" />
              ) : null
            }
          />
        ))
      )}
      {processors.length > 0 && (
        <ProcessorsChip count={processors.length}>
          <ul className="space-y-2">
            {processors.map((processor) => {
              const kinds = Array.isArray(processor.filter.kinds)
                ? (processor.filter.kinds as string[])
                : [];
              return (
                <li key={processor.id} className="card-item space-y-2 p-3">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                    <span className="font-medium">
                      {tProcessors("writesTo")}
                    </span>
                    {processor.output_stream_ids.map((outputId, index) => (
                      <span key={outputId}>
                        {index > 0 && ", "}
                        <WorkspaceLink
                          href={`/events/${outputId}`}
                          className="text-primary hover:underline"
                        >
                          {streamNames.get(outputId) ?? outputId}
                        </WorkspaceLink>
                      </span>
                    ))}
                    <span className="note">
                      {kinds.length > 0
                        ? tProcessors("kinds", { kinds: kinds.join(", ") })
                        : tProcessors("everyEvent")}
                    </span>
                    <span className="note ml-auto">
                      {tProcessors.rich("createdAt", {
                        time: () => (
                          <EventTime
                            value={processor.created_at}
                            style="dateTime"
                          />
                        ),
                      })}
                    </span>
                  </div>
                  {processor.code && (
                    <details className="group rounded-md border border-zinc-200 dark:border-zinc-700">
                      <summary className="cursor-pointer select-none px-3 py-2 text-xs text-muted-foreground">
                        {tProcessors("code")}
                      </summary>
                      <div className="border-t border-zinc-200 dark:border-zinc-700">
                        <TextPreview
                          path="processor.py"
                          text={processor.code}
                        />
                      </div>
                    </details>
                  )}
                </li>
              );
            })}
          </ul>
        </ProcessorsChip>
      )}
    </div>
  );
}

export function StreamStripSkeleton() {
  return (
    <div
      className="flex items-center gap-2 border-b border-zinc-200 pb-3 dark:border-zinc-700"
      aria-hidden="true"
    >
      <Skeleton className="h-6 w-28 rounded-md" />
      <Skeleton className="h-6 w-24 rounded-md" />
    </div>
  );
}

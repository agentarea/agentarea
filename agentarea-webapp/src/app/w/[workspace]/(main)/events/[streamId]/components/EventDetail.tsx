import { getLocale, getTranslations } from "next-intl/server";
import type { StreamEventResponse } from "@/api/client/types.gen";
import SectionLoadError from "@/components/SectionLoadError";
import { StatusIndicator } from "@/components/ui/status-indicator";
import WorkspaceLink from "@/components/WorkspaceLink";
import {
  getStreamEvent,
  listStreams,
  listStreamSubscriptions,
  listTriggers,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { optionalApiData } from "@/lib/server-resource";
import { getStreamOutcomeStatusPresentation } from "@/lib/status";
import {
  resolveForwardSource,
  sortedForwardTargets,
  type DispositionFilter,
} from "@/lib/streamOutcome";
import { formatDateTime } from "@/utils/dateUtils";
import { eventRowId, feedHref } from "../feedHref";
import FocusOnMount from "./FocusOnMount";

const PANEL_ID = "event-detail";
const TITLE_ID = "event-detail-title";

type Translator = Awaited<ReturnType<typeof getTranslations>>;

export default async function EventDetail({
  streamId,
  sequence,
  outcome,
  before,
}: {
  streamId: string;
  sequence: number;
  outcome: DispositionFilter;
  before?: number;
}) {
  const [t, tFilter, locale, eventResult, triggersResult, subscriptionsResult, streamsResult] =
    await Promise.all([
      getTranslations("EventsPage.detail"),
      getTranslations("EventsPage.filter"),
      getLocale(),
      getStreamEvent(streamId, sequence),
      listTriggers(),
      listStreamSubscriptions(streamId),
      listStreams(),
    ]);
  // Gone past retention, or never existed: the feed is still there, so only
  // this panel says so.
  const event = optionalApiData(eventResult, "stream event");
  const closeHref = `${feedHref(streamId, { outcome, before })}#${eventRowId(sequence)}`;
  // Target streams of this stream's own forward subscriptions, sorted the way
  // ForwardHandler appended derived events — only needed to turn "Forwarded
  // as: N" into a link, so a 403/empty read just falls back to plain text.
  const forwardTargets = new Map(
    (subscriptionsResult.data ?? []).map((sub) => [
      sub.id,
      sortedForwardTargets(sub.output_stream_ids),
    ])
  );
  const streamNames = new Map(
    (streamsResult.data ?? []).map((stream) => [stream.id, stream.name])
  );

  return (
    <section
      id={PANEL_ID}
      aria-labelledby={TITLE_ID}
      tabIndex={-1}
      className="rounded-md border border-zinc-200 bg-white card-shadow outline-none dark:border-zinc-700 dark:bg-zinc-800 lg:sticky lg:top-0 lg:self-start"
    >
      <FocusOnMount key={sequence} targetId={PANEL_ID} />
      <header className="flex items-start justify-between gap-3 border-b border-zinc-200 px-4 py-3 dark:border-zinc-700">
        <div className="min-w-0">
          <h2 id={TITLE_ID} className="text-base font-semibold">
            {t("title", { sequence })}
          </h2>
          {event && (
            <p className="mt-0.5 truncate text-xs text-muted-foreground">
              <span className="font-medium text-foreground/80">
                {event.kind}
              </span>
              {" · "}
              <span className="font-mono">{event.event_key}</span>
              {" · "}
              {formatDateTime(event.received_at, locale)}
            </p>
          )}
        </div>
        <WorkspaceLink
          href={closeHref}
          className="note shrink-0 hover:underline"
        >
          {t("close")}
        </WorkspaceLink>
      </header>
      {event ? (
        <EventBody
          event={event}
          t={t}
          tFilter={tFilter}
          triggerNames={
            new Map(
              (triggersResult.data ?? []).map((trigger) => [
                trigger.id,
                trigger.name,
              ])
            )
          }
          triggersError={
            triggersResult.error || !triggersResult.data
              ? apiErrorMessage(triggersResult, t("triggersLoadFailed"))
              : null
          }
          forwardTargets={forwardTargets}
          streamNames={streamNames}
        />
      ) : (
        <div className="py-6 text-center text-sm text-muted-foreground">
          {t("gone")}
        </div>
      )}
    </section>
  );
}

function EventBody({
  event,
  t,
  tFilter,
  triggerNames,
  triggersError,
  forwardTargets,
  streamNames,
}: {
  event: StreamEventResponse;
  t: Translator;
  tFilter: Translator;
  triggerNames: Map<string, string>;
  triggersError: string | null;
  forwardTargets: Map<string, string[]>;
  streamNames: Map<string, string>;
}) {
  const causedBy = resolveForwardSource(event);
  return (
    <div className="space-y-4 p-4">
      <div>
        <h3 className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
          {t("subscribers")}
        </h3>
        {triggersError && <SectionLoadError message={triggersError} />}
        {event.outcomes.length === 0 ? (
          <div className="py-6 text-center text-sm text-muted-foreground">
            {t("noOutcomes")}
          </div>
        ) : (
          <ul className="space-y-2">
            {event.outcomes.map((o) => {
              const presentation = getStreamOutcomeStatusPresentation(
                o.verdict
              );
              // Only a forward's own targets, in append order — a derived
              // sequence pairs with the target stream at the same index.
              const targets = forwardTargets.get(o.subscription_id) ?? [];
              return (
                <li
                  key={o.subscription_id}
                  className="card-item space-y-1 px-3 py-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    {o.trigger_id ? (
                      <WorkspaceLink
                        href={`/triggers/${o.trigger_id}`}
                        className="truncate font-medium hover:underline"
                      >
                        {triggerNames.get(o.trigger_id) ?? t("trigger")}
                      </WorkspaceLink>
                    ) : (
                      <span className="truncate font-medium">
                        {t("forward")}
                        {targets.length > 0 && (
                          <>
                            {": "}
                            {targets.map((targetId, index) => (
                              <span key={targetId} className="font-normal">
                                {index > 0 && ", "}
                                <WorkspaceLink
                                  href={`/events/${targetId}`}
                                  className="text-primary hover:underline"
                                >
                                  {streamNames.get(targetId) ?? targetId}
                                </WorkspaceLink>
                              </span>
                            ))}
                          </>
                        )}
                      </span>
                    )}
                    <StatusIndicator size="sm" kind={presentation.kind}>
                      {presentation.labelKey
                        ? tFilter(presentation.labelKey)
                        : presentation.label}
                      {presentation.labelKey === "unknown" && (
                        <span className="ml-1 font-mono text-xs">
                          {o.verdict}
                        </span>
                      )}
                    </StatusIndicator>
                  </div>
                  {o.reason && (
                    <p className="break-words text-sm text-muted-foreground">
                      {o.reason}
                    </p>
                  )}
                  <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                    {o.score != null && (
                      <span className="tabular-nums">
                        {t("score")}: {o.score.toFixed(2)}
                      </span>
                    )}
                    {o.task_id && (
                      <WorkspaceLink
                        href={`/tasks/${o.task_id}`}
                        className="text-primary hover:underline"
                      >
                        {t("task")}
                      </WorkspaceLink>
                    )}
                    {o.derived_sequences.length > 0 && (
                      <span className="flex items-center gap-1 tabular-nums">
                        {t("derived")}:{" "}
                        {o.derived_sequences.map((sequence, index) => {
                          const targetId = targets[index];
                          return (
                            <span key={sequence}>
                              {index > 0 && ", "}
                              {targetId ? (
                                <WorkspaceLink
                                  href={feedHref(targetId, {
                                    outcome: "all",
                                    event: sequence,
                                  })}
                                  className="text-primary hover:underline"
                                >
                                  {sequence}
                                </WorkspaceLink>
                              ) : (
                                sequence
                              )}
                            </span>
                          );
                        })}
                      </span>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
      {event.causation_id && (
        <div className="text-xs text-muted-foreground">
          {t("causedBy")}:{" "}
          {causedBy ? (
            <WorkspaceLink
              href={feedHref(causedBy.streamId, {
                outcome: "all",
                event: causedBy.sequence,
              })}
              className="text-primary hover:underline"
            >
              {streamNames.get(causedBy.streamId)
                ? `${streamNames.get(causedBy.streamId)} · ${t("title", { sequence: causedBy.sequence })}`
                : t("title", { sequence: causedBy.sequence })}
            </WorkspaceLink>
          ) : (
            <span className="break-all font-mono">{event.causation_id}</span>
          )}
        </div>
      )}
      <div>
        <h3 className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
          {t("data")}
        </h3>
        <pre className="max-h-96 overflow-auto rounded-md bg-muted/50 p-3 text-xs">
          {JSON.stringify(event.data, null, 2)}
        </pre>
      </div>
    </div>
  );
}

"use client";

import { useTranslations } from "next-intl";
import { RefreshCw } from "lucide-react";
import type {
  HandlerResponse,
  StreamEventDetailResponse,
} from "@/api/client/types.gen";
import EventTime from "@/components/EventTime";
import FormError from "@/components/FormError/FormError";
import {
  InfoPanelBody,
  InfoPanelHeader,
  InfoPanelSection,
} from "@/components/InfoPanel";
import { TaskStatus } from "@/components/TaskStatus";
import { Button } from "@/components/ui/button";
import { StatusIndicator } from "@/components/ui/status-indicator";
import WorkspaceLink from "@/components/WorkspaceLink";
import { eventByIdHref, feedHref, processingProgress } from "@/lib/eventFeed";
import { sourceTypeBySlug, type SourceType } from "@/lib/sourceTypes";
import { getStreamOutcomeStatusPresentation } from "@/lib/status";
import {
  EventAttachments,
  EventBody,
  EventFacts,
  EventHeaders,
} from "./EventEnvelope";
import ProcessingPill from "./ProcessingPill";

type Translator = ReturnType<typeof useTranslations>;

/** The event open in the side panel: what it says, its body, each subscriber's answer, then its envelope. */
export default function FeedEventPanel({
  eventId,
  event,
  error,
  onRetry,
  streams,
  sourceTypes,
  currentStream,
}: {
  eventId: string;
  /** Null when the event is no longer kept. */
  event: StreamEventDetailResponse | null;
  /** Reading the event failed. */
  error?: string;
  onRetry?: () => void;
  streams: { id: string; name: string }[];
  sourceTypes: SourceType[];
  /** The stream the feed is filtered to, if any. */
  currentStream?: string;
}) {
  const t = useTranslations("EventsPage");
  const tFilter = useTranslations("EventsPage.filter");
  const tCommon = useTranslations("Common");

  if (!event) {
    return (
      <>
        <InfoPanelHeader
          className="pr-10"
          label={t("panel.title")}
          title={<span className="font-mono">{eventId.slice(0, 8)}</span>}
        />
        <InfoPanelBody>
          {error ? (
            <div className="space-y-2">
              <FormError>{error}</FormError>
              {onRetry && (
                <Button size="xs" variant="outline" onClick={onRetry}>
                  <RefreshCw />
                  {tCommon("retry")}
                </Button>
              )}
            </div>
          ) : (
            <p className="py-6 text-center text-muted-foreground">
              {t("panel.gone")}
            </p>
          )}
        </InfoPanelBody>
      </>
    );
  }

  const progress = event.processing
    ? processingProgress(event.processing)
    : null;
  const streamName = streams.find((s) => s.id === event.stream_id)?.name;

  return (
    <>
      <InfoPanelHeader
        className="pr-10"
        labelClassName="normal-case tracking-normal"
        label={streamName ?? t("list.unknownStream")}
        title={event.kind}
      />
      <div className="-mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 px-3 pb-3 text-xs text-muted-foreground">
        <EventTime value={event.received_at} style="dateTime" />
        {event.processing && event.processing.status !== "no_handlers" && (
          <>
            <span aria-hidden="true">·</span>
            <ProcessingPill
              processing={event.processing}
              receivedAt={event.received_at}
              now={null}
            />
          </>
        )}
      </div>
      <InfoPanelBody>
        {event.summary && <p className="text-sm">{event.summary}</p>}
        <EventBody event={event} />
        {(event.handlers.length > 0 ||
          (progress && progress.total > progress.done) ||
          event.processing?.status === "queued") && (
          <InfoPanelSection title={t("panel.handlers")} contentClassName="p-0">
            <Handlers
              handlers={event.handlers}
              pending={progress ? progress.total - progress.done : 0}
              status={event.processing?.status}
              triggers={
                new Map(
                  event.outcomes.flatMap((o) =>
                    o.trigger_id ? [[o.subscription_id, o.trigger_id]] : []
                  )
                )
              }
              t={t}
              tFilter={tFilter}
            />
          </InfoPanelSection>
        )}
        <EventAttachments event={event} />
        <EventHeaders event={event} />
        <EventFacts
          event={event}
          sourceType={sourceTypeBySlug(sourceTypes, event.source_type)}
        />
        {currentStream !== event.stream_id && (
          <WorkspaceLink
            href={feedHref({ stream: event.stream_id, event: event.event_id })}
            className="inline-block text-primary hover:underline"
          >
            {t("panel.openInStream")}
          </WorkspaceLink>
        )}
      </InfoPanelBody>
    </>
  );
}

function Handlers({
  handlers,
  pending,
  status,
  triggers,
  t,
  tFilter,
}: {
  handlers: HandlerResponse[];
  pending: number;
  status: string | undefined;
  /** The trigger behind each trigger subscription, to link its name. */
  triggers: Map<string, string>;
  t: Translator;
  tFilter: Translator;
}) {
  if (status === "queued") {
    return <p className="p-3 text-muted-foreground">{t("panel.queued")}</p>;
  }
  return (
    <div>
      <ul className="divide-y divide-border">
        {handlers.map((handler) => {
          const verdict = getStreamOutcomeStatusPresentation(handler.verdict);
          const kindLabel =
            handler.kind === "trigger"
              ? t("panel.trigger")
              : handler.kind === "forward"
                ? t("panel.forward")
                : handler.kind === "processor"
                  ? t("panel.processor")
                  : t("panel.deleted");
          return (
            <li key={handler.subscription_id} className="space-y-1 px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    {kindLabel}
                  </p>
                  {triggers.has(handler.subscription_id) ? (
                    <WorkspaceLink
                      href={`/triggers/${triggers.get(handler.subscription_id)}`}
                      className="block truncate font-medium hover:underline"
                    >
                      {handler.name}
                    </WorkspaceLink>
                  ) : (
                    <p className="truncate font-medium">{handler.name}</p>
                  )}
                </div>
                <StatusIndicator
                  size="sm"
                  kind={verdict.kind}
                  className="shrink-0"
                >
                  {verdict.labelKey ? tFilter(verdict.labelKey) : verdict.label}
                </StatusIndicator>
              </div>
              {handler.reason && (
                <p className="break-words text-muted-foreground">
                  {handler.reason}
                </p>
              )}
              {handler.task_id && (
                <div className="flex items-center gap-2">
                  <WorkspaceLink
                    href={`/tasks/${handler.task_id}`}
                    className="text-primary hover:underline"
                  >
                    {t("panel.task")}
                  </WorkspaceLink>
                  {handler.task_status && (
                    <TaskStatus status={handler.task_status} />
                  )}
                </div>
              )}
              {handler.derived_event_ids.length > 0 && (
                <div className="flex flex-wrap items-center gap-1 text-muted-foreground">
                  {t("panel.derived")}:
                  {handler.derived_event_ids.map((id) => (
                    <WorkspaceLink
                      key={id}
                      href={eventByIdHref(id)}
                      className="font-mono text-primary hover:underline"
                      title={id}
                    >
                      {id.slice(0, 8)}
                    </WorkspaceLink>
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {pending > 0 && (
        <p className="border-t border-border px-3 py-2 text-muted-foreground">
          {t("panel.pending", { count: pending })}
        </p>
      )}
    </div>
  );
}

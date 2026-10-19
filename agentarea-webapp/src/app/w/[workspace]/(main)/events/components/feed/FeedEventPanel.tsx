import { getLocale, getTranslations } from "next-intl/server";
import type { HandlerResponse } from "@/api/client/types.gen";
import {
  InfoPanelBody,
  InfoPanelHeader,
  InfoPanelSection,
} from "@/components/InfoPanel";
import { TaskStatus } from "@/components/TaskStatus";
import { StatusIndicator } from "@/components/ui/status-indicator";
import WorkspaceLink from "@/components/WorkspaceLink";
import { getStreamEventById } from "@/lib/api";
import { processingProgress } from "@/lib/eventFeed";
import { optionalApiData } from "@/lib/server-resource";
import { sourceTypeBySlug, type SourceType } from "@/lib/sourceTypes";
import { getStreamOutcomeStatusPresentation } from "@/lib/status";
import { formatDateTime } from "@/utils/dateUtils";
import {
  EventEnvelope,
  EventPayload,
  type Translator,
} from "../../[streamId]/components/EventDetail";
import {
  eventHref,
  feedHref as streamFeedHref,
} from "../../[streamId]/feedHref";
import ProcessingPill from "./ProcessingPill";

/** The event open in the side panel: its envelope, each subscriber's answer, its body. */
export default async function FeedEventPanel({
  eventId,
  streamNames,
  sourceTypes,
}: {
  eventId: string;
  streamNames: Map<string, string>;
  sourceTypes: SourceType[];
}) {
  const [t, tDetail, tFilter, locale, result] = await Promise.all([
    getTranslations("EventsPage"),
    getTranslations("EventsPage.detail"),
    getTranslations("EventsPage.filter"),
    getLocale(),
    getStreamEventById(eventId),
  ]);
  const event = optionalApiData(result, "stream event");

  if (!event) {
    return (
      <>
        <InfoPanelHeader
          className="pr-10"
          label={t("panel.title")}
          title={<span className="font-mono">{eventId.slice(0, 8)}</span>}
        />
        <InfoPanelBody>
          <p className="py-6 text-center text-muted-foreground">
            {t("panel.gone")}
          </p>
        </InfoPanelBody>
      </>
    );
  }

  const progress = event.processing
    ? processingProgress(event.processing)
    : null;

  return (
    <>
      <InfoPanelHeader
        className="pr-10"
        label={`${streamNames.get(event.stream_id) ?? t("list.unknownStream")} · ${formatDateTime(event.received_at, locale)}`}
        title={event.kind}
        right={
          event.processing && (
            <ProcessingPill
              processing={event.processing}
              receivedAt={event.received_at}
              now={null}
            />
          )
        }
      />
      <InfoPanelBody>
        <EventEnvelope
          event={event}
          sourceType={sourceTypeBySlug(sourceTypes, event.source_type)}
          locale={locale}
          t={tDetail}
        />
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
        {event.causation_id && (
          <div className="text-muted-foreground">
            {tDetail("causedBy")}:{" "}
            <WorkspaceLink
              href={eventHref(event.causation_id)}
              className="font-mono text-primary hover:underline"
              title={event.causation_id}
            >
              {event.causation_id.slice(0, 8)}
            </WorkspaceLink>
          </div>
        )}
        <EventPayload event={event} t={tDetail} />
        <WorkspaceLink
          href={streamFeedHref(event.stream_id, {
            outcome: "all",
            event: event.sequence,
          })}
          className="inline-block text-primary hover:underline"
        >
          {t("panel.openInStream")}
        </WorkspaceLink>
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
  if (handlers.length === 0 && pending === 0) {
    return <p className="p-3 text-muted-foreground">{t("panel.noHandlers")}</p>;
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
                      href={eventHref(id)}
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

"use client";

import type { ReactNode } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { Hash, Paperclip, RefreshCw } from "lucide-react";
import type {
  HandlerResponse,
  StreamEventDetailResponse,
} from "@/api/client/types.gen";
import FormError from "@/components/FormError/FormError";
import {
  InfoPanelBody,
  InfoPanelField,
  InfoPanelHeader,
  InfoPanelRow,
  InfoPanelSection,
  InfoPanelValueBox,
} from "@/components/InfoPanel";
import SourceTypeMark from "@/components/SourceTypeMark";
import ActionLink from "@/components/TaskInfoPanel/components/ActionLink";
import { TaskStatus } from "@/components/TaskStatus";
import { Button } from "@/components/ui/button";
import { CopyableText } from "@/components/ui/copyable-text";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { StatusIndicator } from "@/components/ui/status-indicator";
import WorkspaceLink from "@/components/WorkspaceLink";
import { useWorkspacePathname } from "@/hooks/useWorkspaceNavigation";
import { deterministicHue } from "@/lib/avatar-hue";
import { EntityIcon, type EntityKind } from "@/lib/entity-icons";
import { PLATFORM_SOURCE_TYPE, processingProgress } from "@/lib/eventFeed";
import { sourceTypeBySlug, type SourceType } from "@/lib/sourceTypes";
import { getStreamOutcomeStatusPresentation } from "@/lib/status";
import { parseUtcTimestamp } from "@/utils/dateUtils";
import { formatFileSize } from "@/utils/fileUtils";
import ProcessingPill from "./ProcessingPill";

type Translator = ReturnType<typeof useTranslations>;

const HANDLER_ICON: Record<HandlerResponse["kind"], EntityKind> = {
  trigger: "trigger",
  forward: "stream",
  processor: "tool",
  deleted: "trigger",
};

/**
 * The event open in the side panel, built as the task panel is: the header
 * (stream, kind, result), its details as fields, the subscribers that took
 * it as rows, its body, and a way to its stream.
 */
export default function FeedEventPanel({
  eventId,
  event,
  error,
  onRetry,
  streams,
  sourceTypes,
}: {
  eventId: string;
  /** Null when the event is no longer kept. */
  event: StreamEventDetailResponse | null;
  /** Reading the event failed. */
  error?: string;
  onRetry?: () => void;
  streams: { id: string; name: string }[];
  sourceTypes: SourceType[];
}) {
  const t = useTranslations("EventsPage");
  const tDetail = useTranslations("EventsPage.detail");
  const tFilter = useTranslations("EventsPage.filter");
  const tCommon = useTranslations("Common");
  const format = useFormatter();
  const searchParams = useSearchParams();
  // Another event (a cause, a forward) opens in this same panel, the feed
  // and its filters left as they are.
  const pathname = useWorkspacePathname();
  const openEvent = (id: string) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("event", id);
    return `${pathname}?${params.toString()}`;
  };
  const when = (value: string | null | undefined) => {
    const date = parseUtcTimestamp(value);
    return date
      ? format.dateTime(date, { dateStyle: "medium", timeStyle: "short" })
      : null;
  };

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
  const streamName =
    streams.find((s) => s.id === event.stream_id)?.name ??
    t("list.unknownStream");
  const sourceType = sourceTypeBySlug(sourceTypes, event.source_type);
  const occurred = when(event.occurred_at);
  // The platform writes what a task did; its cause is that task (the id it
  // carries as causation is the task's own event, not an event of a stream).
  const platformTask =
    event.source_type === PLATFORM_SOURCE_TYPE
      ? taskIdOf(event.data)
      : undefined;

  return (
    <>
      <InfoPanelHeader
        className="pr-10"
        label={streamName}
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
        <InfoPanelSection
          title={t("panel.details")}
          contentClassName="space-y-3 text-xs"
        >
          <InfoPanelField label={tDetail("source")}>
            <InfoPanelValueBox>
              <span className="flex min-w-0 items-center gap-1.5">
                <SourceTypeMark
                  type={sourceType}
                  slug={event.source_type}
                  inline
                  className="h-3.5 w-3.5 shrink-0"
                />
                <span className="truncate">
                  {event.source_type
                    ? (sourceType?.name ?? event.source_type)
                    : tDetail("noSource")}
                </span>
              </span>
            </InfoPanelValueBox>
          </InfoPanelField>
          <InfoPanelField label={tDetail("key")} icon={Hash}>
            <CopyableText text={event.key} />
          </InfoPanelField>
          <InfoPanelField label={tDetail("session")}>
            {event.session_key ? (
              <CopyableText text={event.session_key} />
            ) : (
              <p className="text-muted-foreground">{tDetail("noSession")}</p>
            )}
          </InfoPanelField>
          {event.sender && (
            <InfoPanelField label={tDetail("sender")}>
              <InfoPanelValueBox mono>{event.sender}</InfoPanelValueBox>
            </InfoPanelField>
          )}
          <Facts
            facts={[
              [t("panel.received"), when(event.received_at)],
              [tDetail("occurredAt"), occurred],
            ]}
          />
          {platformTask ? (
            <InfoPanelField label={t("panel.task")}>
              <InfoPanelValueBox mono href={`/tasks/${platformTask}`}>
                {platformTask.slice(0, 8)}
              </InfoPanelValueBox>
            </InfoPanelField>
          ) : (
            event.causation_id && (
              <InfoPanelField label={tDetail("causedBy")}>
                <InfoPanelValueBox mono href={openEvent(event.causation_id)}>
                  {event.causation_id.slice(0, 8)}
                </InfoPanelValueBox>
              </InfoPanelField>
            )
          )}
        </InfoPanelSection>

        <InfoPanelSection
          title={t("panel.handlers")}
          contentClassName="space-y-0.5 text-xs"
        >
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
            openEvent={openEvent}
            t={t}
            tFilter={tFilter}
          />
        </InfoPanelSection>

        {event.attachments.length > 0 && (
          <InfoPanelSection
            title={tDetail("attachments")}
            contentClassName="space-y-0.5 text-xs"
          >
            {event.attachments.map((file, index) => (
              <InfoPanelRow
                key={`${file.sha256}-${index}`}
                avatar={
                  <Paperclip className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                }
                name={file.name}
                sub={
                  file.url
                    ? [
                        file.mime,
                        file.size != null && formatFileSize(file.size),
                      ]
                        .filter(Boolean)
                        .join(" · ")
                    : tDetail("fetchedByTask")
                }
                href={file.url ?? undefined}
                newTab
              />
            ))}
          </InfoPanelSection>
        )}

        <InfoPanelSection title={tDetail("data")} contentClassName="p-0">
          {typeof event.data.body_ref === "string" && (
            <p className="border-b border-border px-3 py-2">
              {event.body_url ? (
                <a
                  href={event.body_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:underline"
                >
                  {tDetail("bodyStored")}
                </a>
              ) : (
                <span className="text-muted-foreground">
                  {tDetail("bodyStored")}
                </span>
              )}
            </p>
          )}
          <pre className="max-h-96 overflow-auto p-3 font-mono text-[11px] leading-relaxed">
            {JSON.stringify(event.data, null, 2)}
          </pre>
        </InfoPanelSection>

        {/* On its own stream's page the event is already in its stream. */}
        {pathname !== `/events/${event.stream_id}` && (
          <ActionLink
            href={`/events/${event.stream_id}?event=${event.event_id}`}
          >
            {t("panel.openInStream")}
          </ActionLink>
        )}
      </InfoPanelBody>
    </>
  );
}

/** The task a platform event is about, from the body the platform wrote. */
function taskIdOf(data: StreamEventDetailResponse["data"]): string | undefined {
  const body = data.body;
  if (typeof body !== "object" || body === null) return undefined;
  const id = (body as Record<string, unknown>).task_id;
  return typeof id === "string" && id !== "" ? id : undefined;
}

/** Label and value side by side, for the plain values (dates). */
function Facts({ facts }: { facts: [string, ReactNode][] }) {
  const shown = facts.filter(([, value]) => value != null);
  if (shown.length === 0) return null;
  return (
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1">
      {shown.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {label}
          </dt>
          <dd className="min-w-0 text-foreground">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Handlers({
  handlers,
  pending,
  status,
  triggers,
  openEvent,
  t,
  tFilter,
}: {
  handlers: HandlerResponse[];
  pending: number;
  status: string | undefined;
  /** The trigger behind each trigger subscription, to link its name. */
  triggers: Map<string, string>;
  openEvent: (id: string) => string;
  t: Translator;
  tFilter: Translator;
}) {
  if (status === "queued") {
    return <p className="text-muted-foreground">{t("panel.queued")}</p>;
  }
  if (handlers.length === 0 && pending === 0) {
    return <p className="text-muted-foreground">{t("panel.noHandlers")}</p>;
  }
  return (
    <>
      {handlers.map((handler) => {
        const verdict = getStreamOutcomeStatusPresentation(handler.verdict);
        const triggerId = triggers.get(handler.subscription_id);
        return (
          <InfoPanelRow
            key={handler.subscription_id}
            avatar={
              <EntityAvatar
                size={24}
                hue={deterministicHue(handler.subscription_id)}
                icon={<EntityIcon kind={HANDLER_ICON[handler.kind]} />}
                aria-hidden
              />
            }
            name={handler.name}
            sub={handler.reason ?? t(`panel.${handler.kind}`)}
            href={triggerId ? `/triggers/${triggerId}` : undefined}
            trailing={
              <StatusIndicator
                size="sm"
                kind={verdict.kind}
                className="shrink-0"
              >
                {verdict.labelKey ? tFilter(verdict.labelKey) : verdict.label}
              </StatusIndicator>
            }
          >
            {(handler.task_id || handler.derived_event_ids.length > 0) && (
              <div className="ml-8 mt-1 space-y-1">
                {handler.task_id && (
                  <InfoPanelValueBox href={`/tasks/${handler.task_id}`}>
                    <span className="flex items-center gap-2">
                      {t("panel.task")}
                      {handler.task_status && (
                        <TaskStatus status={handler.task_status} />
                      )}
                    </span>
                  </InfoPanelValueBox>
                )}
                {handler.derived_event_ids.length > 0 && (
                  <p className="flex flex-wrap items-center gap-1 text-muted-foreground">
                    {t("panel.derived")}:
                    {handler.derived_event_ids.map((id) => (
                      <WorkspaceLink
                        key={id}
                        href={openEvent(id)}
                        scroll={false}
                        className="font-mono text-primary hover:underline"
                        title={id}
                      >
                        {id.slice(0, 8)}
                      </WorkspaceLink>
                    ))}
                  </p>
                )}
              </div>
            )}
          </InfoPanelRow>
        );
      })}
      {pending > 0 && (
        <p className="pt-1 text-muted-foreground">
          {t("panel.pending", { count: pending })}
        </p>
      )}
    </>
  );
}

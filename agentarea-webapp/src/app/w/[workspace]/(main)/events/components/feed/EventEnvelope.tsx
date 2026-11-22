"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import type { StreamEventResponse } from "@/api/client/types.gen";
import CopyContentsButton from "@/components/CopyContentsButton";
import EventTime from "@/components/EventTime";
import { TextPreview } from "@/components/files/text-preview";
import SourceTypeMark from "@/components/SourceTypeMark";
import WorkspaceLink from "@/components/WorkspaceLink";
import { eventByIdHref } from "@/lib/eventFeed";
import type { SourceType } from "@/lib/sourceTypes";
import { formatFileSize } from "@/utils/fileUtils";

const DETAILS = "group rounded-md border border-zinc-200 dark:border-zinc-700";
const SUMMARY =
  "cursor-pointer select-none px-3 py-2 text-xs uppercase tracking-wide text-muted-foreground";

/**
 * What a source recorded wraps the request in `headers` and `body`; an event
 * the platform or a processor wrote is its data as it stands.
 */
function wrapsRequest(data: StreamEventResponse["data"]): boolean {
  return "body" in data || "headers" in data;
}

/** The request's body as the sender made it, wrapped to the panel; a stored body links to its file. */
export function EventBody({ event }: { event: StreamEventResponse }) {
  const t = useTranslations("EventsPage.detail");
  const stored = typeof event.data.body_ref === "string";
  const body = wrapsRequest(event.data) ? event.data.body : event.data;
  const text =
    body == null
      ? ""
      : typeof body === "string"
        ? body
        : JSON.stringify(body, null, 2);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs uppercase tracking-wide text-muted-foreground">
          {t("data")}
        </h3>
        {!stored && text && <CopyContentsButton text={text} />}
      </div>
      {stored ? (
        <p className="text-sm">
          {event.body_url ? (
            <a
              href={event.body_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary hover:underline"
            >
              {t("bodyStored")}
            </a>
          ) : (
            <span className="text-muted-foreground">{t("bodyStored")}</span>
          )}
          <span className="ml-2 break-all font-mono text-xs text-muted-foreground">
            {String(event.data.body_ref)}
          </span>
        </p>
      ) : text ? (
        <div className="max-h-96 overflow-y-auto">
          <TextPreview
            path={typeof body === "string" ? "body.txt" : "body.json"}
            text={text}
            wrap
          />
        </div>
      ) : (
        <p className="text-muted-foreground">{t("emptyBody")}</p>
      )}
    </div>
  );
}

/** The request's headers, folded: rarely what one opens an event for. */
export function EventHeaders({ event }: { event: StreamEventResponse }) {
  const t = useTranslations("EventsPage.detail");
  const raw = event.data.headers;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const headers = Object.entries(raw as Record<string, unknown>);
  if (headers.length === 0) return null;
  return (
    <details className={DETAILS}>
      <summary className={SUMMARY}>
        {t("headers", { count: headers.length })}
      </summary>
      <dl className="space-y-1 border-t border-zinc-200 px-3 py-2 dark:border-zinc-700">
        {headers.map(([name, value]) => (
          <div key={name} className="break-all font-mono text-xs">
            <dt className="inline text-muted-foreground">{name}:</dt>{" "}
            <dd className="inline">{String(value)}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

/** The files that came with the event. */
export function EventAttachments({ event }: { event: StreamEventResponse }) {
  const t = useTranslations("EventsPage.detail");
  if (event.attachments.length === 0) return null;
  return (
    <div>
      <h3 className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
        {t("attachments")}
      </h3>
      <ul className="space-y-1">
        {event.attachments.map((file, index) => (
          <li
            key={`${file.sha256}-${index}`}
            className="card-item flex items-center justify-between gap-3 px-3 py-2"
          >
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{file.name}</p>
              <p className="note truncate">
                {[file.mime, file.size != null && formatFileSize(file.size)]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </div>
            {file.url ? (
              <a
                href={file.url}
                target="_blank"
                rel="noopener noreferrer"
                className="shrink-0 text-xs text-primary hover:underline"
              >
                {t("openAttachment")}
              </a>
            ) : (
              <span className="note shrink-0">{t("fetchedByTask")}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * The envelope every event has, whatever sent it (ADR-0040 §2), folded: which
 * catalog entry it came through, its key, session and sender, when it
 * happened and what caused it. Nothing is parsed out of the provider's body.
 */
export function EventFacts({
  event,
  sourceType,
}: {
  event: StreamEventResponse;
  sourceType: SourceType | undefined;
}) {
  const t = useTranslations("EventsPage.detail");
  const mono = (value: string) => (
    <span className="break-all font-mono text-xs">{value}</span>
  );
  const facts: { label: string; value: ReactNode; title?: string }[] = [
    {
      label: t("source"),
      value: event.source_type ? (
        <span className="flex min-w-0 items-center gap-1.5">
          <SourceTypeMark type={sourceType} inline className="h-3.5 w-3.5" />
          <span className="truncate">
            {sourceType?.name ?? event.source_type}
          </span>
        </span>
      ) : (
        t("noSource")
      ),
    },
    { label: t("key"), value: mono(event.key), title: t("keyHint") },
    {
      label: t("session"),
      value: event.session_key ? (
        mono(event.session_key)
      ) : (
        <span title={t("noSessionHint")}>{t("noSession")}</span>
      ),
    },
    ...(event.sender
      ? [{ label: t("sender"), value: mono(event.sender) }]
      : []),
    ...(event.occurred_at
      ? [
          {
            label: t("occurredAt"),
            value: <EventTime value={event.occurred_at} style="full" />,
          },
        ]
      : []),
    ...(event.causation_id
      ? [
          {
            label: t("causedBy"),
            value: (
              <WorkspaceLink
                href={eventByIdHref(event.causation_id)}
                className="font-mono text-xs text-primary hover:underline"
                title={event.causation_id}
              >
                {event.causation_id.slice(0, 8)}
              </WorkspaceLink>
            ),
          },
        ]
      : []),
  ];

  return (
    <details className={DETAILS}>
      <summary className={SUMMARY}>{t("details")}</summary>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 border-t border-zinc-200 px-3 py-2 text-sm dark:border-zinc-700">
        {facts.map((fact) => (
          <div key={fact.label} className="contents">
            <dt className="text-muted-foreground" title={fact.title}>
              {fact.label}
            </dt>
            <dd className="min-w-0">{fact.value}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

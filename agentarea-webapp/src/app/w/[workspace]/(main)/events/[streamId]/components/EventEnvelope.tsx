import type { ReactNode } from "react";
import type { StreamEventResponse } from "@/api/client/types.gen";
import SourceTypeMark from "@/components/SourceTypeMark";
import type { SourceType } from "@/lib/sourceTypes";
import { formatDateTime } from "@/utils/dateUtils";
import { formatFileSize } from "@/utils/fileUtils";

/** A next-intl translator, from the server or a client component. */
export type EventTranslator = (key: string) => string;

/** The request as the sender made it: a stored body links to its file. */
export function EventPayload({
  event,
  t,
}: {
  event: StreamEventResponse;
  t: EventTranslator;
}) {
  return (
    <div>
      <h3 className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
        {t("data")}
      </h3>
      {typeof event.data.body_ref === "string" && (
        <p className="mb-2 text-sm">
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
            {event.data.body_ref}
          </span>
        </p>
      )}
      <pre className="max-h-96 overflow-auto rounded-md bg-muted/50 p-3 text-xs">
        {JSON.stringify(event.data, null, 2)}
      </pre>
    </div>
  );
}

/**
 * The envelope every event has, whatever sent it (ADR-0040 §2): which catalog
 * entry it came through, its kind, key, session and sender, and its files.
 * Nothing is parsed out of the provider's body; that stays in the payload.
 */
export function EventEnvelope({
  event,
  sourceType,
  locale,
  t,
}: {
  event: StreamEventResponse;
  sourceType: SourceType | undefined;
  locale: string;
  t: EventTranslator;
}) {
  const facts: { label: string; value: ReactNode }[] = [
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
    { label: t("kind"), value: event.kind },
    {
      label: t("key"),
      value: <span className="break-all font-mono text-xs">{event.key}</span>,
    },
    {
      label: t("session"),
      value: event.session_key ? (
        <span className="break-all font-mono text-xs">{event.session_key}</span>
      ) : (
        t("noSession")
      ),
    },
    ...(event.sender
      ? [
          {
            label: t("sender"),
            value: (
              <span className="break-all font-mono text-xs">
                {event.sender}
              </span>
            ),
          },
        ]
      : []),
    ...(event.occurred_at
      ? [
          {
            label: t("occurredAt"),
            value: formatDateTime(event.occurred_at, locale),
          },
        ]
      : []),
  ];

  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-sm">
        {facts.map((fact) => (
          <div key={fact.label} className="contents">
            <dt className="text-muted-foreground">{fact.label}</dt>
            <dd className="min-w-0">{fact.value}</dd>
          </div>
        ))}
      </dl>
      {event.attachments.length > 0 && (
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
      )}
    </div>
  );
}

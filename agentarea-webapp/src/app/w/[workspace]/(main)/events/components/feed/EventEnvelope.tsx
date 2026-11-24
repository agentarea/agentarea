"use client";

import { useTranslations } from "next-intl";
import type { StreamEventResponse } from "@/api/client/types.gen";
import CopyContentsButton from "@/components/CopyContentsButton";
import { TextPreview } from "@/components/files/text-preview";

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

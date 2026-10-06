"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown, ChevronRight } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import Table from "@/components/Table/Table";
import { TableDateDisplay } from "@/components/Table/TableDateDisplay";
import { Button } from "@/components/ui/button";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { useOnVisible } from "@/hooks/use-on-visible";
import {
  fetchAuditLogs,
  type AuditEvent,
  type AuditLogFilters as AuditQuery,
} from "./actions";
import { AuditAction, AuditActor, AuditResource } from "./AuditCells";
import { AuditChangeList } from "./AuditChangeList";

/** Metadata keys worth a line under the resource, with their label keys. */
const DETAIL_KEYS = ["tool", "decision", "reason", "comment"] as const;

function AuditDetails({ event }: { event: AuditEvent }) {
  const t = useTranslations("AuditLogPage.details");
  const metadata = event.event_metadata ?? {};
  const argumentKeys = Array.isArray(metadata.argument_keys)
    ? metadata.argument_keys.filter((key) => typeof key === "string")
    : [];
  const details = DETAIL_KEYS.flatMap((key) => {
    const value = metadata[key];
    return typeof value === "string" && value ? [{ key, value }] : [];
  });
  if (details.length === 0 && argumentKeys.length === 0) return null;

  return (
    <dl className="mt-1 space-y-0.5 text-xs text-muted-foreground">
      {details.map(({ key, value }) => (
        <div key={key} className="flex min-w-0 gap-1">
          <dt className="shrink-0">{t(key)}:</dt>
          <dd className="min-w-0 break-words text-foreground/80">
            {key === "tool" ? (
              <span className="font-mono">{value}</span>
            ) : (
              value
            )}
          </dd>
        </div>
      ))}
      {argumentKeys.length > 0 && (
        <div className="flex min-w-0 gap-1">
          <dt className="shrink-0">{t("arguments")}:</dt>
          <dd className="min-w-0 break-words font-mono text-foreground/80">
            {argumentKeys.join(", ")}
          </dd>
        </div>
      )}
    </dl>
  );
}

/** The resource, what the event recorded about it, and its changes when open. */
function ResourceCell({
  event,
  expanded,
}: {
  event: AuditEvent;
  expanded: boolean;
}) {
  return (
    <div className="min-w-0">
      <AuditResource event={event} />
      <div className="pl-[38px]">
        <AuditDetails event={event} />
        {expanded && event.changes && event.changes.length > 0 && (
          <AuditChangeList changes={event.changes} className="mt-2 space-y-1" />
        )}
      </div>
    </div>
  );
}

interface Props {
  initialEvents: AuditEvent[];
  initialCursor: string | null;
  /** The API query the page loaded with, for the next pages. */
  query: AuditQuery;
  filtered: boolean;
}

export default function AuditLogClient({
  initialEvents,
  initialCursor,
  query,
  filtered,
}: Props) {
  const t = useTranslations("AuditLogPage");
  const tCommon = useTranslations("Common");
  const [events, setEvents] = useState<AuditEvent[]>(initialEvents);
  const [cursor, setCursor] = useState<string | null>(initialCursor);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const loadMore = () => {
    if (!cursor || isPending) return;
    startTransition(async () => {
      const { data, error } = await fetchAuditLogs({
        ...query,
        cursor,
        limit: 50,
      });
      if (!data) {
        setLoadMoreError(error);
        return;
      }
      setLoadMoreError(null);
      setEvents((prev) => [...prev, ...data.events]);
      setCursor(data.next_cursor ?? null);
    });
  };

  const sentinelRef = useOnVisible(loadMore, {
    enabled: Boolean(cursor) && !isPending && !loadMoreError,
  });

  const columns = [
    {
      accessor: "expand",
      header: "",
      cellClassName: "w-6 pr-0",
      render: (_: unknown, event: AuditEvent) => {
        if (!event.changes?.length) return null;
        const Chevron = expandedId === event.id ? ChevronDown : ChevronRight;
        return <Chevron className="h-3.5 w-3.5 text-muted-foreground/70" />;
      },
    },
    {
      accessor: "action",
      header: t("table.action"),
      cellClassName: "w-[180px]",
      render: (value: string) => <AuditAction action={value} />,
    },
    {
      accessor: "resource",
      header: t("table.resource"),
      render: (_: unknown, event: AuditEvent) => (
        <ResourceCell event={event} expanded={expandedId === event.id} />
      ),
    },
    {
      accessor: "actor_id",
      header: t("table.actor"),
      cellClassName: "w-[220px] max-w-[240px]",
      render: (_: unknown, event: AuditEvent) => <AuditActor event={event} />,
    },
    {
      accessor: "source_ip",
      header: t("table.ip"),
      cellClassName: "w-[120px]",
      render: (value: string | null) => (
        <span className="font-mono text-xs text-muted-foreground">
          {value || "—"}
        </span>
      ),
    },
    {
      accessor: "created_at",
      header: t("table.when"),
      cellClassName: "w-[130px]",
      render: (value: string) => (
        <TableDateDisplay dateString={value} relative />
      ),
    },
  ];

  return (
    <>
      {events.length === 0 ? (
        <EmptyState
          title={filtered ? t("noMatches") : t("noEvents")}
          iconsType="audit"
        />
      ) : (
        <Table
          data={events.map((event) => ({
            ...event,
            // Only a row with changes opens, so only that row says it can.
            className: event.changes?.length ? undefined : "cursor-default",
          }))}
          columns={columns}
          onRowClick={(event: AuditEvent) => {
            if (!event.changes?.length) return;
            setExpandedId(expandedId === event.id ? null : event.id);
          }}
        />
      )}

      {/* The next page loads as the end of the list scrolls into view. After a
          failure it waits for a retry instead of asking again on every scroll. */}
      {cursor && (
        <div
          ref={sentinelRef}
          className="flex min-h-12 flex-col items-center justify-center gap-2 pt-4"
        >
          {loadMoreError ? (
            <>
              <p role="alert" className="text-sm text-destructive">
                {loadMoreError}
              </p>
              <Button variant="outline" size="sm" onClick={loadMore}>
                {tCommon("retry")}
              </Button>
            </>
          ) : (
            isPending && (
              <StatusIndicator
                kind="running"
                aria-label={t("loadingMore")}
                title={t("loadingMore")}
              />
            )
          )}
        </div>
      )}
    </>
  );
}

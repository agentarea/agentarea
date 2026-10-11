"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown, ChevronRight } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import LoadMoreSentinel from "@/components/LoadMoreSentinel";
import Table from "@/components/Table/Table";
import { TableDateDisplay } from "@/components/Table/TableDateDisplay";
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

  const columns = [
    {
      accessor: "expand",
      header: "",
      cellClassName: "w-6 pr-0",
      render: (_: unknown, event: AuditEvent) => {
        if (!event.changes?.length) return null;
        const expanded = expandedId === event.id;
        const Chevron = expanded ? ChevronDown : ChevronRight;
        // Its own control: a click on the rest of the row opens the resource.
        return (
          <button
            type="button"
            aria-expanded={expanded}
            aria-label={t(expanded ? "hideChanges" : "showChanges")}
            onClick={(e) => {
              e.stopPropagation();
              setExpandedId(expanded ? null : event.id);
            }}
            className="-m-1 grid h-6 w-6 place-items-center rounded text-muted-foreground/70 hover:bg-muted hover:text-foreground"
          >
            <Chevron className="h-3.5 w-3.5" />
          </button>
        );
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
      rowLink: true,
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
          data={events}
          columns={columns}
          // A row leads to its resource, like a row in any other table.
          rowHref={(event: AuditEvent) => event.resource?.href ?? ""}
        />
      )}

      <LoadMoreSentinel
        hasMore={Boolean(cursor)}
        pending={isPending}
        error={loadMoreError}
        onLoadMore={loadMore}
      />
    </>
  );
}

"use client";

import { createElement, useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import Link from "@/components/WorkspaceLink";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import Table from "@/components/Table/Table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  exportAuditLogs,
  fetchAuditLogs,
  type AuditActorOption,
  type AuditEvent,
  type AuditLogFilters as AuditLogFiltersQuery,
} from "./actions";
import { AuditChangeList } from "./AuditChangeList";
import { auditEventsToCsv } from "./auditCsv";
import {
  ALL,
  AuditLogFilters,
  EMPTY_FILTERS,
  isFiltered,
  type AuditFilterState,
} from "./AuditLogFilters";
import {
  auditActorIcon,
  auditResourceIcon,
  auditVerbIcon,
} from "./auditIcons";
import { auditActionColor, auditVerb, formatAuditTime } from "./format";

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

function ResourceCell({ event }: { event: AuditEvent }) {
  const resource = event.resource;
  const label = resource?.label ?? event.resource_type;
  const typeLabel = resource?.type_label ?? event.resource_type;
  const icon = auditResourceIcon(event.resource_type);

  return (
    <div className="min-w-0">
      <div className="flex min-w-0 items-center gap-2">
        {icon &&
          createElement(icon, {
            "aria-hidden": true,
            className: "h-4 w-4 shrink-0 text-muted-foreground",
          })}
        {resource?.href ? (
          <Link
            href={resource.href ?? ""}
            className="truncate text-sm font-medium text-zinc-800 underline-offset-2 hover:text-primary hover:underline dark:text-zinc-100"
            onClick={(e) => e.stopPropagation()}
          >
            {label}
          </Link>
        ) : (
          <span className="truncate text-sm font-medium text-zinc-800 dark:text-zinc-100">
            {label}
          </span>
        )}
        <Badge variant="zinc" size="sm" className="shrink-0 font-normal">
          {typeLabel}
        </Badge>
      </div>
      {event.resource_id && !resource?.found && (
        <div className="mt-0.5 font-mono text-xs text-muted-foreground">
          {event.resource_id}
        </div>
      )}
      {event.resource_id && resource?.found && (
        <div className="mt-0.5 font-mono text-xs text-muted-foreground">
          {event.resource_id.slice(0, 8)}
        </div>
      )}
      <AuditDetails event={event} />
      {event.changes && event.changes.length > 0 && (
        <AuditChangeList changes={event.changes} className="mt-2 space-y-1" />
      )}
    </div>
  );
}

function ActorCell({ event }: { event: AuditEvent }) {
  const actor = event.actor;
  const label = actor?.label ?? event.actor_id;
  const description = actor?.description;
  const icon = auditActorIcon(actor?.actor_type ?? event.actor_type);

  return (
    <div className="flex min-w-0 items-start gap-2">
      {createElement(icon, {
        "aria-hidden": true,
        className: "mt-0.5 h-4 w-4 shrink-0 text-muted-foreground",
      })}
      <div className="min-w-0">
        {actor?.href ? (
          <Link
            href={actor.href ?? ""}
            className="block truncate text-sm font-medium text-zinc-800 underline-offset-2 hover:text-primary hover:underline dark:text-zinc-100"
            onClick={(e) => e.stopPropagation()}
          >
            {label}
          </Link>
        ) : (
          <span className="block truncate text-sm font-medium text-zinc-800 dark:text-zinc-100">
            {label}
          </span>
        )}
        {description && (
          <span className="block truncate text-xs text-muted-foreground">
            {description}
          </span>
        )}
      </div>
    </div>
  );
}

interface Props {
  initialEvents: AuditEvent[];
  initialCursor: string | null;
  actorOptions: AuditActorOption[];
}

/** The API query a filter state stands for; dates cover whole local days. */
function toQuery(filters: AuditFilterState): AuditLogFiltersQuery {
  return {
    resource_type:
      filters.resourceType === ALL ? undefined : filters.resourceType,
    action: filters.action === ALL ? undefined : filters.action,
    actor_id: filters.actorId === ALL ? undefined : filters.actorId,
    since: filters.since
      ? new Date(`${filters.since}T00:00:00`).toISOString()
      : undefined,
    until: filters.until
      ? new Date(`${filters.until}T23:59:59.999`).toISOString()
      : undefined,
  };
}

export default function AuditLogClient({
  initialEvents,
  initialCursor,
  actorOptions,
}: Props) {
  const t = useTranslations("AuditLogPage");
  const [events, setEvents] = useState<AuditEvent[]>(initialEvents);
  const [cursor, setCursor] = useState<string | null>(initialCursor);
  const [filters, setFilters] = useState<AuditFilterState>(EMPTY_FILTERS);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
  const [exportNotice, setExportNotice] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const [isExporting, startExport] = useTransition();

  const applyFilters = (next: AuditFilterState) => {
    setFilters(next);
    setExpandedId(null);
    startTransition(async () => {
      const { data, error } = await fetchAuditLogs({
        ...toQuery(next),
        limit: 50,
      });
      if (!data) {
        setLoadMoreError(error);
        return;
      }
      setLoadMoreError(null);
      setEvents(data.events);
      setCursor(data.next_cursor ?? null);
    });
  };

  const loadMore = () => {
    if (!cursor) return;
    startTransition(async () => {
      const { data, error } = await fetchAuditLogs({
        ...toQuery(filters),
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

  const exportCsv = () => {
    setExportNotice(null);
    startExport(async () => {
      const { data, error } = await exportAuditLogs(toQuery(filters));
      if (!data) {
        setExportNotice(`${t("export.failed")}: ${error}`);
        return;
      }
      const blob = new Blob([auditEventsToCsv(data.events)], {
        type: "text/csv;charset=utf-8",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `audit-log-${new Date().toISOString().slice(0, 10)}.csv`;
      link.click();
      URL.revokeObjectURL(url);
      if (data.truncated) {
        setExportNotice(t("export.truncated", { count: data.events.length }));
      }
    });
  };

  const filterBar = (
    <AuditLogFilters
      value={filters}
      onChange={applyFilters}
      actorOptions={actorOptions}
      onExport={exportCsv}
      exporting={isExporting}
    />
  );

  const columns = [
    {
      accessor: "expand",
      header: "",
      cellClassName: "w-8 pr-0",
      render: (_: unknown, event: AuditEvent) => {
        const isExpanded = expandedId === event.id;
        const hasChanges = event.changes && event.changes.length > 0;
        return hasChanges ? (
          isExpanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
          )
        ) : null;
      },
    },
    {
      accessor: "action",
      header: t("table.action"),
      cellClassName: "w-[140px]",
      render: (value: string) => {
        const verb = auditVerb(value);
        const verbIcon = auditVerbIcon(verb);
        return (
          <Badge
            variant="secondary"
            className={`gap-1 text-xs font-mono ${auditActionColor(value)}`}
            title={value}
          >
            {verbIcon &&
              createElement(verbIcon, {
                "aria-hidden": true,
                className: "h-3 w-3",
              })}
            {verb || value}
          </Badge>
        );
      },
    },
    {
      accessor: "resource",
      header: t("table.resource"),
      cellClassName: "",
      render: (_: unknown, event: AuditEvent) => (
        <ResourceCell
          event={{
            ...event,
            changes:
              expandedId === event.id ? (event.changes ?? null) : null,
          }}
        />
      ),
    },
    {
      accessor: "actor_id",
      header: t("table.actor"),
      cellClassName: "w-[180px] max-w-[220px]",
      render: (_value: string, event: AuditEvent) => (
        <ActorCell event={event} />
      ),
    },
    {
      accessor: "source_ip",
      header: t("table.ip"),
      cellClassName: "w-[100px]",
      render: (value: string | null) => (
        <span className="text-xs text-muted-foreground font-mono">
          {value || "-"}
        </span>
      ),
    },
    {
      accessor: "created_at",
      header: t("table.when"),
      cellClassName: "w-[100px] text-right",
      render: (value: string) => (
        <span className="text-xs text-muted-foreground">
          {formatAuditTime(value)}
        </span>
      ),
    },
  ];

  return (
    <>
      {filterBar}
      {exportNotice && (
        <p role="status" className="mb-3 text-sm text-muted-foreground">
          {exportNotice}
        </p>
      )}
      {events.length === 0 ? (
        <EmptyState
          title={isFiltered(filters) ? t("noMatches") : t("noEvents")}
          iconsType="audit"
        />
      ) : (
        <Table
          data={events.map((event) => ({
            ...event,
            className: "hover:bg-zinc-50 dark:hover:bg-zinc-800/50",
          }))}
          columns={columns}
          onRowClick={(event: AuditEvent) =>
            setExpandedId(expandedId === event.id ? null : event.id)
          }
        />
      )}

      {loadMoreError && (
        <p role="alert" className="mt-4 text-center text-sm text-destructive">
          {loadMoreError}
        </p>
      )}

      {cursor && (
        <div className="flex justify-center mt-4">
          <Button
            variant="outline"
            size="sm"
            onClick={loadMore}
            disabled={isPending}
          >
            {isPending ? (
              <Loader2 className="mr-2 animate-spin" />
            ) : null}
            {t("loadMore")}
          </Button>
        </div>
      )}
    </>
  );
}

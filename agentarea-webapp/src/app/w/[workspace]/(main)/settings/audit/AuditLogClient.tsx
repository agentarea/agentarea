"use client";

import { createElement, useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import Link from "@/components/WorkspaceLink";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import Table from "@/components/Table/Table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fetchAuditLogs, type AuditEvent } from "./actions";
import {
  auditActorIcon,
  auditResourceIcon,
  auditVerbIcon,
} from "./auditIcons";
import { auditActionColor, auditVerb, formatAuditTime } from "./format";

function ChangesDetail({ changes }: { changes: AuditEvent["changes"] }) {
  if (!changes || changes.length === 0) return null;

  return (
    <div className="mt-2 space-y-1">
      {changes.map((change, i) => (
        <div key={i} className="text-xs font-mono">
          <span className="text-muted-foreground">
            {String(change.field ?? "unknown")}:
          </span>{" "}
          <span className="text-red-500 line-through">
            {String(change.before ?? "null")}
          </span>{" "}
          <span className="text-emerald-600">
            {String(change.after ?? "null")}
          </span>
        </div>
      ))}
    </div>
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
      {event.changes && event.changes.length > 0 && (
        <ChangesDetail changes={event.changes} />
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
}

export default function AuditLogClient({
  initialEvents,
  initialCursor,
}: Props) {
  const t = useTranslations("AuditLogPage");
  const [events, setEvents] = useState<AuditEvent[]>(initialEvents);
  const [cursor, setCursor] = useState<string | null>(initialCursor);
  const [resourceFilter] = useState("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const loadMore = () => {
    if (!cursor) return;
    startTransition(async () => {
      const { data, error } = await fetchAuditLogs({
        resource_type: resourceFilter === "all" ? undefined : resourceFilter,
        cursor,
        limit: 50,
      });
      if (!data) {
        setLoadMoreError(error);
        return;
      }
      setLoadMoreError(null);
      setEvents((prev) => [...prev, ...data.events]);
      setCursor(data.next_cursor);
    });
  };

  if (events.length === 0) {
    return <EmptyState title={t("noEvents")} iconsType="audit" />;
  }

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
            changes: expandedId === event.id ? event.changes : undefined,
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

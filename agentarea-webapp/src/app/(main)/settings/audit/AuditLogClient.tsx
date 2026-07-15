"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import Table from "@/components/Table/Table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fetchAuditLogs, type AuditEvent } from "./actions";

const ACTION_COLORS: Record<string, string> = {
  create:
    "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400",
  update: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400",
  delete: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400",
};

function getActionColor(action: string): string {
  const verb = action.split(".").pop() || "";
  return (
    ACTION_COLORS[verb] ||
    "bg-zinc-100 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-300"
  );
}

function formatTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays}d ago`;

  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

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

  return (
    <div className="min-w-0">
      <div className="flex min-w-0 items-center gap-2">
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

  return (
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
  );
}

interface Props {
  initialEvents: AuditEvent[];
  initialCursor: string | null;
  initialError: string | null;
}

export default function AuditLogClient({
  initialEvents,
  initialCursor,
  initialError,
}: Props) {
  const t = useTranslations("AuditLogPage");
  const [events, setEvents] = useState<AuditEvent[]>(initialEvents);
  const [cursor, setCursor] = useState<string | null>(initialCursor);
  const [resourceFilter] = useState("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const loadMore = () => {
    if (!cursor) return;
    startTransition(async () => {
      const { data } = await fetchAuditLogs({
        resource_type: resourceFilter === "all" ? undefined : resourceFilter,
        cursor,
        limit: 50,
      });
      if (data) {
        setEvents((prev) => [...prev, ...data.events]);
        setCursor(data.next_cursor);
      }
    });
  };

  if (initialError) {
    return (
      <EmptyState
        title={t("enterpriseFeature")}
        description={t("enterpriseDescription")}
        iconsType="audit"
      />
    );
  }

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
      render: (value: string) => (
        <Badge
          variant="secondary"
          className={`text-xs font-mono ${getActionColor(value)}`}
        >
          {value}
        </Badge>
      ),
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
          {formatTime(value)}
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

      {cursor && (
        <div className="flex justify-center mt-4">
          <Button
            variant="outline"
            size="sm"
            onClick={loadMore}
            disabled={isPending}
          >
            {isPending ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : null}
            {t("loadMore")}
          </Button>
        </div>
      )}
    </>
  );
}

"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown, ChevronRight, Filter, Loader2 } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import Table from "@/components/Table/Table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
  const [resourceFilter, setResourceFilter] = useState("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const resourceTypes = [
    { value: "all", label: t("filter.all") },
    { value: "agent", label: t("filter.agent") },
    { value: "mcp_server", label: t("filter.mcp_server") },
    { value: "mcp_instance", label: t("filter.mcp_instance") },
    { value: "task", label: t("filter.task") },
    { value: "trigger", label: t("filter.trigger") },
    { value: "skill", label: t("filter.skill") },
  ];

  const applyFilter = (resourceType: string) => {
    setResourceFilter(resourceType);
    startTransition(async () => {
      const { data } = await fetchAuditLogs({
        resource_type: resourceType === "all" ? undefined : resourceType,
        limit: 50,
      });
      if (data) {
        setEvents(data.events);
        setCursor(data.next_cursor);
      }
    });
  };

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
        <div>
          <span className="text-sm">{event.resource_type}</span>
          {event.resource_id && (
            <span className="text-xs text-muted-foreground ml-1.5 font-mono">
              {event.resource_id.slice(0, 8)}
            </span>
          )}
          {expandedId === event.id &&
            event.changes &&
            event.changes.length > 0 && (
              <ChangesDetail changes={event.changes} />
            )}
        </div>
      ),
    },
    {
      accessor: "actor_id",
      header: t("table.actor"),
      cellClassName: "w-[120px]",
      render: (value: string) => (
        <span className="text-sm truncate max-w-[120px] block">
          {value.length > 12 ? value.slice(0, 12) + "..." : value}
        </span>
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

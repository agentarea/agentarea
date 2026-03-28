"use client";

import { useState, useTransition } from "react";
import {
  Filter,
  ChevronDown,
  ChevronRight,
  Loader2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { fetchAuditLogs, type AuditEvent } from "./actions";

const ACTION_COLORS: Record<string, string> = {
  create:
    "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400",
  update:
    "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400",
  delete:
    "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400",
};

function getActionColor(action: string): string {
  const verb = action.split(".").pop() || "";
  return ACTION_COLORS[verb] || "bg-zinc-100 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-300";
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
          <span className="text-muted-foreground">{change.field}:</span>{" "}
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

const RESOURCE_TYPES = [
  { value: "all", label: "All resources" },
  { value: "agent", label: "Agents" },
  { value: "mcp_server", label: "MCP Servers" },
  { value: "mcp_instance", label: "MCP Instances" },
  { value: "task", label: "Tasks" },
  { value: "trigger", label: "Triggers" },
  { value: "skill", label: "Skills" },
];

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
  const [events, setEvents] = useState<AuditEvent[]>(initialEvents);
  const [cursor, setCursor] = useState<string | null>(initialCursor);
  const [resourceFilter, setResourceFilter] = useState("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

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
      <div className="p-6">
        <h2 className="text-lg font-semibold mb-4">Audit Log</h2>
        <div className="rounded-lg border border-zinc-200 dark:border-zinc-700 p-8 text-center text-muted-foreground">
          <p>Audit logging is available on Enterprise plans.</p>
          <p className="text-sm mt-1">
            Track who did what, when, and from where across your workspace.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-lg font-semibold">Audit Log</h2>
          <p className="text-sm text-muted-foreground">
            Track changes across your workspace
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-muted-foreground" />
          <Select value={resourceFilter} onValueChange={applyFilter}>
            <SelectTrigger className="w-[160px] h-8 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RESOURCE_TYPES.map((rt) => (
                <SelectItem key={rt.value} value={rt.value}>
                  {rt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {events.length === 0 ? (
        <div className="rounded-lg border border-zinc-200 dark:border-zinc-700 p-8 text-center text-muted-foreground">
          No audit events found.
        </div>
      ) : (
        <>
          <div className="rounded-lg border border-zinc-200 dark:border-zinc-700 overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="bg-zinc-50 dark:bg-zinc-900/50">
                  <TableHead className="w-8" />
                  <TableHead className="w-[140px]">Action</TableHead>
                  <TableHead>Resource</TableHead>
                  <TableHead className="w-[120px]">Actor</TableHead>
                  <TableHead className="w-[100px]">IP</TableHead>
                  <TableHead className="w-[100px] text-right">When</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {events.map((event) => {
                  const isExpanded = expandedId === event.id;
                  const hasChanges =
                    event.changes && event.changes.length > 0;

                  return (
                    <TableRow
                      key={event.id}
                      className="cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
                      onClick={() =>
                        setExpandedId(isExpanded ? null : event.id)
                      }
                    >
                      <TableCell className="pr-0">
                        {hasChanges &&
                          (isExpanded ? (
                            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                          ) : (
                            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                          ))}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="secondary"
                          className={`text-xs font-mono ${getActionColor(event.action)}`}
                        >
                          {event.action}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <div>
                          <span className="text-sm">
                            {event.resource_type}
                          </span>
                          {event.resource_id && (
                            <span className="text-xs text-muted-foreground ml-1.5 font-mono">
                              {event.resource_id.slice(0, 8)}
                            </span>
                          )}
                        </div>
                        {isExpanded && hasChanges && (
                          <ChangesDetail changes={event.changes} />
                        )}
                      </TableCell>
                      <TableCell>
                        <span className="text-sm truncate max-w-[120px] block">
                          {event.actor_id.length > 12
                            ? event.actor_id.slice(0, 12) + "..."
                            : event.actor_id}
                        </span>
                      </TableCell>
                      <TableCell>
                        <span className="text-xs text-muted-foreground font-mono">
                          {event.source_ip || "-"}
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        <span className="text-xs text-muted-foreground">
                          {formatTime(event.created_at)}
                        </span>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>

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
                Load more
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

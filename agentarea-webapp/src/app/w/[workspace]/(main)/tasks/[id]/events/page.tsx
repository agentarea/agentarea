"use client";

import { useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Search,
  RefreshCw,
} from "lucide-react";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useTaskEvents } from "@/lib/events/useTaskEvents";
import type { DisplayEvent, EventLevel } from "@/types/events";
import { useTaskContext } from "../TaskContext";

const eventLevelKinds: Record<EventLevel, "active" | "attention" | "done" | "failed"> = {
  info: "active",
  success: "done",
  warning: "attention",
  error: "failed",
};

function EventRow({ event, index }: { event: DisplayEvent; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const ts = event.timestamp;
  const time = ts
    ? `${ts.getHours().toString().padStart(2, "0")}:${ts.getMinutes().toString().padStart(2, "0")}:${ts.getSeconds().toString().padStart(2, "0")}.${ts.getMilliseconds().toString().padStart(3, "0")}`
    : "no timestamp";

  return (
    <>
      <tr
        className="border-b border-border/50 hover:bg-muted/30 cursor-pointer text-xs"
        onClick={() => setExpanded(!expanded)}
      >
        <td className="px-2 py-1.5 text-muted-foreground tabular-nums w-8">
          {index + 1}
        </td>
        <td className="px-2 py-1.5 text-muted-foreground tabular-nums whitespace-nowrap w-24">
          {time}
        </td>
        <td className="px-2 py-1.5 whitespace-nowrap w-40">
          <code className="text-xs">{event.type}</code>
        </td>
        <td className="px-2 py-1.5 w-16">
          <StatusIndicator kind={eventLevelKinds[event.level]} size="sm">
            {event.level}
          </StatusIndicator>
        </td>
        <td className="px-2 py-1.5 truncate max-w-md">
          {event.description}
        </td>
        <td className="px-2 py-1.5 w-6 text-muted-foreground">
          {event.data && Object.keys(event.data).length > 0 &&
            (expanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            ))}
        </td>
      </tr>
      {expanded && event.data && Object.keys(event.data).length > 0 && (
        <tr className="border-b border-border/50">
          <td colSpan={6} className="px-2 py-2 bg-muted/20">
            <pre className="text-[11px] font-mono whitespace-pre-wrap text-muted-foreground overflow-x-auto max-h-64 overflow-y-auto">
              {JSON.stringify(event.data, null, 2)}
            </pre>
          </td>
        </tr>
      )}
    </>
  );
}

export default function TaskEventsPage() {
  const { task, loading } = useTaskContext();
  const [search, setSearch] = useState("");
  const [levelFilter, setLevelFilter] = useState<EventLevel | "all">("all");

  const {
    rawEvents: events,
    loading: eventsLoading,
    error: eventsError,
    connected,
    refresh: refreshEvents,
  } = useTaskEvents(task?.agent_id || null, task?.id || null, {
    includeHistory: true,
    autoConnect: true,
  });

  const filtered = useMemo(() => {
    return events.filter((e) => {
      if (levelFilter !== "all" && e.level !== levelFilter) return false;
      if (
        search &&
        !e.type.toLowerCase().includes(search.toLowerCase()) &&
        !e.description.toLowerCase().includes(search.toLowerCase()) &&
        !JSON.stringify(e.data || {})
          .toLowerCase()
          .includes(search.toLowerCase())
      )
        return false;
      return true;
    });
  }, [events, search, levelFilter]);

  if (loading) {
    return (
      <div className="main-content space-y-2 p-4" aria-hidden="true">
        {Array.from({ length: 10 }).map((_, i) => (
          <div
            key={i}
            className="flex items-center gap-3 border-b border-zinc-100 py-2.5 dark:border-zinc-800"
          >
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-4 flex-1" />
            <Skeleton className="h-4 w-24" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="main-content space-y-3 p-4">
      {/* Toolbar */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Filter events..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8 h-8 text-xs"
          />
        </div>
        <div className="flex items-center gap-1">
          {(["all", "info", "success", "warning", "error"] as const).map(
            (level) => (
              <Button
                key={level}
                variant={levelFilter === level ? "default" : "outline"}
                size="sm"
                className="h-7 text-xs px-2"
                onClick={() => setLevelFilter(level)}
              >
                {level === "all" ? "All" : level}
              </Button>
            )
          )}
        </div>
        <div className="flex items-center gap-2">
          <StatusIndicator
            kind={connected ? "active" : "failed"}
            size="sm"
            aria-label={connected ? "Live" : "Offline"}
            title={connected ? "Live" : "Offline"}
          >
            {connected ? "Live" : "Offline"}
          </StatusIndicator>
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={refreshEvents}
            disabled={eventsLoading}
          >
            <RefreshCw
              className={`mr-1 ${eventsLoading ? "animate-spin" : ""}`}
            />
            Refresh
          </Button>
        </div>
      </div>

      {/* Count */}
      <div className="text-xs text-muted-foreground">
        {filtered.length} of {events.length} events
        {search || levelFilter !== "all" ? " (filtered)" : ""}
      </div>

      {/* Error */}
      {eventsError && (
        <div className="rounded bg-red-50 p-2 text-xs dark:bg-red-900/20">
          <StatusIndicator kind="failed" size="sm">
            {eventsError}
          </StatusIndicator>
        </div>
      )}

      {/* Table */}
      <div className="border rounded-md overflow-hidden">
        <div className="overflow-auto max-h-[calc(100vh-280px)]">
          <table className="w-full">
            <thead className="sticky top-0 bg-muted/80 backdrop-blur-sm">
              <tr className="text-xs text-muted-foreground font-medium">
                <th className="px-2 py-2 text-left w-8">#</th>
                <th className="px-2 py-2 text-left w-24">Time</th>
                <th className="px-2 py-2 text-left w-40">Event Type</th>
                <th className="px-2 py-2 text-left w-16">Level</th>
                <th className="px-2 py-2 text-left">Description</th>
                <th className="px-2 py-2 w-6"></th>
              </tr>
            </thead>
            <tbody>
              {eventsLoading && filtered.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-8">
                    <div className="flex items-center justify-center text-xs text-muted-foreground">
                      <StatusIndicator kind="running" size="sm">
                        Loading events...
                      </StatusIndicator>
                    </div>
                  </td>
                </tr>
              ) : filtered.length === 0 ? (
                <tr>
                  <td
                    colSpan={6}
                    className="py-8 text-center text-muted-foreground text-xs"
                  >
                    {eventsError ? "Could not load events." : "No events found."}
                  </td>
                </tr>
              ) : (
                filtered.map((event, index) => (
                  <EventRow key={event.id} event={event} index={index} />
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

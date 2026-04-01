"use client";

import { useMemo, useState } from "react";
import {
  Activity,
  ChevronDown,
  ChevronRight,
  Search,
  RefreshCw,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { useTaskEvents } from "@/hooks/useTaskEvents";
import type { DisplayEvent, EventLevel } from "@/types/events";
import { useTaskContext } from "../TaskContext";

const levelColors: Record<EventLevel, string> = {
  info: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
  success:
    "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300",
  warning:
    "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300",
  error: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300",
};

function EventRow({ event, index }: { event: DisplayEvent; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const ts = event.timestamp;
  const time = `${ts.getHours().toString().padStart(2, "0")}:${ts.getMinutes().toString().padStart(2, "0")}:${ts.getSeconds().toString().padStart(2, "0")}.${ts.getMilliseconds().toString().padStart(3, "0")}`;

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
          <Badge
            className={`text-[10px] px-1.5 py-0 font-normal ${levelColors[event.level]}`}
          >
            {event.level}
          </Badge>
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
    events,
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
      <div className="flex h-full items-center justify-center">
        <LoadingSpinner />
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
          <div className="flex items-center gap-1.5">
            <div
              className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-green-500" : "bg-red-400"}`}
            />
            <span className="text-[10px] text-muted-foreground">
              {connected ? "Live" : "Offline"}
            </span>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={refreshEvents}
            disabled={eventsLoading}
          >
            <RefreshCw
              className={`h-3 w-3 mr-1 ${eventsLoading ? "animate-spin" : ""}`}
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
        <div className="text-xs text-red-500 bg-red-50 dark:bg-red-900/20 rounded p-2">
          {eventsError}
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
                    <div className="flex items-center justify-center gap-2 text-muted-foreground text-xs">
                      <Activity className="h-4 w-4 animate-spin" />
                      Loading events...
                    </div>
                  </td>
                </tr>
              ) : filtered.length === 0 ? (
                <tr>
                  <td
                    colSpan={6}
                    className="py-8 text-center text-muted-foreground text-xs"
                  >
                    No events found.
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

"use client";

import { LoadingSpinner } from "@/components/LoadingSpinner";
import EventsDisplay from "@/components/TaskEvents/EventsDisplay";
import { useTaskEvents } from "@/hooks/useTaskEvents";
import { useTaskContext } from "../TaskContext";

export default function TaskEventsPage() {
  const { task, loading } = useTaskContext();

  const {
    events,
    loading: eventsLoading,
    error: eventsError,
    connected: eventsConnected,
    refresh: refreshEvents,
  } = useTaskEvents(task?.agent_id || null, task?.id || null, {
    includeHistory: true,
    autoConnect: true,
  });

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  return (
    <EventsDisplay
      events={events}
      loading={eventsLoading}
      error={eventsError}
      connected={eventsConnected}
      onRefresh={refreshEvents}
      showFilters={true}
      showStats={true}
      maxHeight="600px"
    />
  );
}


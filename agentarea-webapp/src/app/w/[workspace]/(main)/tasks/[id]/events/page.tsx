"use client";

import { useTaskEvents } from "@/lib/events/useTaskEvents";
import { useTaskContext } from "../TaskContext";
import TaskEventsView from "./TaskEventsView";

export default function TaskEventsPage() {
  const { task, loading } = useTaskContext();
  const {
    rawEvents: events,
    loading: eventsLoading,
    error,
    connected,
    refresh,
  } = useTaskEvents(task?.agent_id || null, task?.id || null, {
    includeHistory: true,
    autoConnect: true,
  });

  return (
    <TaskEventsView
      events={events}
      loading={loading || (eventsLoading && events.length === 0)}
      refreshing={eventsLoading}
      error={error}
      connected={connected}
      onRefresh={refresh}
    />
  );
}

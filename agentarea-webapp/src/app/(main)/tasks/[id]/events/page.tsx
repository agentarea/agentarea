"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import EventsDisplay from "@/components/TaskEvents/EventsDisplay";
import { useTaskEvents } from "@/hooks/useTaskEvents";

interface TaskBasic {
  id: string;
  agent_id: string;
}

export default function TaskEventsPage() {
  const params = useParams();
  const id = Array.isArray(params.id) ? params.id[0] : (params.id as string);

  const [task, setTask] = useState<TaskBasic | null>(null);
  const [loading, setLoading] = useState(true);

  const loadTask = useCallback(async () => {
    try {
      setLoading(true);
      const { getAllTasks } = await import("@/lib/browser-api");
      const { data: allTasks } = await getAllTasks();
      const foundTask = allTasks?.find((t: any) => t.id?.toString() === id);
      if (foundTask) {
        setTask({
          id: foundTask.id.toString(),
          agent_id: foundTask.agent_id.toString(),
        });
      }
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    loadTask();
  }, [loadTask]);

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
      <div className="p-8">
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


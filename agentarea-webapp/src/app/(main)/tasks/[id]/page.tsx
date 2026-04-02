"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { UserMessage as UserMessageComponent } from "@/components/Chat/componets/UserMessage";
import { parseEventToMessage, shouldDisplayEvent } from "@/components/Chat/EventParser";
import { MessageRenderer } from "@/components/Chat/MessageComponents";
import type { MessageComponentType } from "@/components/Chat/types";
import { normalizeEventType } from "@/components/Chat/utils/eventNormalizer";
import EmptyState from "@/components/EmptyState";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import TaskInfoPanel from "@/components/TaskInfoPanel/TaskInfoPanel";
import TaskInfoPanelDock from "@/components/TaskInfoPanel/TaskInfoPanelDock";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useTaskEvents } from "@/hooks/useTaskEvents";
import {
  cancelAgentTaskAction as cancelAgentTask,
  pauseAgentTaskAction as pauseAgentTask,
  resumeAgentTaskAction as resumeAgentTask,
} from "@/lib/server-actions";
import { resolveEscalationAction } from "@/lib/server-actions";
import { useTaskContext } from "./TaskContext";

export default function TaskDetailsPage() {
  const { task, taskStatus, loading, error, refresh } = useTaskContext();

  const [refreshing, setRefreshing] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [showCancelDialog, setShowCancelDialog] = useState(false);

  const handleResolveEscalation = async (escalationId: string, approved: boolean, comment: string) => {
    if (!task) return;
    try {
      await resolveEscalationAction(task.agent_id, task.id, escalationId, approved, comment);
      refresh();
    } catch (e) {
      console.error("Failed to resolve escalation:", e);
    }
  };

  // Events hook for real-time events + historical replay
  const {
    events: taskEvents,
    loading: eventsLoading,
    refresh: refreshEvents,
  } = useTaskEvents(task?.agent_id || null, task?.id || null, {
    includeHistory: true,
    autoConnect: true,
  });

  // FIXME: Performance — this useMemo re-processes ALL events on every render whenever
  // taskEvents or task changes. Each event goes through normalizeEventType → shouldDisplayEvent →
  // parseEventToMessage (a large switch statement). For long-running tasks with many events
  // this becomes O(n) per render. Should accumulate incrementally: keep a processed array
  // and only parse newly appended events rather than replaying the full list each time.
  // Convert historical events to chat message components for direct rendering
  const executionMessages = useMemo((): MessageComponentType[] => {
    if (!task) return [];

    const messages: MessageComponentType[] = [];

    for (const event of taskEvents) {
      const eventType = normalizeEventType(event.type);
      if (!shouldDisplayEvent(eventType)) continue;

      const eventData = {
        ...(event.data || {}),
        task_id: task.id,
        agent_id: task.agent_id,
        timestamp: event.timestamp.toISOString(),
      };

      const message = parseEventToMessage(eventType, eventData);
      if (message) {
        messages.push(message);
      }
    }

    return messages;
  }, [task, taskEvents]);

  // Auto-scroll to bottom when new messages arrive
  const messagesEndRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [executionMessages.length]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await refresh();
    await refreshEvents();
    setRefreshing(false);
  };

  // Task control handlers
  const handlePauseTask = async () => {
    if (!task) return;

    try {
      setControlling(true);
      const { error } = await pauseAgentTask(task.agent_id, task.id);

      if (error) {
        const errorMessage =
          error.detail?.[0]?.msg || "An error occurred while pausing the task";
        toast.error("Failed to pause task", {
          description: errorMessage,
        });
      } else {
        toast.success("Task paused successfully");
        // Refresh task data to get updated status
        await refresh();
      }
    } catch (err) {
      toast.error("Failed to pause task", {
        description: "An unexpected error occurred",
      });
    } finally {
      setControlling(false);
    }
  };

  const handleResumeTask = async () => {
    if (!task) return;

    try {
      setControlling(true);
      const { error } = await resumeAgentTask(task.agent_id, task.id);

      if (error) {
        const errorMessage =
          error.detail?.[0]?.msg || "An error occurred while resuming the task";
        toast.error("Failed to resume task", {
          description: errorMessage,
        });
      } else {
        toast.success("Task resumed successfully");
        // Refresh task data to get updated status
        await refresh();
      }
    } catch (err) {
      toast.error("Failed to resume task", {
        description: "An unexpected error occurred",
      });
    } finally {
      setControlling(false);
    }
  };

  const handleCancelTask = async () => {
    if (!task) return;

    try {
      setControlling(true);
      const { error } = await cancelAgentTask(task.agent_id, task.id);

      if (error) {
        const errorMessage =
          error.detail?.[0]?.msg ||
          (error as any).message ||
          "An error occurred while cancelling the task";
        toast.error("Failed to cancel task", {
          description: errorMessage,
        });
      } else {
        toast.success("Task cancelled successfully");
        // Refresh task data to get updated status
        await refresh();
      }
    } catch (err) {
      toast.error("Failed to cancel task", {
        description: "An unexpected error occurred",
      });
    } finally {
      setControlling(false);
      setShowCancelDialog(false);
    }
  };

  // Show loading state
  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  // Show error state
  if (error || !task) {
    return (
      <EmptyState
        title={error ? "Error Loading Task" : "Task Not Found"}
        description={error || "The requested task could not be found."}
        iconsType="tasks"
        action={{ label: "Back to Tasks", href: "/tasks" }}
        additionAction={{ label: "Try Again", onClick: handleRefresh }}
      />
    );
  }

  // Determine if task is active based on status
  const isActive = ["running", "paused", "blocked"].includes(task.status);

  // Get current status from taskStatus or fallback to task.status
  const currentStatus = taskStatus?.status || task.status;
  const executionTime = taskStatus?.execution_time || "N/A";
  const startTime = taskStatus?.start_time || task.created_at || "";
  const endTime = taskStatus?.end_time;

  return (
    <>
      <div className="flex h-full w-full">
        {/* Left side - Execution history */}
        <div className="flex-1 flex flex-col h-full">
          <div className="relative flex-1 overflow-auto">
            <div className="absolute inset-0 bg-[url('/lines.png')] dark:bg-[url('/lines-dark.png')] bg-[size:450px_450px] bg-center bg-repeat opacity-20 pointer-events-none" />
            <div className="relative z-1 space-y-3 px-3 py-5">
              {/* Task description as user message */}
              {task.description && (
                <UserMessageComponent
                  id={`task-${task.id}-desc`}
                  content={task.description}
                  timestamp={task.created_at || new Date().toISOString()}
                />
              )}

              {/* Loading state */}
              {eventsLoading && (
                <div className="flex items-center justify-center py-8">
                  <LoadingSpinner />
                </div>
              )}

              {/* Execution events rendered directly */}
              {executionMessages.map((message, index) => (
                <MessageRenderer
                  key={`${message.data.id}-${message.data.event_type}-${index}`}
                  message={message}
                  agent_name={task.agent_name || undefined}
                  onResolveEscalation={handleResolveEscalation}
                />
              ))}

              {/* Empty state */}
              {!eventsLoading && executionMessages.length === 0 && (
                <div className="flex items-center justify-center py-8 text-muted-foreground text-sm">
                  No execution events yet.
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>
          </div>
        </div>

        <TaskInfoPanelDock
          storageKey="task-info-panel"
          panel={
            <TaskInfoPanel
              task={{
                id: task.id,
                description: task.description || "",
                agent_id: task.agent_id,
                agent_name: task.agent_name,
                agent_description: task.agent_description,
                created_at: task.created_at || "",
                execution_id: task.execution_id || null,
                result: task.result,
              }}
              currentStatus={currentStatus}
              isActive={isActive}
              startTime={startTime}
              endTime={endTime}
              executionTime={executionTime}
            />
          }
        />
      </div>

      {/* Cancel Confirmation Dialog */}
      <Dialog open={showCancelDialog} onOpenChange={setShowCancelDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Cancel Task</DialogTitle>
            <DialogDescription>
              Are you sure you want to cancel this task? This action cannot be
              undone and will terminate the task execution immediately.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline" disabled={controlling}>
                Keep Running
              </Button>
            </DialogClose>
            <Button
              variant="destructive"
              onClick={handleCancelTask}
              disabled={controlling}
            >
              {controlling ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Cancelling...
                </>
              ) : (
                <>
                  <X className="mr-2 h-4 w-4" />
                  Cancel Task
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

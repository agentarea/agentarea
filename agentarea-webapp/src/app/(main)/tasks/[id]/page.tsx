"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Send, X } from "lucide-react";
import { toast } from "sonner";
import { ChatInputArea } from "@/components/Chat/componets/ChatInputArea";
import { UserMessage as UserMessageComponent } from "@/components/Chat/componets/UserMessage";
import { MessageRenderer } from "@/components/Chat/MessageComponents";
import type { MessageComponentType } from "@/components/Chat/types";
import { processEventsToMessages } from "@/components/Chat/utils/eventProcessor";
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
  sendTaskCommandAction as sendTaskCommand,
} from "@/lib/server-actions";
import { resolveEscalationAction } from "@/lib/server-actions";
import { useTaskContext } from "./TaskContext";

export default function TaskDetailsPage() {
  const { task, taskStatus, loading, error, refresh } = useTaskContext();
  const router = useRouter();

  const [refreshing, setRefreshing] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [showCancelDialog, setShowCancelDialog] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [sendingMessage, setSendingMessage] = useState(false);
  const [optimisticMessages, setOptimisticMessages] = useState<MessageComponentType[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  // Convert historical events to chat message components using shared processor
  const executionMessages = useMemo((): MessageComponentType[] => {
    if (!task) return [];

    const processed = processEventsToMessages(
      taskEvents.map((e) => ({
        type: e.type,
        timestamp: e.timestamp,
        data: e.data,
      })),
      { taskId: task.id, agentId: task.agent_id }
    );

    // Merge optimistic messages, filtering out any that have been confirmed by events
    const confirmedContents = new Set(
      processed
        .filter((m) => m.type === "user_message")
        .map((m) => (m.data as any).content)
    );
    const pendingOptimistic = optimisticMessages.filter(
      (m) => !confirmedContents.has((m.data as any).content)
    );

    return [...processed, ...pendingOptimistic];
  }, [task, taskEvents, optimisticMessages]);

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

  // Chat input handler
  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!chatInput.trim() || !task || sendingMessage) return;

    const message = chatInput.trim();
    setChatInput("");
    setSendingMessage(true);

    try {
      if (isActive) {
        // Optimistically show user message immediately
        setOptimisticMessages((prev) => [
          ...prev,
          {
            type: "user_message",
            data: {
              id: `optimistic-${Date.now()}`,
              timestamp: new Date().toISOString(),
              agent_id: task.agent_id,
              event_type: "MessageQueued",
              content: message,
            },
          },
        ]);

        const { error } = await sendTaskCommand(task.agent_id, task.id, {
          command: "queue_message",
          message: message,
        });
        if (error) {
          toast.error("Failed to send message");
          // Remove optimistic message on error
          setOptimisticMessages((prev) =>
            prev.filter((m) => (m.data as any).content !== message)
          );
        }
      } else {
        // Task is completed — create a new task for the same agent
        const response = await fetch(`/api/agents/${task.agent_id}/tasks/create`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            description: message,
            parameters: {
              context: {},
              task_type: "chat",
              session_id: `chat-${Date.now()}`,
            },
            enable_agent_communication: true,
          }),
        });

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        // Extract task_id from the SSE stream to navigate
        const reader = response.body?.getReader();
        if (reader) {
          const decoder = new TextDecoder();
          let newTaskId: string | null = null;
          let done = false;
          while (!done) {
            const { value, done: readerDone } = await reader.read();
            done = readerDone;
            if (value) {
              const text = decoder.decode(value, { stream: true });
              const match = text.match(/"task_id"\s*:\s*"([^"]+)"/);
              if (match && !newTaskId) {
                newTaskId = match[1];
              }
            }
          }
          if (newTaskId) {
            router.push(`/tasks/${newTaskId}`);
            return;
          }
        }
        toast.error("Failed to create new task");
      }
    } catch (err) {
      console.error("Failed to send message:", err);
      toast.error("Failed to send message", {
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setSendingMessage(false);
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setChatInput(e.target.value);
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
  // Completed tasks stay alive (workflow waits for follow-ups), so we always use queue_message
  const isActive = ["running", "paused", "blocked", "completed"].includes(task.status);

  // Get current status from taskStatus or fallback to task.status
  const currentStatus = taskStatus?.status || task.status;
  const executionTime = taskStatus?.execution_time || "N/A";
  const startTime = taskStatus?.start_time || task.created_at || "";
  const endTime = taskStatus?.end_time;

  return (
    <>
      <div className="flex h-full w-full">
        {/* Left side - Execution history + chat input */}
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

          {/* Chat input */}
          <div className="border-t bg-background px-3 py-3">
            <ChatInputArea
              input={chatInput}
              onInputChange={handleInputChange}
              onSubmit={handleSendMessage}
              isLoading={sendingMessage}
              placeholder={
                isActive
                  ? `Message ${task.agent_name || "agent"}...`
                  : `Send a follow-up to ${task.agent_name || "agent"}...`
              }
              selectedFiles={[]}
              onRemoveFile={() => {}}
              onOpenFileDialog={() => {}}
              fileInputRef={fileInputRef}
              textareaRef={textareaRef}
              variant="default"
              sendButtonIcon="send"
              rows={1}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSendMessage(e);
                }
              }}
            />
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

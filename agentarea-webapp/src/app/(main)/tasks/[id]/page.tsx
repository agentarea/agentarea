"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Play, X } from "lucide-react";
import { toast } from "sonner";
import { ChatInputArea } from "@/components/Chat/componets/ChatInputArea";
import { UserMessage as UserMessageComponent } from "@/components/Chat/componets/UserMessage";
import type { HumanInputSecretValue } from "@/components/Chat/types";
import EmptyState from "@/components/EmptyState";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { buildActivitySummary } from "@/components/TaskInfoPanel/buildActivitySummary";
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
import { Skeleton } from "@/components/ui/skeleton";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { useTaskActions } from "@/hooks/useTaskActions";
import { PartRenderer } from "@/lib/events/parts/PartRenderer";
import { useTaskEvents } from "@/lib/events/useTaskEvents";
import {
  cancelAgentTaskAction as cancelAgentTask,
  continueAgentTaskAction as continueAgentTask,
} from "@/lib/server-actions";
import { useTaskContext } from "./TaskContext";

// Statuses where the workflow is still alive and a free-text message should be
// queued for the next iteration rather than starting a new task. "completed" is
// included: a conversational task writes "completed" after each reply but stays
// alive in its follow-up window.
const QUEUEABLE_STATUSES = ["running", "paused", "blocked", "completed"];

export default function TaskDetailsPage() {
  const { task, taskStatus, policy, loading, error, refresh } =
    useTaskContext();
  const router = useRouter();

  const [, setRefreshing] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [showCancelDialog, setShowCancelDialog] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [sendingMessage, setSendingMessage] = useState(false);
  const [continuationIterations, setContinuationIterations] = useState("10");
  const [continuationBudget, setContinuationBudget] = useState("");
  const [continuing, setContinuing] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const status = taskStatus?.status || task?.status || "";
  const agentId = task?.agent_id || null;
  const taskId = task?.id || null;

  // Unified event core: one SSE hook folds history + live tail into ordered
  // parts (supersede-by-id), a lifecycle timeline, the single active form, and
  // the terminal message/status.
  const {
    parts,
    status: streamStatus,
    pendingForm,
    terminalMessage,
    loading: eventsLoading,
  } = useTaskEvents(agentId, taskId, {
    includeHistory: true,
    autoConnect: true,
  });

  const actions = useTaskActions(agentId, taskId);

  // Side-panel activity summary derived from the reduced parts.
  const activitySummary = useMemo(
    () => buildActivitySummary(parts, parts.length),
    [parts]
  );

  const isActive =
    QUEUEABLE_STATUSES.includes(status) || status === "waiting_for_input";
  // Whether the task is still executing, from the event stream (the record's
  // status can lag). Drives the info panel's live/idle indicators.
  const isRunning = streamStatus === "running";

  // Auto-scroll to bottom as parts arrive.
  const messagesEndRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [parts.length, terminalMessage]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await refresh();
    setRefreshing(false);
  };

  const handleCancelTask = async () => {
    if (!task) return;

    try {
      setControlling(true);
      const { error } = await cancelAgentTask(task.agent_id, task.id);

      if (error) {
        const errorMessage =
          error.detail?.[0]?.msg ||
          (error as { message?: string }).message ||
          "An error occurred while cancelling the task";
        toast.error("Failed to cancel task", {
          description: errorMessage,
        });
      } else {
        toast.success("Task cancelled successfully");
        await refresh();
      }
    } catch {
      toast.error("Failed to cancel task", {
        description: "An unexpected error occurred",
      });
    } finally {
      setControlling(false);
      setShowCancelDialog(false);
    }
  };

  const handleContinueTask = async () => {
    if (!taskId) return;
    const iterations = Number.parseInt(continuationIterations, 10);
    const budget = continuationBudget.trim();
    if (
      !Number.isInteger(iterations) ||
      iterations < 0 ||
      (iterations === 0 && !budget)
    ) {
      toast.error("Grant at least one iteration or a budget top-up.");
      return;
    }

    setContinuing(true);
    try {
      const { error: continuationError } = await continueAgentTask(
        taskId,
        iterations,
        budget || undefined
      );
      if (continuationError) {
        toast.error("Couldn't continue task", {
          description:
            "The task is no longer waiting, or the grant does not lift its limit.",
        });
        return;
      }
      toast.success("Task continued");
      await refresh();
    } catch {
      toast.error("Couldn't continue task", {
        description: "An unexpected error occurred.",
      });
    } finally {
      setContinuing(false);
    }
  };

  // Answer the single active form (input request) — resumes the workflow.
  const handleFormSubmit = useCallback(
    async (
      inputRequestId: string,
      answers: Record<string, unknown>,
      secrets: Record<string, HumanInputSecretValue>
    ) => {
      const { error } = await actions.submitInput(
        inputRequestId,
        answers,
        secrets
      );
      if (error) toast.error("Failed to submit response");
    },
    [actions]
  );

  // Free-text send routes by task state: answer a pending form, queue for a
  // live task, or start a follow-up task and navigate to it.
  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    const message = chatInput.trim();
    if (!message || sendingMessage) return;

    setChatInput("");
    setSendingMessage(true);
    try {
      if (pendingForm && pendingForm.eventType === "input.request") {
        const { error } = await actions.submitInput(
          pendingForm.partId,
          { answer: message },
          {}
        );
        if (error) toast.error("Failed to submit response");
        return;
      }

      if (QUEUEABLE_STATUSES.includes(status)) {
        const { error } = await actions.queueMessage(message);
        if (error) toast.error("Failed to send message");
        return;
      }

      const newTaskId = await actions.createFollowupTask(message);
      if (newTaskId) router.push(`/tasks/${newTaskId}`);
      else toast.error("Failed to create new task");
    } catch (err) {
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

  // Show loading state — chat-shaped placeholder (alternating message bubbles).
  if (loading) {
    return (
      <div
        className="mx-auto w-full max-w-3xl space-y-4 p-4"
        aria-hidden="true"
      >
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className={`flex ${i % 2 ? "justify-end" : "justify-start"}`}
          >
            <Skeleton
              className={`h-16 rounded-lg ${i % 2 ? "w-1/2" : "w-2/3"}`}
            />
          </div>
        ))}
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

  const currentStatus = taskStatus?.status || task.status;
  const executionTime = taskStatus?.execution_time || "N/A";
  const startTime = taskStatus?.start_time || task.created_at || "";
  const endTime = taskStatus?.end_time;

  // Budget display: spent cost lives in the task result, the limit in its parameters.
  const rawCost =
    (taskStatus?.result as Record<string, unknown> | undefined)?.total_cost ??
    task.result?.total_cost;
  const totalCost =
    rawCost != null && !Number.isNaN(Number(rawCost)) ? Number(rawCost) : null;
  const rawBudget =
    policy?.budget?.run_budget_usd ?? task.parameters?.budget_usd;
  const budgetLimit =
    rawBudget != null && !Number.isNaN(Number(rawBudget))
      ? Number(rawBudget)
      : null;

  const terminalTone =
    streamStatus === "failed"
      ? "danger"
      : streamStatus === "cancelled"
        ? "warning"
        : "success";

  // A successful task's answer already renders as the last assistant part, so a
  // terminal message that just repeats it would double up. Show the terminal
  // banner only when it adds something (a failure reason, or a completion whose
  // text isn't already in the transcript).
  const lastAssistantText = [...parts].reverse().find((p) => p.kind === "llm")
    ?.data?.content as string | undefined;
  const showTerminalMessage =
    !!terminalMessage &&
    terminalMessage.trim() !== (lastAssistantText || "").trim();

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

              {/* Ordered event parts (supersede-by-id → stable React keys). */}
              {parts.map((part) => (
                <PartRenderer
                  key={part.partId}
                  part={part}
                  onFormSubmit={handleFormSubmit}
                />
              ))}

              {/* Terminal message from the last lifecycle event (only when it
                  adds info beyond the last assistant part). */}
              {showTerminalMessage && (
                <StatusIndicator tone={terminalTone}>
                  {terminalMessage}
                </StatusIndicator>
              )}

              {/* Empty state */}
              {!eventsLoading && parts.length === 0 && !terminalMessage && (
                <div className="flex items-center justify-center py-8 text-muted-foreground text-sm">
                  No execution events yet.
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>
          </div>

          {/* Chat input — matches the workplace composer (borderless textarea
              inside a soft rounded card) so both surfaces look identical. */}
          <div className="border-t bg-background px-3 py-3">
            {currentStatus === "waiting_for_continuation" ? (
              <div className="space-y-3 rounded-2xl border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/30">
                <div>
                  <p className="text-sm font-medium text-amber-950 dark:text-amber-100">
                    The task reached its iteration or budget limit.
                  </p>
                  <p className="text-xs text-amber-800 dark:text-amber-300">
                    Grant only the resources you want it to use. It will wait
                    for up to 24 hours.
                  </p>
                </div>
                <div className="flex flex-wrap items-end gap-3">
                  <label className="space-y-1 text-xs font-medium">
                    Additional iterations
                    <input
                      className="block h-9 w-32 rounded-md border bg-background px-3 text-sm"
                      min="0"
                      max="1000"
                      type="number"
                      value={continuationIterations}
                      onChange={(event) =>
                        setContinuationIterations(event.target.value)
                      }
                    />
                  </label>
                  <label className="space-y-1 text-xs font-medium">
                    Budget top-up (USD, optional)
                    <input
                      className="block h-9 w-44 rounded-md border bg-background px-3 text-sm"
                      min="0.01"
                      step="0.01"
                      type="number"
                      value={continuationBudget}
                      onChange={(event) =>
                        setContinuationBudget(event.target.value)
                      }
                    />
                  </label>
                  <Button onClick={handleContinueTask} disabled={continuing}>
                    {continuing ? (
                      <Loader2 className="mr-2 animate-spin" />
                    ) : (
                      <Play className="mr-2" />
                    )}
                    Continue task
                  </Button>
                </div>
              </div>
            ) : (
              <div className="rounded-2xl border bg-white px-2 pb-2 pt-0 shadow-[0_8px_30px_rgb(0,0,0,0.04)] transition-all duration-500 ease-out hover:shadow-[0_20px_40px_rgb(0,0,0,0.06)] dark:border-zinc-800 dark:bg-zinc-900 dark:shadow-[0_8px_30px_rgb(0,0,0,0.2)]">
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
                  variant="centered"
                  rows={1}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      handleSendMessage(e);
                    }
                  }}
                />
              </div>
            )}
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
              isActive={isRunning}
              startTime={startTime}
              endTime={endTime}
              executionTime={executionTime}
              activitySummary={activitySummary}
              artifacts={taskStatus?.artifacts}
              totalCost={totalCost}
              budgetLimit={budgetLimit}
              policy={policy}
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
                  <Loader2 className="mr-2 animate-spin" />
                  Cancelling...
                </>
              ) : (
                <>
                  <X className="mr-2" />
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

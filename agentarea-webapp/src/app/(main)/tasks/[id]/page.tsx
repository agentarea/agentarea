"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { ChatInputArea } from "@/components/Chat/componets/ChatInputArea";
import { UserMessage as UserMessageComponent } from "@/components/Chat/componets/UserMessage";
import { MessageRenderer } from "@/components/Chat/MessageComponents";
import EmptyState from "@/components/EmptyState";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Skeleton } from "@/components/ui/skeleton";
import TaskInfoPanel from "@/components/TaskInfoPanel/TaskInfoPanel";
import TaskInfoPanelDock from "@/components/TaskInfoPanel/TaskInfoPanelDock";
import { buildActivitySummary } from "@/components/TaskInfoPanel/buildActivitySummary";
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
import { useTaskConversation } from "@/hooks/useTaskConversation";
import { cancelAgentTaskAction as cancelAgentTask } from "@/lib/server-actions";
import { useTaskContext } from "./TaskContext";

export default function TaskDetailsPage() {
  const { task, taskStatus, policy, loading, error, refresh } = useTaskContext();

  const [, setRefreshing] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [showCancelDialog, setShowCancelDialog] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [sendingMessage, setSendingMessage] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Single conversation stack: live event feed, derived messages (+ optimistic
  // echoes), and the full action set with state-aware send routing.
  const status = taskStatus?.status || task?.status || "";
  const {
    events: taskEvents,
    messages: executionMessages,
    loading: eventsLoading,
    isActive,
    refresh: refreshEvents,
    actions,
  } = useTaskConversation(task?.agent_id || null, task?.id || null, { status });

  // Side-panel activity summary (tools/skills used, failures, LLM calls)
  const activitySummary = useMemo(
    () => buildActivitySummary(executionMessages, taskEvents.length, taskEvents),
    [executionMessages, taskEvents]
  );

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

  // Chat input handler — routing (answer input / queue / new task) lives in the hook.
  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    const message = chatInput.trim();
    if (!message || sendingMessage) return;

    setChatInput("");
    setSendingMessage(true);
    try {
      await actions.sendMessage(message);
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
      <div className="mx-auto w-full max-w-3xl space-y-4 p-4" aria-hidden="true">
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

  // Current status from taskStatus or fallback to task.status (isActive comes
  // from the conversation hook, which also treats waiting_for_input as active).
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
  // Prefer the resolved policy's run budget; fall back to the creation param.
  const rawBudget =
    policy?.budget?.run_budget_usd ?? task.parameters?.budget_usd;
  const budgetLimit =
    rawBudget != null && !Number.isNaN(Number(rawBudget))
      ? Number(rawBudget)
      : null;

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
                  onResolveEscalation={actions.resolveEscalation}
                  onSubmitInput={actions.submitInput}
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

          {/* Chat input — matches the workplace composer (borderless textarea
              inside a soft rounded card) so both surfaces look identical. */}
          <div className="border-t bg-background px-3 py-3">
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

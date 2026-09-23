"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Play } from "lucide-react";
import { toast } from "sonner";
import ActivityGroup from "@/components/Chat/ActivityGroup";
import {
  buildActivitySegments,
  lastVisibleAssistantContent,
  shouldRenderConversationFallback,
} from "@/components/Chat/activityView";
import { ChatInputArea } from "@/components/Chat/componets/ChatInputArea";
import { UserMessage as UserMessageComponent } from "@/components/Chat/componets/UserMessage";
import { useA2UIActions } from "@/components/Chat/hooks/useA2UIActions";
import { useFileUpload } from "@/components/Chat/hooks/useFileUpload";
import { useScrollManagement } from "@/components/Chat/hooks/useScrollManagement";
import type {
  A2UIActionHandler,
  HumanInputSecretValue,
} from "@/components/Chat/types";
import { deliverTaskMessage } from "@/components/Chat/utils/deliverTaskMessage";
import EmptyState from "@/components/EmptyState";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { buildActivitySummary } from "@/components/TaskInfoPanel/buildActivitySummary";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { useTaskActions } from "@/hooks/useTaskActions";
import type { TaskWithAgent } from "@/lib/api";
import type { Part } from "@/lib/events/contract";
import { PartRenderer } from "@/lib/events/parts/PartRenderer";
import { useTaskEvents } from "@/lib/events/useTaskEvents";
import { getTaskStatusPresentation } from "@/lib/status";

const QUEUEABLE_STATUSES = ["running", "paused", "blocked", "completed"];

export type TaskConversationTask = Pick<TaskWithAgent, "id" | "agent_id"> &
  Partial<
    Pick<TaskWithAgent, "description" | "agent_name" | "status" | "created_at">
  >;

export interface TaskConversationActivity {
  parts: Part[];
  streamStatus: string;
  executionStatus: "running" | "waiting" | "finished";
  activitySummary: ReturnType<typeof buildActivitySummary>;
  terminalMessage: string | null;
  eventsLoading: boolean;
  eventsError: string | null;
}

interface TaskConversationProps {
  task: TaskConversationTask;
  currentStatus?: string | null;
  fallback?: React.ReactNode;
  onActivityChange?: (activity: TaskConversationActivity) => void;
  onRefresh?: () => Promise<void> | void;
  onA2UIAction?: A2UIActionHandler;
}

export function TaskConversation({
  task,
  currentStatus,
  fallback,
  onActivityChange,
  onRefresh,
  onA2UIAction,
}: TaskConversationProps) {
  const router = useRouter();
  const [chatInput, setChatInput] = useState("");
  const [sendingMessage, setSendingMessage] = useState(false);
  const [continuationIterations, setContinuationIterations] = useState("10");
  const [continuationBudget, setContinuationBudget] = useState("");
  const [continuing, setContinuing] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const {
    selectedFiles,
    fileInputRef,
    handleFileSelect,
    removeFile,
    openFileDialog,
    clearFiles,
  } = useFileUpload();

  const {
    parts,
    timeline,
    executionStatus,
    isInteractionClosed,
    status: streamStatus,
    pendingForm,
    terminalMessage,
    completedRuns,
    loading: eventsLoading,
    error: eventsError,
    refresh: refreshEvents,
  } = useTaskEvents(task.agent_id, task.id, {
    includeHistory: true,
    autoConnect: true,
  });
  const actions = useTaskActions(task.agent_id, task.id);
  const { dispatchAction } = useA2UIActions(task.agent_id, task.id);
  const dispatchA2UIAction = onA2UIAction ?? dispatchAction;
  const activitySummary = useMemo(
    () => buildActivitySummary(parts, parts.length),
    [parts]
  );
  const activitySegments = useMemo(
    () => buildActivitySegments(parts, completedRuns),
    [completedRuns, parts]
  );
  const historyReady = !eventsLoading && !eventsError;
  const status =
    historyReady && (parts.length > 0 || timeline.length > 0)
      ? streamStatus
      : currentStatus || task.status || "";
  const isActive =
    QUEUEABLE_STATUSES.includes(status) || status === "waiting_for_input";
  const lastAssistantText = lastVisibleAssistantContent(activitySegments);
  const terminalTone = getTaskStatusPresentation(streamStatus).tone;
  const showTerminalMessage =
    streamStatus !== "completed" &&
    !!terminalMessage &&
    terminalMessage.trim() !== (lastAssistantText ?? "");
  const { messagesContainerRef, messagesEndRef, handleScroll } =
    useScrollManagement({
      messagesCount: parts.length + (terminalMessage ? 1 : 0),
    });

  useEffect(() => {
    onActivityChange?.({
      parts,
      streamStatus: status,
      executionStatus,
      activitySummary,
      terminalMessage,
      eventsLoading,
      eventsError,
    });
  }, [
    activitySummary,
    eventsError,
    eventsLoading,
    executionStatus,
    onActivityChange,
    parts,
    status,
    terminalMessage,
  ]);

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

  const handleSendMessage = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!historyReady) return;
    const message = chatInput.trim();
    if ((!message && selectedFiles.length === 0) || sendingMessage) return;

    setSendingMessage(true);
    try {
      const delivery = await deliverTaskMessage({
        actions,
        files: selectedFiles,
        message,
        pendingInputId:
          pendingForm?.eventType === "input.request"
            ? pendingForm.partId
            : undefined,
        queueOnCurrentTask:
          executionStatus !== "finished" && QUEUEABLE_STATUSES.includes(status),
      });
      if (delivery.route === "followup" && !delivery.taskId) {
        toast.error("Failed to create new task");
        return;
      }
      if (delivery.route === "input" && delivery.error) {
        toast.error("Failed to submit response");
        return;
      }
      if (delivery.route === "queue" && delivery.error) {
        toast.error("Failed to send message");
        return;
      }

      setChatInput("");
      clearFiles();
      if (delivery.route === "followup" && delivery.taskId) {
        router.push(`/tasks/${delivery.taskId}`);
      }
    } catch (error) {
      toast.error("Failed to send message", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSendingMessage(false);
    }
  };

  const handleContinueTask = async () => {
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
      const { continueAgentTaskAction } = await import("@/lib/server-actions");
      const { error } = await continueAgentTaskAction(
        task.id,
        iterations,
        budget || undefined
      );
      if (error) {
        toast.error("Couldn't continue task", {
          description:
            "The task is no longer waiting, or the grant does not lift its limit.",
        });
        return;
      }
      toast.success("Task continued");
      await onRefresh?.();
    } catch {
      toast.error("Couldn't continue task", {
        description: "An unexpected error occurred.",
      });
    } finally {
      setContinuing(false);
    }
  };

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <div
        ref={messagesContainerRef}
        onScroll={handleScroll}
        className="relative min-h-0 flex-1 overflow-auto"
      >
        <div className="pointer-events-none absolute inset-0 bg-[url('/lines.png')] bg-[size:450px_450px] bg-center bg-repeat opacity-[0.025] dark:bg-[url('/lines-dark.png')]" />
        <div className="relative z-10 mx-auto w-full max-w-3xl space-y-4 px-4 py-6 md:px-6">
          {task.description && (
            <UserMessageComponent
              id={`task-${task.id}-desc`}
              content={task.description}
              timestamp={task.created_at || ""}
            />
          )}
          {eventsError && !parts.length ? (
            <div className="py-6">
              <EmptyState
                title="Error Loading Conversation"
                description={eventsError}
                iconsType="tasks"
                additionAction={{ label: "Try Again", onClick: refreshEvents }}
              />
            </div>
          ) : eventsLoading && !parts.length ? (
            <div
              className="space-y-4 py-2"
              aria-label="Loading conversation history"
              role="status"
            >
              {Array.from({ length: 5 }).map((_, index) => (
                <div
                  key={index}
                  className={`flex ${index % 2 ? "justify-end" : "justify-start"}`}
                >
                  <Skeleton
                    className={`h-16 rounded-lg ${index % 2 ? "w-1/2" : "w-2/3"}`}
                  />
                </div>
              ))}
            </div>
          ) : eventsLoading ? (
            <div className="flex items-center justify-center py-8">
              <LoadingSpinner />
            </div>
          ) : null}
          {eventsError && parts.length > 0 && (
            <div
              role="alert"
              className="flex items-center justify-between gap-3 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-xs text-destructive"
            >
              <span>{eventsError}</span>
              <Button size="xs" variant="ghost" onClick={refreshEvents}>
                Try again
              </Button>
            </div>
          )}
          {activitySegments.map((segment) =>
            segment.kind === "work" ? (
              <ActivityGroup
                key={segment.run.id}
                run={segment.run}
                onFormSubmit={handleFormSubmit}
                isInteractionClosed={isInteractionClosed}
                onA2UIAction={dispatchA2UIAction}
              />
            ) : (
              <PartRenderer
                key={segment.part.partId}
                part={segment.part}
                interactionClosed={isInteractionClosed(segment.part)}
                onFormSubmit={handleFormSubmit}
                onA2UIAction={dispatchA2UIAction}
              />
            )
          )}
          {showTerminalMessage && (
            <StatusIndicator tone={terminalTone}>
              {terminalMessage}
            </StatusIndicator>
          )}
          {!eventsLoading &&
            parts.length === 0 &&
            !terminalMessage &&
            !fallback && (
              <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
                No execution events yet.
              </div>
            )}
          {!eventsError &&
            shouldRenderConversationFallback(eventsLoading, activitySegments) &&
            fallback}
          <div ref={messagesEndRef} />
        </div>
      </div>

      <div className="shrink-0 bg-background">
        <div className="mx-auto w-full max-w-3xl px-4 py-3 md:px-6">
          {status === "waiting_for_continuation" ? (
            <div className="space-y-3 rounded-2xl border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/30">
              <div>
                <p className="text-sm font-medium text-amber-950 dark:text-amber-100">
                  The task reached its iteration or budget limit.
                </p>
                <p className="text-xs text-amber-800 dark:text-amber-300">
                  Grant only the resources you want it to use. It will wait for
                  up to 24 hours.
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
            <div>
              <ChatInputArea
                input={chatInput}
                onInputChange={(event) => setChatInput(event.target.value)}
                onSubmit={handleSendMessage}
                isLoading={sendingMessage}
                isSubmitDisabled={!historyReady}
                placeholder={
                  isActive
                    ? `Message ${task.agent_name || "agent"}...`
                    : `Send a follow-up to ${task.agent_name || "agent"}...`
                }
                selectedFiles={selectedFiles}
                onRemoveFile={removeFile}
                onOpenFileDialog={openFileDialog}
                onFileSelect={handleFileSelect}
                attachmentNotice={`Files will be sent in a new task with ${task.agent_name || "agent"}.`}
                fileInputRef={fileInputRef}
                textareaRef={textareaRef}
                variant="centered"
                rows={1}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    if (historyReady) void handleSendMessage(event);
                  }
                }}
              />
              {!historyReady && (
                <p
                  role="status"
                  className="px-1 pt-1.5 text-[11px] leading-4 text-muted-foreground"
                >
                  {eventsError
                    ? "Conversation history is unavailable. Retry loading before sending."
                    : "Loading conversation history. You can start writing; sending will be available when it finishes."}
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default TaskConversation;

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import ActivityGroup from "@/components/Chat/ActivityGroup";
import {
  buildActivitySegments,
  lastVisibleAssistantContent,
  shouldRenderConversationFallback,
} from "@/components/Chat/activityView";
import { ChatInputArea } from "@/components/Chat/componets/ChatInputArea";
import { UserMessage as UserMessageComponent } from "@/components/Chat/componets/UserMessage";
import { ContinuationGrantForm } from "@/components/Chat/ContinuationGrantForm";
import { useA2UIActions } from "@/components/Chat/hooks/useA2UIActions";
import { useFileUpload } from "@/components/Chat/hooks/useFileUpload";
import { useScrollManagement } from "@/components/Chat/hooks/useScrollManagement";
import type {
  A2UIActionHandler,
  HumanInputSecretValue,
} from "@/components/Chat/types";
import { deliverTaskMessage } from "@/components/Chat/utils/deliverTaskMessage";
import EmptyState from "@/components/EmptyState";
import FormError from "@/components/FormError";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { buildActivitySummary } from "@/components/TaskInfoPanel/buildActivitySummary";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { useTaskActions } from "@/hooks/useTaskActions";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import type { TaskWithAgent } from "@/lib/api";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { latestContinuationReason } from "@/lib/continuation";
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
  const router = useWorkspaceRouter();
  const t = useTranslations("Chat.errors");
  const [chatInput, setChatInput] = useState("");
  const [sendingMessage, setSendingMessage] = useState(false);
  const [composerError, setComposerError] = useState<string | null>(null);
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
  const { dispatchAction, error: a2uiError } = useA2UIActions(
    task.agent_id,
    task.id
  );
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
  const terminalKind = getTaskStatusPresentation(streamStatus).kind;
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
      setComposerError(null);
      const result = await actions.submitInput(
        inputRequestId,
        answers,
        secrets
      );
      if (result.error) {
        setComposerError(apiErrorMessage(result, t("submitResponseFailed")));
      }
    },
    [actions, t]
  );

  const handleSendMessage = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!historyReady) return;
    const message = chatInput.trim();
    if ((!message && selectedFiles.length === 0) || sendingMessage) return;

    setSendingMessage(true);
    setComposerError(null);
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
        setComposerError(apiErrorMessage(delivery, t("createTaskFailed")));
        return;
      }
      if (delivery.route === "input" && delivery.error) {
        setComposerError(apiErrorMessage(delivery, t("submitResponseFailed")));
        return;
      }
      if (delivery.route === "queue" && delivery.error) {
        setComposerError(apiErrorMessage(delivery, t("sendFailed")));
        return;
      }

      setChatInput("");
      clearFiles();
      if (delivery.route === "followup" && delivery.taskId) {
        router.push(`/tasks/${delivery.taskId}`);
      }
    } catch (error) {
      console.error("Failed to send message", error);
      setComposerError(`${t("sendFailed")}: ${formatApiError(error)}`);
    } finally {
      setSendingMessage(false);
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
            <StatusIndicator kind={terminalKind}>
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
            <ContinuationGrantForm
              taskId={task.id}
              failureReason={latestContinuationReason(timeline)}
              onContinued={onRefresh}
            />
          ) : (
            <div>
              {(composerError || a2uiError) && (
                <div className="mb-2 space-y-2">
                  {composerError && <FormError>{composerError}</FormError>}
                  {a2uiError && <FormError>{a2uiError}</FormError>}
                </div>
              )}
              <ChatInputArea
                input={chatInput}
                onInputChange={(event) => {
                  setChatInput(event.target.value);
                  setComposerError(null);
                }}
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

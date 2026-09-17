"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Play } from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { ChatInputArea } from "@/components/Chat/componets/ChatInputArea";
import { UserMessage as UserMessageComponent } from "@/components/Chat/componets/UserMessage";
import type { HumanInputSecretValue } from "@/components/Chat/types";
import EmptyState from "@/components/EmptyState";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { buildActivitySummary } from "@/components/TaskInfoPanel/buildActivitySummary";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { useTaskActions } from "@/hooks/useTaskActions";
import type { Part } from "@/lib/events/contract";
import { PartRenderer } from "@/lib/events/parts/PartRenderer";
import { useTaskEvents } from "@/lib/events/useTaskEvents";

const QUEUEABLE_STATUSES = ["running", "paused", "blocked", "completed"];

export interface TaskConversationTask {
  id: string;
  agent_id: string;
  description?: string | null;
  agent_name?: string | null;
  status?: string | null;
  created_at?: string | null;
}

export interface TaskConversationActivity {
  parts: Part[];
  streamStatus: string;
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
}

export function TaskConversation({
  task,
  currentStatus,
  fallback,
  onActivityChange,
  onRefresh,
}: TaskConversationProps) {
  const router = useRouter();
  const [chatInput, setChatInput] = useState("");
  const [sendingMessage, setSendingMessage] = useState(false);
  const [continuationIterations, setContinuationIterations] = useState("10");
  const [continuationBudget, setContinuationBudget] = useState("");
  const [continuing, setContinuing] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const {
    parts,
    status: streamStatus,
    pendingForm,
    terminalMessage,
    loading: eventsLoading,
    error: eventsError,
  } = useTaskEvents(task.agent_id, task.id, {
    includeHistory: true,
    autoConnect: true,
  });
  const actions = useTaskActions(task.agent_id, task.id);
  const activitySummary = useMemo(
    () => buildActivitySummary(parts, parts.length),
    [parts]
  );
  const status = currentStatus || task.status || "";
  const isActive =
    QUEUEABLE_STATUSES.includes(status) || status === "waiting_for_input";
  const isRunning = streamStatus === "running";
  const lastAssistantText = [...parts]
    .reverse()
    .find((part) => part.kind === "llm")?.data?.content;
  const hasAssistantAnswer = parts.some(
    (part) =>
      part.kind === "llm" &&
      typeof (part.data.content ?? part.data.chunk) === "string" &&
      String(part.data.content ?? part.data.chunk).trim().length > 0
  );
  const terminalTone =
    streamStatus === "failed"
      ? "danger"
      : streamStatus === "cancelled"
        ? "warning"
        : "success";
  const showTerminalMessage =
    !!terminalMessage &&
    terminalMessage.trim() !==
      (typeof lastAssistantText === "string" ? lastAssistantText.trim() : "");

  useEffect(() => {
    onActivityChange?.({
      parts,
      streamStatus,
      activitySummary,
      terminalMessage,
      eventsLoading,
      eventsError,
    });
  }, [
    activitySummary,
    eventsError,
    eventsLoading,
    onActivityChange,
    parts,
    streamStatus,
    terminalMessage,
  ]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [parts.length, terminalMessage]);

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
    const message = chatInput.trim();
    if (!message || sendingMessage) return;

    setSendingMessage(true);
    try {
      if (pendingForm && pendingForm.eventType === "input.request") {
        const { error } = await actions.submitInput(
          pendingForm.partId,
          { answer: message },
          {}
        );
        if (error) {
          toast.error("Failed to submit response");
          return;
        }
        setChatInput("");
        return;
      }

      if (QUEUEABLE_STATUSES.includes(status)) {
        const { error } = await actions.queueMessage(message);
        if (error) {
          toast.error("Failed to send message");
          return;
        }
        setChatInput("");
        return;
      }

      const newTaskId = await actions.createFollowupTask(message);
      if (!newTaskId) {
        toast.error("Failed to create new task");
        return;
      }
      setChatInput("");
      router.push(`/tasks/${newTaskId}`);
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

  if (eventsError && !parts.length) {
    return (
      <EmptyState
        title="Error Loading Conversation"
        description={eventsError}
        iconsType="tasks"
        additionAction={{ label: "Try Again", onClick: () => undefined }}
      />
    );
  }

  if (eventsLoading && !parts.length) {
    return (
      <div className="mx-auto w-full max-w-3xl space-y-4 p-4" aria-hidden="true">
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
    );
  }

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <div className="relative min-h-0 flex-1 overflow-auto">
        <div className="absolute inset-0 bg-[url('/lines.png')] bg-[size:450px_450px] bg-center bg-repeat opacity-20 dark:bg-[url('/lines-dark.png')]" />
        <div className="relative z-10 space-y-3 px-3 py-5">
          {task.description && (
            <UserMessageComponent
              id={`task-${task.id}-desc`}
              content={task.description}
              timestamp={task.created_at || ""}
            />
          )}
          {eventsLoading && (
            <div className="flex items-center justify-center py-8">
              <LoadingSpinner />
            </div>
          )}
          {parts.map((part) => (
            <PartRenderer
              key={part.partId}
              part={part}
              onFormSubmit={handleFormSubmit}
            />
          ))}
          {showTerminalMessage && (
            <StatusIndicator tone={terminalTone}>
              {terminalMessage}
            </StatusIndicator>
          )}
          {!eventsLoading && parts.length === 0 && !terminalMessage && !fallback && (
            <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
              No execution events yet.
            </div>
          )}
          {!eventsLoading && !hasAssistantAnswer && fallback}
          <div ref={messagesEndRef} />
        </div>
      </div>

      <div className="shrink-0 border-t bg-background px-3 py-3">
        {status === "waiting_for_continuation" ? (
          <div className="space-y-3 rounded-2xl border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/30">
            <div>
              <p className="text-sm font-medium text-amber-950 dark:text-amber-100">
                The task reached its iteration or budget limit.
              </p>
              <p className="text-xs text-amber-800 dark:text-amber-300">
                Grant only the resources you want it to use. It will wait for up to 24 hours.
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
                  onChange={(event) => setContinuationIterations(event.target.value)}
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
                  onChange={(event) => setContinuationBudget(event.target.value)}
                />
              </label>
              <Button onClick={handleContinueTask} disabled={continuing}>
                {continuing ? <Loader2 className="mr-2 animate-spin" /> : <Play className="mr-2" />}
                Continue task
              </Button>
            </div>
          </div>
        ) : (
          <div className="rounded-2xl border bg-white px-2 pb-2 pt-0 shadow-[0_8px_30px_rgb(0,0,0,0.04)] dark:border-zinc-800 dark:bg-zinc-900 dark:shadow-[0_8px_30px_rgb(0,0,0,0.2)]">
            <ChatInputArea
              input={chatInput}
              onInputChange={(event) => setChatInput(event.target.value)}
              onSubmit={handleSendMessage}
              isLoading={sendingMessage}
              placeholder={
                isActive
                  ? `Message ${task.agent_name || "agent"}...`
                  : `Send a follow-up to ${task.agent_name || "agent"}...`
              }
              selectedFiles={[]}
              onRemoveFile={() => undefined}
              onOpenFileDialog={() => undefined}
              fileInputRef={fileInputRef}
              textareaRef={textareaRef}
              variant="centered"
              rows={1}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void handleSendMessage(event);
                }
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}

export default TaskConversation;

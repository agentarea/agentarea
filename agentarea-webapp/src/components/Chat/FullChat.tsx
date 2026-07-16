"use client";

import type { PolicyDocument } from "@/api/client/types.gen";
import React from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { useMentions } from "@/hooks/useMentions";
import {
  pauseAgentTaskAction as pauseAgentTask,
  resumeAgentTaskAction as resumeAgentTask,
} from "@/lib/server-actions";
import { useTaskActions } from "@/hooks/useTaskActions";
import { cn } from "@/lib/utils";
import {
  extractPlainText,
  formatTextForTextarea,
  restoreMentionIds,
} from "@/utils/mentions";
import {
  applyEvent,
  initialState,
  type EventState,
} from "@/lib/events/reducer";
import { normalizeSSEEvent } from "@/lib/events/normalize";
import { canonicalType } from "@/lib/events/contract";
import { PartRenderer } from "@/lib/events/parts/PartRenderer";
import type { HumanInputSecretValue } from "@/components/Chat/types";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { BadgeSuggestions } from "./componets/BadgeSuggestions";
import type { BadgeSuggestion } from "./componets/BadgeSuggestions";
import { ChatInputArea } from "./componets/ChatInputArea";
import { ScrollToBottomButton } from "./componets/ScrollToBottomButton";
import { UserMessage as UserMessageComponent } from "./componets/UserMessage";
import { parseSSEStream } from "./handlers/sseParser";
import { useA2UIActions } from "./hooks/useA2UIActions";
import { useFileUpload } from "./hooks/useFileUpload";
// Import hooks
import { useScrollManagement } from "./hooks/useScrollManagement";
import { useTaskLifecycle } from "./hooks/useTaskLifecycle";

// A user message the person typed. Not a task event — interleaved by arrival.
interface UserChatMessage {
  id: string;
  content: string;
  role: "user";
  timestamp: string;
  files?: File[];
}

// Anchor a user message after the last part present when it was sent, so it
// keeps its slot as later agent parts supersede in place (stable partId).
interface UserEntry {
  message: UserChatMessage;
  afterPartId: string | null;
}

export interface Agent {
  id: string;
  name: string;
  description?: string | null;
  icon?: string | null;
  color_token?: string | null;
}

export interface ProjectOption {
  id: string;
  name: string;
  description?: string | null;
}

export interface TaskPolicyRule {
  id: string;
  target: string;
  effect: string;
  params: Record<string, unknown>;
}

export interface TaskPolicyOption {
  id: string;
  name: string;
  description?: string | null;
  policy?: TaskPolicyRule;
}

type TaskPolicyDocument = PolicyDocument;

function buildTaskPolicyDocument(
  rule: TaskPolicyRule | undefined
): TaskPolicyDocument | undefined {
  if (!rule) return undefined;

  const params = rule.params ?? {};
  const document: TaskPolicyDocument = {};

  if (rule.effect === "cap" && rule.target === "tokens") {
    document.tokens = {
      max_tokens: toNullableNumber(params.max_tokens),
      max_tokens_per_call: toNullableNumber(params.max_tokens_per_call),
    };
  }

  if (rule.effect === "cap" && rule.target === "spend") {
    const amount = toNullableMoney(params.amount_usd);
    document.budget =
      params.period === "run"
        ? { run_budget_usd: amount }
        : { monthly_spend_cap_usd: amount };
  }

  if (rule.effect === "cap" && rule.target === "service") {
    document.budget = {
      service_budget_usd: toNullableMoney(params.amount_usd),
    };
  }

  if (rule.target.startsWith("tool:")) {
    const toolName = rule.target.slice("tool:".length);
    if (rule.effect === "deny") {
      document.tools = { denied: [toolName] };
    }
    if (rule.effect === "allow") {
      document.tools = { allowed: [toolName] };
    }
    if (rule.effect === "approval") {
      document.approval = {
        requires_human_approval: true,
        approvers: toStringArray(params.approvers),
      };
    }
  }

  if (rule.effect === "approval" && rule.target === "*") {
    document.approval = {
      requires_human_approval: true,
      approvers: toStringArray(params.approvers),
    };
  }

  if (rule.effect === "safety" && rule.target === "content") {
    document.content_safety = {
      prompt_injection_detection_enabled: Boolean(params.prompt_injection),
      output_sanitizer_enabled: Boolean(params.output_sanitizer),
    };
  }

  return Object.keys(document).length > 0 ? document : undefined;
}

function toNullableNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function toNullableMoney(value: unknown): string | number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") return value;
  return null;
}

function toStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

interface FullChatProps {
  agent: Agent;
  availableAgents?: Agent[];
  onAgentChange?: (agent: Agent) => void;
  availableProjects?: ProjectOption[];
  availableTaskPolicies?: TaskPolicyOption[];
  startCentered?: boolean;
  taskId?: string;
  onTaskCreated?: (taskId: string) => void;
  onTaskStarted?: (taskId: string) => void;
  onTaskFinished?: (taskId: string) => void;
  className?: string;
  placeholder?: string;
  welcomeComponent?: React.ReactNode;
  badgeSuggestions?: BadgeSuggestion[];
}

export default function FullChat({
  agent,
  availableAgents,
  onAgentChange,
  startCentered = false,
  placeholder,
  welcomeComponent,
  taskId,
  onTaskCreated,
  onTaskStarted,
  onTaskFinished,
  className,
  badgeSuggestions,
  availableProjects = [],
  availableTaskPolicies = [],
}: FullChatProps) {
  const t = useTranslations("Chat");

  // Unified event core: SSE events fold through the reducer into ordered parts
  // (supersede-by-id). User messages the person typed aren't task events, so
  // they're tracked separately and interleaved by arrival order.
  const [eventState, setEventState] =
    React.useState<EventState>(initialState);
  const [userEntries, setUserEntries] = React.useState<UserEntry[]>([]);
  const eventStateRef = React.useRef<EventState>(eventState);
  eventStateRef.current = eventState;

  const parts = eventState.parts;
  const hasUserMessages = userEntries.length > 0;

  const pushEvent = React.useCallback(
    (eventType: string, data: Record<string, unknown>) => {
      const next = applyEvent(eventStateRef.current, { eventType, data });
      eventStateRef.current = next;
      setEventState(next);
    },
    []
  );

  const addUserMessage = React.useCallback((message: UserChatMessage) => {
    const order = eventStateRef.current.order;
    const afterPartId = order.length ? order[order.length - 1] : null;
    setUserEntries((prev) => [...prev, { message, afterPartId }]);
  }, []);

  // Ref so the agent-change effect can call the latest clearFiles without
  // listing an unstable function reference as a dep (useFileUpload doesn't
  // memoize it).
  const clearFilesRef = React.useRef<() => void>(() => {});

  // Clear conversation when agent changes
  React.useEffect(() => {
    eventStateRef.current = initialState();
    setEventState(eventStateRef.current);
    setUserEntries([]);
    setInput("");
    setInputDisplay("");
    clearFilesRef.current();
  }, [agent.id]);

  const { currentTaskId, setCurrentTaskId, callbacks } = useTaskLifecycle(
    agent.id,
    {
      initialTaskId: taskId,
      onTaskCreated,
      onTaskStarted,
      onTaskFinished,
    }
  );

  const { dispatchAction: dispatchA2UIAction } = useA2UIActions(
    agent.id,
    currentTaskId
  );

  const {
    messagesContainerRef,
    messagesEndRef,
    isAtBottom,
    handleScroll,
    scrollToBottom,
    checkIfAtBottom,
  } = useScrollManagement({
    messagesCount: parts.length + userEntries.length,
  });

  const {
    selectedFiles,
    fileInputRef,
    removeFile,
    openFileDialog,
    clearFiles,
  } = useFileUpload();
  clearFilesRef.current = clearFiles;

  // Single centralized action layer for this task (resolve escalation, submit
  // structured input incl. secrets → vault). Same layer every task surface uses.
  const actions = useTaskActions(agent.id, currentTaskId || taskId || null);

  // State for loading and input
  const [isLoading, setIsLoading] = React.useState(false);
  const [isPausing, setIsPausing] = React.useState(false);
  const [isResuming, setIsResuming] = React.useState(false);
  const [taskLifecycleStatus, setTaskLifecycleStatus] = React.useState<
    string | null
  >(null);
  const [input, setInput] = React.useState(""); // Stores @[agentId:agentName] format
  const [inputDisplay, setInputDisplay] = React.useState(""); // Stores @agentName for display
  const [selectedProjectId, setSelectedProjectId] = React.useState<
    string | null
  >(null);
  const [selectedTaskPolicyId, setSelectedTaskPolicyId] = React.useState<
    string | null
  >(null);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);
  const cardContainerRef = React.useRef<HTMLDivElement>(null);

  // Mention functionality
  const {
    showMentions,
    mentionPosition,
    filteredAgents,
    selectedMentionIndex,
    mentionMenuRef,
    agents: mentionAgents,
    handleInputChange: handleMentionInputChange,
    handleAgentSelect,
    handleKeyDown: handleMentionKeyDown,
  } = useMentions({
    textareaRef,
    containerRef: cardContainerRef,
    onMentionInsert: (newText, newCursorPosition) => {
      setInput(newText);
      const displayText = formatTextForTextarea(newText);
      setInputDisplay(displayText);

      setTimeout(() => {
        if (textareaRef.current) {
          const displayCursorPos = formatTextForTextarea(
            newText.substring(0, newCursorPosition)
          ).length;
          textareaRef.current.setSelectionRange(
            displayCursorPos,
            displayCursorPos
          );
          textareaRef.current.focus();
        }
      }, 0);
    },
  });

  // Badge click handler
  const handleBadgeClick = (text: string) => {
    setInput(text);
    setInputDisplay(text);

    setTimeout(() => {
      if (textareaRef.current) {
        textareaRef.current.focus();
        const length = text.length;
        textareaRef.current.setSelectionRange(length, length);

        if (text.endsWith("@")) {
          const syntheticEvent = {
            target: {
              value: text,
              selectionStart: length,
            },
          } as React.ChangeEvent<HTMLTextAreaElement>;
          handleMentionInputChange(syntheticEvent);
        }
      }
    }, 0);
  };

  // Handle input change
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const displayValue = e.target.value;
    setInputDisplay(displayValue);

    // Convert display value back to storage format
    const mentionsInInput = input.match(/@\[[^\]]+\]/g) || [];

    const replacementMap = new Map<string, string>();
    mentionsInInput.forEach((mentionWithId) => {
      const mentionDisplay = formatTextForTextarea(mentionWithId);
      if (!replacementMap.has(mentionDisplay)) {
        replacementMap.set(mentionDisplay, mentionWithId);
      }
    });

    let newInput = displayValue;
    const sortedReplacements = Array.from(replacementMap.entries()).sort(
      (a, b) => b[0].length - a[0].length
    );

    sortedReplacements.forEach(([display, storage]) => {
      const escaped = display.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      newInput = newInput.replace(new RegExp(escaped, "g"), storage);
    });

    setInput(newInput);
    handleMentionInputChange(e);
  };

  // Structured input / A2UI form submit routes through the shared action layer.
  const handleFormSubmit = React.useCallback(
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

  // SSE handler: adopt the task id on creation (lifecycle callbacks + URL
  // rewrite), track lifecycle status, then fold every event into the reducer.
  const currentTaskIdRef = React.useRef<string | null>(currentTaskId);
  currentTaskIdRef.current = currentTaskId;

  const handleSSEMessage = React.useCallback(
    (event: { type: string; data: Record<string, unknown> }) => {
      const rawType =
        (typeof event.data?.event_type === "string" && event.data.event_type) ||
        (typeof event.data?.original_event_type === "string" &&
          event.data.original_event_type) ||
        event.type;

      // Adopt the created task id once, before folding events.
      if (rawType === "task_created") {
        const newTaskId =
          typeof event.data?.task_id === "string" ? event.data.task_id : null;
        if (newTaskId && !currentTaskIdRef.current) {
          currentTaskIdRef.current = newTaskId;
          setCurrentTaskId(newTaskId);
          callbacks.onTaskCreated.current?.(newTaskId);
          callbacks.onTaskStarted.current?.(newTaskId);
        }
        return;
      }

      const canonical = canonicalType(rawType);
      if (canonical === "task.completed") {
        setTaskLifecycleStatus("completed");
        setIsLoading(false);
        const finishedId = currentTaskIdRef.current;
        if (finishedId) callbacks.onTaskFinished.current?.(finishedId);
      } else if (canonical === "task.failed") {
        const errorText = String(
          event.data?.error || event.data?.message || ""
        ).toLowerCase();
        const blocked =
          errorText.includes("insufficient balance") ||
          errorText.includes("no resource package") ||
          errorText.includes("quota exceeded");
        setTaskLifecycleStatus(blocked ? "blocked" : "failed");
        setIsLoading(false);
        const finishedId = currentTaskIdRef.current;
        if (finishedId) callbacks.onTaskFinished.current?.(finishedId);
      } else if (canonical === "task.cancelled") {
        setTaskLifecycleStatus("cancelled");
        setIsLoading(false);
      } else if (rawType === "execution_paused") {
        setTaskLifecycleStatus("paused");
      } else if (rawType === "execution_resumed") {
        setTaskLifecycleStatus("running");
      }

      const normalized = normalizeSSEEvent(event.type, event.data);
      if (normalized) pushEvent(normalized.eventType, normalized.data);
    },
    [callbacks, setCurrentTaskId, pushEvent]
  );

  // Send message handler
  const sendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if ((!input.trim() && selectedFiles.length === 0) || isLoading) return;

    const plainContent = extractPlainText(input);
    const finalContent = restoreMentionIds(input, mentionAgents);
    const selectedTaskPolicy = availableTaskPolicies.find(
      (policy) => policy.id === selectedTaskPolicyId
    );
    const taskPolicy = buildTaskPolicyDocument(selectedTaskPolicy?.policy);

    const userMessage: UserChatMessage = {
      id: Date.now().toString(),
      content: finalContent,
      role: "user",
      timestamp: new Date().toISOString(),
      files: selectedFiles.length > 0 ? selectedFiles : undefined,
    };

    addUserMessage(userMessage);
    setInput("");
    setInputDisplay("");
    clearFiles();
    setIsLoading(true);

    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }

    try {
      const response = await fetch(`/api/agents/${agent.id}/tasks/create`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify({
          description: plainContent,
          project_id: selectedProjectId,
          task_policy: taskPolicy,
          parameters: {
            context: {
              project_id: selectedProjectId,
              task_policy_rule_id: selectedTaskPolicy?.id,
              task_policy_rule_name: selectedTaskPolicy?.name,
            },
            task_type: "chat",
            session_id: `chat-${Date.now()}`,
          },
          enable_agent_communication: true,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      if (!response.body) {
        throw new Error("No response body");
      }

      const reader = response.body.getReader();

      await parseSSEStream(reader, {
        onEvent: handleSSEMessage,
        buffered: true,
      });
    } catch (error) {
      toast.error("Failed to send message", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setIsLoading(false);
    }
  };

  // Handle pause task
  const handlePause = async () => {
    if (!currentTaskId || isPausing) return;

    try {
      setIsPausing(true);
      const { error } = await pauseAgentTask(agent.id, currentTaskId);

      if (error) {
        const errorMessage =
          error.detail?.[0]?.msg || "An error occurred while pausing the task";
        toast.error("Failed to pause task", {
          description: errorMessage,
        });
      } else {
        toast.success("Task paused successfully");
        // We keep isLoading true until we get a confirmation or the stream ends?
        // If we pause, the stream might stop sending events.
        // Let's allow the user to interact again by stopping the loading state.
        setIsLoading(false);
      }
    } catch (_err) {
      toast.error("Failed to pause task", {
        description: "An unexpected error occurred",
      });
    } finally {
      setIsPausing(false);
    }
  };

  const handleResume = async () => {
    if (!currentTaskId || isResuming) return;

    try {
      setIsResuming(true);
      const { error } = await resumeAgentTask(agent.id, currentTaskId);

      if (error) {
        const errorMessage =
          error.detail?.[0]?.msg || "An error occurred while resuming the task";
        toast.error("Failed to resume task", {
          description: errorMessage,
        });
      } else {
        setTaskLifecycleStatus("running");
        setIsLoading(true);
        toast.success("Task resumed successfully");
      }
    } catch (_err) {
      toast.error("Failed to resume task", {
        description: "An unexpected error occurred",
      });
    } finally {
      setIsResuming(false);
    }
  };

  // Interleave user messages with agent parts. Each user message is anchored
  // after the part that was last present when it was sent (null = before all
  // parts), so it holds its slot while later parts supersede in place.
  const renderItems = React.useMemo(() => {
    const items: Array<
      | { kind: "user"; message: UserChatMessage }
      | { kind: "part"; partId: string }
    > = [];
    const usersByAnchor = new Map<string | null, UserChatMessage[]>();
    for (const entry of userEntries) {
      const list = usersByAnchor.get(entry.afterPartId) ?? [];
      list.push(entry.message);
      usersByAnchor.set(entry.afterPartId, list);
    }
    for (const message of usersByAnchor.get(null) ?? []) {
      items.push({ kind: "user", message });
    }
    for (const part of parts) {
      items.push({ kind: "part", partId: part.partId });
      for (const message of usersByAnchor.get(part.partId) ?? []) {
        items.push({ kind: "user", message });
      }
    }
    return items;
  }, [userEntries, parts]);

  const partsById = React.useMemo(() => {
    const map = new Map(parts.map((p) => [p.partId, p]));
    return map;
  }, [parts]);

  const terminalTone =
    eventState.status === "failed"
      ? "danger"
      : eventState.status === "cancelled"
        ? "warning"
        : "success";

  // Keydown handler
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (handleMentionKeyDown(e)) {
      return;
    }

    if (e.key === "Enter" && !e.shiftKey && !showMentions) {
      e.preventDefault();
      sendMessage(e);
    }
  };

  return (
    <div
      className={cn(
        "mx-auto flex h-full w-full flex-col gap-0 rounded-lg transition-all duration-700 ease-out",
        "justify-between",
        startCentered && !hasUserMessages
          ? "justify-center gap-8 overflow-y-auto overflow-x-hidden md:overflow-visible" // Allow vertical scroll on mobile/small screens if content overflows
          : "justify-between overflow-hidden",
        startCentered && !hasUserMessages
          ? "max-w-3xl mx-auto py-8 md:py-0"
          : "", // Add padding on mobile to ensure content isn't cut off at edges
        className
      )}
    >
      {/* Placeholder/Title/Welcome Component */}
      {!hasUserMessages && (welcomeComponent || placeholder) ? (
        <div
          className={cn(
            // Keep Workplace visuals intact when startCentered is true
            startCentered
              ? "flex items-center justify-center transition-all duration-500 flex-none w-full"
              : "flex flex-1 min-h-0 w-full items-center justify-center transition-all duration-500 pb-24"
          )}
        >
          {welcomeComponent ? (
            welcomeComponent
          ) : (
            <div className="relative flex flex-col items-center justify-center">
              <h1 className="relative z-10 text-primary/20 dark:text-accent-foreground/20">
                {placeholder}
              </h1>
            </div>
          )}
        </div>
      ) : null}

      {/* Messages Container */}
      <div
        className={`relative flex flex-col overflow-auto p-0 transition-all duration-700 ease-out ${
          hasUserMessages ? "h-full flex-1" : "h-0 flex-none"
        }`}
      >
        <div
          ref={messagesContainerRef}
          onScroll={handleScroll}
          className={`space-y-3 overflow-y-auto px-3 py-3 ${
            hasUserMessages ? "flex-1" : "min-h-0"
          }`}
        >
          {renderItems.map((item) => {
            if (item.kind === "user") {
              return (
                <UserMessageComponent
                  key={item.message.id}
                  id={item.message.id}
                  content={item.message.content}
                  timestamp={item.message.timestamp}
                  files={item.message.files}
                />
              );
            }
            const part = partsById.get(item.partId);
            if (!part) return null;
            return (
              <PartRenderer
                key={part.partId}
                part={part}
                onFormSubmit={handleFormSubmit}
                onA2UIAction={dispatchA2UIAction}
              />
            );
          })}
          {eventState.terminalMessage && (
            <StatusIndicator tone={terminalTone}>
              {eventState.terminalMessage}
            </StatusIndicator>
          )}
          <div ref={messagesEndRef} className="aa-messages-end" />
        </div>

        <ScrollToBottomButton
          visible={!isAtBottom}
          onScrollToBottom={() => {
            scrollToBottom();
            requestAnimationFrame(() => {
              checkIfAtBottom();
              // isAtBottom state is managed by scroll handler
            });
          }}
        />
      </div>

      {/* Input Area */}
      <div
        className={cn(
          "relative mx-auto w-full transition-all duration-700 ease-out group",
          startCentered && !hasUserMessages ? "max-w-3xl" : ""
        )}
      >
        {/* Subtle decorative elements for centered state */}
        {startCentered && !hasUserMessages && (
          <>
            <div className="absolute -left-12 top-1/2 -translate-y-1/2 w-24 h-24 bg-primary/5 rounded-full blur-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-1000" />
            <div className="absolute -right-12 top-1/2 -translate-y-1/2 w-24 h-24 bg-sky-500/5 rounded-full blur-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-1000" />
          </>
        )}

        <div
          ref={cardContainerRef}
          className={cn(
            "card relative w-full cursor-auto bg-white hover:shadow-none dark:bg-zinc-900",
            "px-2 pb-2 pt-0 border-t",
            startCentered && !hasUserMessages
              ? "border shadow-[0_8px_30px_rgb(0,0,0,0.04)] dark:shadow-[0_8px_30px_rgb(0,0,0,0.2)] rounded-2xl dark:border-zinc-800 hover:shadow-[0_20px_40px_rgb(0,0,0,0.06)]"
              : "rounded-t-lg",
            "transition-all duration-500 ease-out"
          )}
        >
          <ChatInputArea
            input={input}
            inputDisplay={inputDisplay}
            onInputChange={handleInputChange}
            onSubmit={sendMessage}
            isLoading={isLoading}
            placeholder={t("writeNewTaskFor", { agentName: agent.name })}
            selectedFiles={selectedFiles}
            onRemoveFile={removeFile}
            onOpenFileDialog={openFileDialog}
            fileInputRef={fileInputRef}
            textareaRef={textareaRef}
            onKeyDown={handleKeyDown}
            mentionProps={{
              show: showMentions,
              agents: filteredAgents,
              position: mentionPosition,
              selectedIndex: selectedMentionIndex,
              menuRef: mentionMenuRef,
              onAgentSelect: handleAgentSelect,
            }}
            containerRef={cardContainerRef}
            variant="centered"
            rows={3}
            currentAgent={agent}
            availableAgents={availableAgents}
            onAgentChange={onAgentChange}
            currentProjectId={selectedProjectId}
            availableProjects={availableProjects}
            onProjectChange={setSelectedProjectId}
            currentTaskPolicyId={selectedTaskPolicyId}
            availableTaskPolicies={availableTaskPolicies}
            onTaskPolicyChange={setSelectedTaskPolicyId}
            onStop={isLoading && currentTaskId ? handlePause : undefined}
            isStopping={isPausing}
            onResume={currentTaskId ? handleResume : undefined}
            isResuming={isResuming}
            canResume={
              taskLifecycleStatus === "paused" ||
              taskLifecycleStatus === "blocked"
            }
          />
        </div>
      </div>

      {/* Badge Suggestions */}
      {startCentered && (
        <div className="flex-none w-full pb-4">
          <BadgeSuggestions
            suggestions={badgeSuggestions || []}
            onBadgeClick={handleBadgeClick}
            visible={!hasUserMessages}
          />
        </div>
      )}
    </div>
  );
}

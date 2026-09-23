"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import type { PolicyDocument } from "@/api/client/types.gen";
import type { HumanInputSecretValue } from "@/components/Chat/types";
import type { TaskResourceRef } from "@/components/ResourcePicker/TaskResourceAttach";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { useMentions } from "@/hooks/useMentions";
import { useTaskActions } from "@/hooks/useTaskActions";
import { canonicalType, type Part } from "@/lib/events/contract";
import { normalizeSSEEvent } from "@/lib/events/normalize";
import { PartRenderer } from "@/lib/events/parts/PartRenderer";
import {
  applyEvent,
  initialState,
  isInteractionClosed,
  type CompletedRun,
  type EventState,
} from "@/lib/events/reducer";
import {
  pauseAgentTaskAction as pauseAgentTask,
  resumeAgentTaskAction as resumeAgentTask,
} from "@/lib/server-actions";
import { getTaskStatusPresentation } from "@/lib/status";
import { cn } from "@/lib/utils";
import {
  extractPlainText,
  formatTextForTextarea,
  restoreMentionIds,
} from "@/utils/mentions";
import ActivityGroup from "./ActivityGroup";
import { buildActivitySegments } from "./activityView";
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
import { createTaskWithAttachments } from "./utils/createTaskWithAttachments";
import { deliverTaskMessage } from "./utils/deliverTaskMessage";
import {
  adoptCreatedTaskId,
  routeComposerMessage,
} from "./utils/routeComposerMessage";

/** What the runtime needs to look a resource up; the rest is presentation. */
const toRunRef = ({ id, name }: TaskResourceRef) => ({
  id,
  ...(name ? { name } : {}),
});

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
  completedRunCount: number;
}

export interface Agent {
  id: string;
  name: string;
  description?: string | null;
  icon?: string | null;
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
  badgeSuggestions?: BadgeSuggestion[] | Promise<BadgeSuggestion[]>;
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
  const [eventState, setEventState] = React.useState<EventState>(initialState);
  const [userEntries, setUserEntries] = React.useState<UserEntry[]>([]);
  const eventStateRef = React.useRef<EventState>(eventState);
  eventStateRef.current = eventState;

  const parts = eventState.parts;
  const hasUserMessages = userEntries.length > 0;
  const visiblePartIds = React.useMemo(
    () => new Set(parts.map((part) => part.partId)),
    [parts]
  );

  const pushEvent = React.useCallback(
    (eventType: string, data: Record<string, unknown>) => {
      const next = applyEvent(eventStateRef.current, { eventType, data });
      eventStateRef.current = next;
      setEventState(next);
    },
    []
  );

  const addUserMessage = React.useCallback((message: UserChatMessage) => {
    const currentState = eventStateRef.current;
    const order = currentState.order;
    const afterPartId = order.length ? order[order.length - 1] : null;
    setUserEntries((prev) => [
      ...prev,
      {
        message,
        afterPartId,
        completedRunCount: currentState.completedRuns.length,
      },
    ]);
  }, []);

  // Ref so the agent-change effect can call the latest clearFiles without
  // listing an unstable function reference as a dep (useFileUpload doesn't
  // memoize it).
  const clearFilesRef = React.useRef<() => void>(() => {});
  const activeStreamRef =
    React.useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);

  // Clear conversation when agent changes
  React.useEffect(() => {
    eventStateRef.current = initialState();
    setEventState(eventStateRef.current);
    setUserEntries([]);
    setInput("");
    setInputDisplay("");
    clearFilesRef.current();
    return () => {
      const reader = activeStreamRef.current;
      activeStreamRef.current = null;
      void reader?.cancel();
    };
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
    handleFileSelect,
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
  const [taskMcps, setTaskMcps] = React.useState<TaskResourceRef[]>([]);
  const [taskSkills, setTaskSkills] = React.useState<TaskResourceRef[]>([]);
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

      // Each accepted task owns subsequent input and action submissions.
      if (rawType === "task_created") {
        const newTaskId = adoptCreatedTaskId(
          currentTaskIdRef.current,
          event.data
        );
        if (newTaskId) {
          currentTaskIdRef.current = newTaskId;
          setCurrentTaskId(newTaskId);
          pushEvent("task.started", { task_id: newTaskId });
          setTaskLifecycleStatus("running");
          callbacks.onTaskCreated.current?.(newTaskId);
          callbacks.onTaskStarted.current?.(newTaskId);
        }
        return;
      }

      const normalized = normalizeSSEEvent(event.type, event.data);
      if (normalized) pushEvent(normalized.eventType, normalized.data);
      const canonical = canonicalType(rawType);
      if (canonical === "task.completed") {
        setTaskLifecycleStatus("completed");
        setIsLoading(false);
        const finishedId = currentTaskIdRef.current;
        if (finishedId) callbacks.onTaskFinished.current?.(finishedId);
      } else if (canonical === "task.failed") {
        setTaskLifecycleStatus(eventStateRef.current.status);
        setIsLoading(false);
        const finishedId = currentTaskIdRef.current;
        if (finishedId) callbacks.onTaskFinished.current?.(finishedId);
      } else if (canonical === "task.cancelled") {
        setTaskLifecycleStatus("cancelled");
        setIsLoading(false);
      } else if (
        canonical === "input.request" ||
        canonical === "approval.request" ||
        canonical === "task.awaiting_follow_up"
      ) {
        setTaskLifecycleStatus(eventStateRef.current.status);
        setIsLoading(false);
      } else if (
        canonical === "input.response" ||
        canonical === "approval.response" ||
        canonical === "llm.call.started"
      ) {
        setTaskLifecycleStatus(eventStateRef.current.status);
        setIsLoading(eventStateRef.current.executionStatus === "running");
      } else if (canonical === "task.awaiting_continuation") {
        setTaskLifecycleStatus("waiting_for_continuation");
        setIsLoading(false);
      } else if (canonical === "task.continued") {
        setTaskLifecycleStatus("running");
        setIsLoading(true);
      } else if (rawType === "execution_paused") {
        setTaskLifecycleStatus("paused");
      } else if (rawType === "execution_resumed") {
        setTaskLifecycleStatus("running");
      }
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
    const filesToUpload = [...selectedFiles];

    const userMessage: UserChatMessage = {
      id: Date.now().toString(),
      content: finalContent,
      role: "user",
      timestamp: new Date().toISOString(),
      files: selectedFiles.length > 0 ? selectedFiles : undefined,
    };

    setIsLoading(true);

    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }

    let streamReader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    try {
      const route = routeComposerMessage(eventStateRef.current, {
        currentTaskId,
        hasFiles: filesToUpload.length > 0,
      });
      if (route.route === "current") {
        const delivery = await deliverTaskMessage({
          actions,
          files: [],
          message: plainContent,
          pendingInputId: route.pendingInputId,
          queueOnCurrentTask: true,
        });
        if ("error" in delivery && delivery.error)
          throw new Error("The task did not accept the message.");
        addUserMessage(userMessage);
        setInput("");
        setInputDisplay("");
        return;
      }
      const response = await createTaskWithAttachments({
        files: filesToUpload,
        request: (attachments) => {
          const taskData = {
            description:
              plainContent || "Use the attached files to complete the task.",
            project_id: selectedProjectId,
            task_policy: taskPolicy,
            parameters: {
              context: {
                project_id: selectedProjectId,
                task_policy_rule_id: selectedTaskPolicy?.id,
                task_policy_rule_name: selectedTaskPolicy?.name,
              },
              task_type: "chat",
              interaction: { channel: "web" },
              session_id: `chat-${Date.now()}`,
              // Additive for this run only. The activity resolves these against
              // the agent's own tools and refuses the run if one has gone away,
              // so a stale pick fails loudly instead of silently running short.
              // Only id and name travel: the logo is for the chip, not the run.
              ...(taskMcps.length > 0 ? { mcps: taskMcps.map(toRunRef) } : {}),
              ...(taskSkills.length > 0
                ? { skills: taskSkills.map(toRunRef) }
                : {}),
            },
            enable_agent_communication: true,
            ...(attachments.length > 0 ? { attachments } : {}),
          };

          return fetch(`/api/agents/${agent.id}/tasks/create`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Accept: "text/event-stream",
            },
            body: JSON.stringify(taskData),
          });
        },
        onAccepted: () => {
          addUserMessage(userMessage);
          setInput("");
          setInputDisplay("");
          clearFiles();
        },
      });

      streamReader = response.body.getReader();
      const previousReader = activeStreamRef.current;
      activeStreamRef.current = streamReader;
      void previousReader?.cancel();

      await parseSSEStream(streamReader, {
        onEvent: (event) => {
          if (activeStreamRef.current === streamReader) handleSSEMessage(event);
        },
        buffered: true,
      });
    } catch (error) {
      if (!streamReader || activeStreamRef.current === streamReader) {
        setIsLoading(false);
        toast.error("Failed to send message", {
          description: error instanceof Error ? error.message : String(error),
        });
      }
    } finally {
      if (!streamReader || activeStreamRef.current === streamReader) {
        if (streamReader) activeStreamRef.current = null;
        setIsLoading(false);
      }
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
      | {
          kind: "parts";
          parts: Part[];
          key: string;
          completedRuns?: CompletedRun[];
        }
    > = [];
    const terminalOnlyRuns = eventState.completedRuns.filter(
      (run) =>
        Boolean(run.terminalAnswer?.trim()) &&
        !run.partIds.some((partId) => visiblePartIds.has(partId))
    );
    const terminalRunsByUserId = new Map<string, CompletedRun[]>();
    const unanchoredTerminalRuns: CompletedRun[] = [];
    for (const [runIndex, run] of terminalOnlyRuns.map(
      (run) => [eventState.completedRuns.indexOf(run), run] as const
    )) {
      const entry = userEntries.find(
        (candidate) => candidate.completedRunCount === runIndex
      );
      if (!entry) {
        unanchoredTerminalRuns.push(run);
        continue;
      }
      const existing = terminalRunsByUserId.get(entry.message.id) ?? [];
      existing.push(run);
      terminalRunsByUserId.set(entry.message.id, existing);
    }
    const pushUser = (message: UserChatMessage) => {
      items.push({ kind: "user", message });
      const terminalRuns = terminalRunsByUserId.get(message.id);
      if (terminalRuns?.length) {
        items.push({
          kind: "parts",
          parts: [],
          key: `terminal-${terminalRuns[0].id}`,
          completedRuns: terminalRuns,
        });
      }
    };
    const usersByAnchor = new Map<string | null, UserChatMessage[]>();
    for (const entry of userEntries) {
      const list = usersByAnchor.get(entry.afterPartId) ?? [];
      list.push(entry.message);
      usersByAnchor.set(entry.afterPartId, list);
    }
    for (const message of usersByAnchor.get(null) ?? []) pushUser(message);
    let pending: Part[] = [];
    const flush = () => {
      if (pending.length)
        items.push({ kind: "parts", parts: pending, key: pending[0].partId });
      pending = [];
    };
    for (const part of parts) {
      pending.push(part);
      const messages = usersByAnchor.get(part.partId);
      if (messages?.length) {
        flush();
        for (const message of messages) pushUser(message);
      }
    }
    flush();
    const emittedUserIds = new Set(
      items
        .filter(
          (item): item is { kind: "user"; message: UserChatMessage } =>
            item.kind === "user"
        )
        .map((item) => item.message.id)
    );
    for (const entry of userEntries) {
      if (!emittedUserIds.has(entry.message.id)) pushUser(entry.message);
    }
    if (unanchoredTerminalRuns.length) {
      items.push({
        kind: "parts",
        parts: [],
        key: `terminal-${unanchoredTerminalRuns[0].id}`,
        completedRuns: unanchoredTerminalRuns,
      });
    }
    return items;
  }, [eventState.completedRuns, userEntries, parts, visiblePartIds]);

  const terminalTone = getTaskStatusPresentation(eventState.status).tone;

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
          className={`mx-auto w-full max-w-3xl space-y-4 overflow-y-auto px-4 py-4 md:px-6 ${
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
            const ids = new Set(item.parts.map((part) => part.partId));
            const runs =
              item.completedRuns ??
              eventState.completedRuns.map((run) => ({
                ...run,
                // Keep each final answer after its run and its user-message anchor.
                terminalAnswer: (() => {
                  const lastVisiblePartId = [...run.partIds]
                    .reverse()
                    .find((partId) => visiblePartIds.has(partId));
                  return lastVisiblePartId && ids.has(lastVisiblePartId)
                    ? run.terminalAnswer
                    : null;
                })(),
              }));
            return (
              <React.Fragment key={item.key}>
                {buildActivitySegments(item.parts, runs).map((segment) =>
                  segment.kind === "work" ? (
                    <ActivityGroup
                      key={segment.run.id}
                      run={segment.run}
                      onFormSubmit={handleFormSubmit}
                      isInteractionClosed={(part) =>
                        isInteractionClosed(eventState, part)
                      }
                      onA2UIAction={dispatchA2UIAction}
                    />
                  ) : (
                    <PartRenderer
                      key={segment.part.partId}
                      part={segment.part}
                      interactionClosed={isInteractionClosed(
                        eventState,
                        segment.part
                      )}
                      onFormSubmit={handleFormSubmit}
                      onA2UIAction={dispatchA2UIAction}
                    />
                  )
                )}
              </React.Fragment>
            );
          })}
          {eventState.terminalMessage && eventState.status !== "completed" && (
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
          "group relative mx-auto w-full max-w-3xl px-4 transition-all duration-700 ease-out md:px-6"
        )}
      >
        <div
          ref={cardContainerRef}
          className="relative w-full cursor-auto pb-3"
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
            onFileSelect={handleFileSelect}
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
            taskMcps={taskMcps}
            taskSkills={taskSkills}
            onTaskMcpsChange={setTaskMcps}
            onTaskSkillsChange={setTaskSkills}
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

      {/* Starter chips. Their own boundary: they may still be loading while
          the composer above is already usable. */}
      {startCentered && badgeSuggestions && (
        <div className="flex-none w-full pb-4">
          <React.Suspense fallback={null}>
            <BadgeSuggestions
              suggestions={badgeSuggestions}
              onBadgeClick={handleBadgeClick}
              visible={!hasUserMessages}
            />
          </React.Suspense>
        </div>
      )}
    </div>
  );
}

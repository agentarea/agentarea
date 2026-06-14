"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { useMentions } from "@/hooks/useMentions";
import {
  pauseAgentTaskAction as pauseAgentTask,
  resumeAgentTaskAction as resumeAgentTask,
  resolveEscalationAction as resolveEscalation,
} from "@/lib/server-actions";
import { cn } from "@/lib/utils";
import {
  extractPlainText,
  formatTextForTextarea,
  restoreMentionIds,
} from "@/utils/mentions";
import { BadgeSuggestions } from "./componets/BadgeSuggestions";
import type { BadgeSuggestion } from "./componets/BadgeSuggestions";
import { ChatInputArea } from "./componets/ChatInputArea";
import { ScrollToBottomButton } from "./componets/ScrollToBottomButton";
import { UserMessage as UserMessageComponent } from "./componets/UserMessage";
import { createSSEEventHandler } from "./handlers/eventHandlers";
import { parseSSEStream } from "./handlers/sseParser";
import {
  useChatMessages,
  type ChatMessage,
  type UserChatMessage,
} from "./hooks/useChatMessages";
import { useFileUpload } from "./hooks/useFileUpload";
// Import hooks
import { useScrollManagement } from "./hooks/useScrollManagement";
import { useTaskLifecycle } from "./hooks/useTaskLifecycle";
import { useA2UIActions } from "./hooks/useA2UIActions";
import { MessageRenderer } from "./MessageComponents";

export interface Agent {
  id: string;
  name: string;
  description?: string | null;
}

interface FullChatProps {
  agent: Agent;
  availableAgents?: Agent[];
  onAgentChange?: (agent: Agent) => void;
  startCentered?: boolean;
  taskId?: string;
  initialMessages?: ChatMessage[];
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
  initialMessages = [],
  onTaskCreated,
  onTaskStarted,
  onTaskFinished,
  className,
  badgeSuggestions,
}: FullChatProps) {
  const t = useTranslations("Chat");

  // Hooks for state management
  const { messages, setMessages, hasUserMessages, addUserMessage } =
    useChatMessages({
      agentName: agent.name,
      agentId: agent.id,
      initialMessages,
    });

  // Clear messages when agent changes
  React.useEffect(() => {
    setMessages([]);
    setInput("");
    setInputDisplay("");
    clearFiles();
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

  const { dispatchAction: dispatchA2UIAction } = useA2UIActions(agent.id, currentTaskId);

  const {
    messagesContainerRef,
    messagesEndRef,
    isAtBottom,
    handleScroll,
    scrollToBottom,
    checkIfAtBottom,
  } = useScrollManagement({
    messagesCount: messages.length,
  });

  const {
    selectedFiles,
    fileInputRef,
    removeFile,
    openFileDialog,
    clearFiles,
  } = useFileUpload();

  // Callback for resolving tool escalations (approve/deny)
  const handleResolveEscalation = React.useCallback(
    async (escalationId: string, approved: boolean, comment: string) => {
      const tid = currentTaskId || taskId;
      if (!tid) return;
      await resolveEscalation(agent.id, tid, escalationId, approved, comment);
    },
    [agent.id, currentTaskId, taskId]
  );

  // State for loading and input
  const [isLoading, setIsLoading] = React.useState(false);
  const [isPausing, setIsPausing] = React.useState(false);
  const [isResuming, setIsResuming] = React.useState(false);
  const [taskLifecycleStatus, setTaskLifecycleStatus] = React.useState<string | null>(null);
  const [input, setInput] = React.useState(""); // Stores @[agentId:agentName] format
  const [inputDisplay, setInputDisplay] = React.useState(""); // Stores @agentName for display
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

  // SSE message handler
  const handleSSEMessage = React.useCallback(
    createSSEEventHandler({
      currentTaskId,
      setMessages,
      setIsLoading,
      setTaskLifecycleStatus,
      setCurrentTaskId,
      onTaskCreated: callbacks.onTaskCreated.current,
      onTaskStarted: callbacks.onTaskStarted.current,
      onTaskFinished: callbacks.onTaskFinished.current,
    }),
    [currentTaskId, callbacks]
  );

  // Send message handler
  const sendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if ((!input.trim() && selectedFiles.length === 0) || isLoading) return;

    const plainContent = extractPlainText(input);
    const finalContent = restoreMentionIds(input, mentionAgents);

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

      if (!response.body) {
        throw new Error("No response body");
      }

      const reader = response.body.getReader();

      await parseSSEStream(reader, {
        onEvent: handleSSEMessage,
        buffered: true,
      });
    } catch (error) {
      const errorMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        content: `Sorry, I couldn't process your message. Error: ${error}`,
        role: "assistant",
        timestamp: new Date().toISOString(),
        agent_id: agent.id,
      };
      setMessages((prev) => [...prev, errorMessage]);
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
    } catch (err) {
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
    } catch (err) {
      toast.error("Failed to resume task", {
        description: "An unexpected error occurred",
      });
    } finally {
      setIsResuming(false);
    }
  };

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
          {messages.map((message, index) => {
            if ("type" in message) {
              return (
                <MessageRenderer
                  key={`${message.data.id}-${message.data.event_type}-${index}`}
                  message={message}
                  agent_name={agent.name}
                  onA2UIAction={dispatchA2UIAction}
                  onResolveEscalation={handleResolveEscalation}
                />
              );
            } else if (message.role === "user") {
              return (
                <UserMessageComponent
                  key={message.id}
                  id={message.id}
                  content={message.content}
                  timestamp={message.timestamp}
                  files={message.files}
                />
              );
            }
            return null;
          })}
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
            <div className="absolute -right-12 top-1/2 -translate-y-1/2 w-24 h-24 bg-indigo-500/5 rounded-full blur-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-1000" />
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
            onStop={isLoading && currentTaskId ? handlePause : undefined}
            isStopping={isPausing}
            onResume={currentTaskId ? handleResume : undefined}
            isResuming={isResuming}
            canResume={taskLifecycleStatus === "paused" || taskLifecycleStatus === "blocked"}
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

"use client";

import React, { useCallback } from "react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { useMentions } from "@/hooks/useMentions";
import { extractPlainText, formatTextForTextarea, restoreMentionIds } from "@/utils/mentions";
import { UserMessage as UserMessageComponent } from "./componets/UserMessage";
import { MessageRenderer } from "./MessageComponents";
import { BadgeSuggestions } from "./componets/BadgeSuggestions";
import { ScrollToBottomButton } from "./componets/ScrollToBottomButton";
import { ChatInputArea } from "./componets/ChatInputArea";
import { parseSSEStream } from "./handlers/sseParser";
import { createSSEEventHandler } from "./handlers/eventHandlers";

// Import hooks
import { useScrollManagement } from "./hooks/useScrollManagement";
import { useFileUpload } from "./hooks/useFileUpload";
import { useTaskLifecycle } from "./hooks/useTaskLifecycle";
import { useChatMessages, type ChatMessage, type UserChatMessage } from "./hooks/useChatMessages";

import type { BadgeSuggestion } from "./componets/BadgeSuggestions";

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
  height?: string;
  placeholder?: string;
  badgeSuggestions?: BadgeSuggestion[];
}

export default function FullChat({
  agent,
  availableAgents,
  onAgentChange,
  startCentered = false,
  placeholder,
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
  const { messages, setMessages, hasUserMessages, addUserMessage } = useChatMessages({
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

  const {
    currentTaskId,
    setCurrentTaskId,
    sseUrl,
    callbacks,
  } = useTaskLifecycle(agent.id, {
    initialTaskId: taskId,
    onTaskCreated,
    onTaskStarted,
    onTaskFinished,
  });

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
    handleFileSelect,
    removeFile,
    openFileDialog,
    clearFiles,
  } = useFileUpload();

  // State for loading and input
  const [isLoading, setIsLoading] = React.useState(false);
  const [input, setInput] = React.useState(""); // Stores @[agentId:agentName] format
  const [inputDisplay, setInputDisplay] = React.useState(""); // Stores @agentName for display
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);
  const cardContainerRef = React.useRef<HTMLDivElement>(null);

  // Mention functionality
  const {
    showMentions,
    mentionQuery,
    mentionPosition,
    filteredAgents,
    selectedMentionIndex,
    mentionMenuRef,
    agents: mentionAgents,
    handleInputChange: handleMentionInputChange,
    handleAgentSelect,
    handleKeyDown: handleMentionKeyDown,
    setShowMentions,
  } = useMentions({
    textareaRef,
    containerRef: cardContainerRef,
    onMentionInsert: (newText, newCursorPosition) => {
      setInput(newText);
      const displayText = formatTextForTextarea(newText);
      setInputDisplay(displayText);

      setTimeout(() => {
        if (textareaRef.current) {
          const displayCursorPos = formatTextForTextarea(newText.substring(0, newCursorPosition)).length;
          textareaRef.current.setSelectionRange(displayCursorPos, displayCursorPos);
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

        if (text.endsWith('@')) {
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
    const sortedReplacements = Array.from(replacementMap.entries())
      .sort((a, b) => b[0].length - a[0].length);

    sortedReplacements.forEach(([display, storage]) => {
      const escaped = display.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      newInput = newInput.replace(new RegExp(escaped, 'g'), storage);
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
        "mx-auto flex h-full w-full flex-col gap-0 overflow-hidden rounded-lg transition-all duration-700 ease-out",
        "justify-between",
        startCentered ? "justify-center" : "justify-between",
        (startCentered && !hasUserMessages) ? "max-w-3xl mx-auto" : "",
      )}
    >
      {/* Placeholder/Title */}
      {!hasUserMessages && placeholder ? (
        <div className="flex flex-1 items-center justify-center">
          <div className="relative flex flex-col items-center justify-center">
            <h1 className="relative z-10 text-primary/20 dark:text-accent-foreground/20">
              {placeholder}
            </h1>
          </div>
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
              const atBottom = checkIfAtBottom();
              // isAtBottom state is managed by scroll handler
            });
          }}
        />
      </div>

      {/* Input Area */}
      <div
        ref={cardContainerRef}
        className={cn(
          "card mx-auto w-full cursor-auto bg-white hover:shadow-none dark:bg-zinc-900",
          "px-2 pb-2 pt-0 border-t",
          "transition-[max-width] duration-700 ease-out",
          (startCentered && !hasUserMessages) ? "max-w-3xl" : "",
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
        />
      </div>

      {/* Badge Suggestions */}
      {startCentered && (
        <BadgeSuggestions
          suggestions={badgeSuggestions || []}
          onBadgeClick={handleBadgeClick}
          visible={!hasUserMessages}
        />
      )}
    </div>
  );
}

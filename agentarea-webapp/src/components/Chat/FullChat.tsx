"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Paperclip, ArrowUp } from "lucide-react";
import { AttachmentCard } from "@/components/ui/attachment-card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { useSSE } from "@/hooks/useSSE";
import { useMentions } from "@/hooks/useMentions";
import { cn } from "@/lib/utils";
import { extractPlainText, formatTextForTextarea, restoreMentionIds } from "@/utils/mentions";
import { UserMessage as UserMessageComponent } from "./componets/UserMessage";
import { parseEventToMessage, shouldDisplayEvent } from "./EventParser";
import { MessageComponentType, MessageRenderer } from "./MessageComponents";
import { MentionMenu } from "./MentionMenu";
import { BadgeSuggestions } from "./componets/BadgeSuggestions";
import { ScrollToBottomButton } from "./componets/ScrollToBottomButton";

interface UserChatMessage {
  id: string;
  content: string;
  role: "user";
  timestamp: string;
  files?: File[];
}

interface WelcomeMessage {
  id: string;
  content: string;
  role: "assistant";
  timestamp: string;
  agent_id: string;
}

type ChatMessage = UserChatMessage | WelcomeMessage | MessageComponentType;

import type { BadgeSuggestion } from "./componets/BadgeSuggestions";

interface FullChatProps {
  agent: {
    id: string;
    name: string;
    description?: string | null;
  };
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
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState(""); // Stores @[agentId:agentName] format
  const [inputDisplay, setInputDisplay] = useState(""); // Stores @agentName for display
  const [isLoading, setIsLoading] = useState(false);
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(
    taskId || null
  );
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [hasUserMessages, setHasUserMessages] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const cardContainerRef = useRef<HTMLDivElement>(null);

  // Mention functionality
  const {
    showMentions,
    mentionQuery,
    mentionPosition,
    filteredAgents,
    selectedMentionIndex,
    mentionMenuRef,
    agents: mentionAgents, // Get agents list for ID restoration
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


  const handleBadgeClick = (text: string) => {
    setInput(text);
    setInputDisplay(text);
    
    // Focus textarea and set cursor to end after setting text
    // Also trigger mention detection if text ends with @
    setTimeout(() => {
      if (textareaRef.current) {
        textareaRef.current.focus();
        const length = text.length;
        textareaRef.current.setSelectionRange(length, length);
        
        // Trigger mention detection if text ends with @
        if (text.endsWith('@')) {
          // Create a synthetic event to trigger mention detection
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
  const onTaskCreatedRef = useRef(onTaskCreated);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const initializedRef = useRef(false);
  const scrollTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const scrollRAFRef = useRef<number | null>(null);

  useEffect(() => {
    onTaskCreatedRef.current = onTaskCreated;
  }, [onTaskCreated]);

  // Cleanup timeouts and RAF on unmount
  useEffect(() => {
    return () => {
      if (scrollTimeoutRef.current) {
        clearTimeout(scrollTimeoutRef.current);
      }
      if (scrollRAFRef.current) {
        cancelAnimationFrame(scrollRAFRef.current);
      }
    };
  }, []);

  // SSE connection URL - only connect if we have a task
  const sseUrl = currentTaskId
    ? `/api/sse/agents/${agent.id}/tasks/${currentTaskId}/events/stream`
    : null;

  // Check if user is at bottom of scroll
  const checkIfAtBottom = useCallback(() => {
    if (!messagesContainerRef.current) return false;

    const container = messagesContainerRef.current;
    const threshold = 100; // Увеличиваем порог для более стабильной работы
    const scrollTop = container.scrollTop;
    const clientHeight = container.clientHeight;
    const scrollHeight = container.scrollHeight;
    const isAtBottom = scrollTop + clientHeight >= scrollHeight - threshold;

    return isAtBottom;
  }, []);

  // Check if there are any user messages (not just welcome messages)
  const checkForUserMessages = useCallback((messagesList: ChatMessage[]) => {
    return messagesList.some(
      (message) => "role" in message && message.role === "user"
    );
  }, []);

  // Handle scroll events with debounce
  const handleScroll = useCallback(() => {
    // Отменяем предыдущий таймаут если он есть
    if (scrollTimeoutRef.current) {
      clearTimeout(scrollTimeoutRef.current);
    }

    // Устанавливаем новый таймаут для debounce
    scrollTimeoutRef.current = setTimeout(() => {
      const atBottom = checkIfAtBottom();
      setIsAtBottom(atBottom);
    }, 100); // Увеличиваем задержку для более стабильной работы
  }, [checkIfAtBottom]);

  // Auto-scroll to bottom when messages change (only if user was at bottom)
  useEffect(() => {
    if (isAtBottom && messagesContainerRef.current) {
      // Отменяем предыдущий RAF если он есть
      if (scrollRAFRef.current) {
        cancelAnimationFrame(scrollRAFRef.current);
      }

      // Используем прямую прокрутку контейнера вместо scrollIntoView
      // чтобы не прокручивать всю страницу
      scrollRAFRef.current = requestAnimationFrame(() => {
        const container = messagesContainerRef.current;
        if (container) {
          container.scrollTop = container.scrollHeight;
        }

        // Проверяем позицию после скролла
        scrollRAFRef.current = requestAnimationFrame(() => {
          const atBottom = checkIfAtBottom();
          if (!atBottom && messagesContainerRef.current) {
            // Принудительно скроллим еще раз если не достигли низа
            messagesContainerRef.current.scrollTop = messagesContainerRef.current.scrollHeight;
          }
        });
      });
    }
  }, [messages, isAtBottom, checkIfAtBottom]);

  // Check scroll position when container size changes
  useEffect(() => {
    const container = messagesContainerRef.current;
    if (container) {
      // Используем RAF для проверки позиции после изменения размера
      const checkPosition = () => {
        const atBottom = checkIfAtBottom();
        setIsAtBottom(atBottom);
      };

      scrollRAFRef.current = requestAnimationFrame(checkPosition);
      return () => {
        if (scrollRAFRef.current) {
          cancelAnimationFrame(scrollRAFRef.current);
        }
      };
    }
  }, [messages.length, checkIfAtBottom]);

  // Initialize messages only once
  useEffect(() => {
    if (!initializedRef.current) {
      initializedRef.current = true;
      if (initialMessages.length > 0) {
        setMessages(initialMessages);
        setHasUserMessages(checkForUserMessages(initialMessages));
      } else {
        const welcomeMessages = [
          {
            id: "welcome",
            content: `Hello! I'm ${agent.name}. How can I help you today?`,
            role: "assistant" as const,
            timestamp: new Date().toISOString(),
            agent_id: agent.id,
          } as WelcomeMessage,
        ];
        setMessages(welcomeMessages);
        setHasUserMessages(checkForUserMessages(welcomeMessages));
      }
    }
  }, [checkForUserMessages]); // Add checkForUserMessages to dependencies

  // Handle SSE events
  // Normalize event types to UI-friendly canonical names and use them across FullChat event handling.
  const normalizeEventType = (type: string): string => {
    const key = (type || "").toLowerCase().replace(/[^a-z]/g, "");
    const map: Record<string, string> = {
      // workflow core
      workflowstarted: "WorkflowStarted",
      workflowcompleted: "WorkflowCompleted",
      workflowfailed: "WorkflowFailed",
      workflowcancelled: "WorkflowCancelled",
      started: "WorkflowStarted",
      completed: "WorkflowCompleted",
      failed: "WorkflowFailed",
      cancelled: "WorkflowCancelled",
      // llm
      llmcallstarted: "LLMCallStarted",
      llmcallcompleted: "LLMCallCompleted",
      llmcallfailed: "LLMCallFailed",
      llmcallchunk: "LLMCallChunk",
      // tool
      toolcallstarted: "ToolCallStarted",
      toolcallcompleted: "ToolCallCompleted",
      toolcallfailed: "ToolCallFailed",
      // task-level aliases
      taskcompleted: "WorkflowCompleted",
      taskfailed: "WorkflowFailed",
      taskcancelled: "WorkflowCancelled",
    };
    return map[key] || type.replace("workflow.", "");
  };
  const handleSSEMessage = useCallback(
    (event: { type: string; data: any }) => {
      // Get the actual event type from the data if available
      const actualEventType =
        event.data?.event_type || event.data?.original_event_type || event.type;

      // Handle generic "message" events that might be heartbeats or connection events
      if (actualEventType === "message" && !event.data?.event_type) {
        // This is likely a heartbeat or connection event - just return
        return;
      }

      // Normalize to canonical event type
      const cleanEventType = normalizeEventType(actualEventType);

      // Check if this event should create a visible message
      if (!shouldDisplayEvent(cleanEventType)) {
        return;
      }

      // Special handling for chunk events - accumulate instead of creating new messages
      if (cleanEventType === "LLMCallChunk") {
        const originalData = event.data.original_data || event.data;
        const chunk = originalData.chunk || event.data.chunk;
        const chunkIndex =
          originalData.chunk_index || event.data.chunk_index || 0;
        const isFinal = originalData.is_final || event.data.is_final || false;
        const taskId = originalData.task_id || event.data.task_id;

        setMessages((prev) => {
          const lastMessage = prev[prev.length - 1];

          // If the last message is a streaming message from the same task, append to it
          if (
            lastMessage &&
            "type" in lastMessage &&
            lastMessage.type === "llm_chunk" &&
            lastMessage.data.id === taskId
          ) {
            // Update the existing streaming message
            const updatedMessage = {
              ...lastMessage,
              data: {
                ...lastMessage.data,
                chunk: lastMessage.data.chunk + chunk,
                chunk_index: chunkIndex,
                is_final: isFinal,
              },
            };

            return [...prev.slice(0, -1), updatedMessage];
          } else {
            // Create new streaming message
            const messageComponent = parseEventToMessage(
              cleanEventType,
              event.data
            );
            if (messageComponent) {
              return [...prev, messageComponent];
            }
            return prev;
          }
        });

        // Convert to final message when streaming is complete
        if (isFinal) {
          setMessages((prev) => {
            const lastMessage = prev[prev.length - 1];
            if (
              lastMessage &&
              "type" in lastMessage &&
              lastMessage.type === "llm_chunk" &&
              lastMessage.data.id === taskId
            ) {
              // Convert to final llm_response message
              const finalMessage: MessageComponentType = {
                type: "llm_response",
                data: {
                  id: lastMessage.data.id,
                  timestamp: lastMessage.data.timestamp,
                  agent_id: lastMessage.data.agent_id,
                  event_type: "LLMCallCompleted",
                  content: lastMessage.data.chunk,
                  role: "assistant",
                },
              };

              return [...prev.slice(0, -1), finalMessage];
            }
            return prev;
          });
        }

        return;
      }

      // Special handling for tool call events - replace tool_call_started with tool_result
      if (cleanEventType === "ToolCallStarted") {
        const originalData = event.data.original_data || event.data;
        const toolName = originalData.tool_name || event.data.tool_name;
        const toolCallId = originalData.tool_call_id || event.data.tool_call_id;

        setMessages((prev) => {
          // Check if this tool call has already been started
          const alreadyStarted = prev.some(
            (msg) =>
              "type" in msg &&
              msg.type === "tool_call_started" &&
              (msg.data as any).tool_name === toolName &&
              (msg.data as any).tool_call_id === toolCallId
          );

          if (alreadyStarted) {
            return prev;
          }

          // Create new tool call started message
          const messageComponent = parseEventToMessage(
            cleanEventType,
            event.data
          );
          if (messageComponent) {
            return [...prev, messageComponent];
          }
          return prev;
        });

        return;
      }

      if (cleanEventType === "ToolCallCompleted") {
        const originalData = event.data.original_data || event.data;
        const toolName = originalData.tool_name || event.data.tool_name;
        const toolCallId = originalData.tool_call_id || event.data.tool_call_id;

        setMessages((prev) => {
          // Check if this tool call has already been completed
          const alreadyCompleted = prev.some(
            (msg) =>
              "type" in msg &&
              msg.type === "tool_result" &&
              (msg.data as any).tool_name === toolName &&
              (msg.data as any).tool_call_id === toolCallId
          );

          if (alreadyCompleted) {
            return prev;
          }

          // Find the last tool_call_started message for the same tool and call ID
          const lastToolCallIndex = prev.findLastIndex(
            (msg) =>
              "type" in msg &&
              msg.type === "tool_call_started" &&
              msg.data.tool_name === toolName &&
              msg.data.tool_call_id === toolCallId
          );

          if (lastToolCallIndex !== -1) {
            // Replace the tool_call_started message with tool_result
            const messageComponent = parseEventToMessage(
              cleanEventType,
              event.data
            );
            if (messageComponent) {
              const newMessages = [...prev];
              newMessages[lastToolCallIndex] = messageComponent;
              return newMessages;
            }
          } else {
            // If no matching tool_call_started found, just add the result
            const messageComponent = parseEventToMessage(
              cleanEventType,
              event.data
            );
            if (messageComponent) {
              return [...prev, messageComponent];
            }
          }
          return prev;
        });

        return;
      }

      // Clear any loading state FIRST - before message parsing
      if (
        cleanEventType === "WorkflowCompleted" ||
        cleanEventType === "WorkflowFailed" ||
        cleanEventType === "task_failed"
      ) {
        setIsLoading(false);

        // Call onTaskFinished when task completes (success or failure)
        // Use task_id from event data if currentTaskId is not available
        const taskId = currentTaskId || event.data?.task_id;
        if (onTaskFinished && taskId) {
          onTaskFinished(taskId);
        }
      }

      // Parse event into message component for all other event types
      const messageComponent = parseEventToMessage(cleanEventType, event.data);
      if (!messageComponent) {
        return;
      }

      // Add the new message component to the messages
      setMessages((prev) => [...prev, messageComponent]);

      // Handle special system events that don't create messages but affect UI state
      switch (cleanEventType) {
        case "connected":
          break;

        case "task_created":
          if (event.data.task_id && !currentTaskId) {
            setCurrentTaskId(event.data.task_id);
            onTaskCreatedRef.current?.(event.data.task_id);
            // Also call onTaskStarted with the real task ID
            onTaskStarted?.(event.data.task_id);
          }
          break;

        case "error":
          setIsLoading(false);
          break;

        default:
          // All other events are handled by the message parsing above
          break;
      }
    },
    [agent.id]
  );

  // SSE event handlers
  const handleSSEError = useCallback((error: Event) => {
    setIsLoading(false);
  }, []);

  const handleSSEOpen = useCallback(() => {
    // SSE connection opened
  }, []);

  const handleSSEClose = useCallback(() => {
    // SSE connection closed
  }, []);

  // File handling functions
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    setSelectedFiles((prev) => [...prev, ...files]);
  };

  const removeFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const openFileDialog = () => {
    fileInputRef.current?.click();
  };

  // Handle input change - combine mention detection with input update
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    handleMentionInputChange(e);
  };

  // Initialize SSE connection
  useSSE(sseUrl, {
    onMessage: handleSSEMessage,
    onError: handleSSEError,
    onOpen: handleSSEOpen,
    onClose: handleSSEClose,
  });

  const sendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if ((!input.trim() && selectedFiles.length === 0) || isLoading) return;

    // Keep the format with ID for display, but extract plain text for API
    const plainContent = extractPlainText(input);
    
    // Restore mention IDs for any mentions without ID format
    const finalContent = restoreMentionIds(input, mentionAgents);
    
    const userMessage: UserChatMessage = {
      id: Date.now().toString(),
      content: finalContent,
      role: "user",
      timestamp: new Date().toISOString(),
      files: selectedFiles.length > 0 ? selectedFiles : undefined,
    };

    // Add user message immediately
    setMessages((prev) => {
      const newMessages = [...prev, userMessage];
      setHasUserMessages(checkForUserMessages(newMessages));
      return newMessages;
    });
    setInput("");
    setInputDisplay("");
    setSelectedFiles([]);
    setIsLoading(true);

    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }

    try {
      // Create task with SSE streaming through Next.js API route (handles auth)
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
          user_id: "default_user",
          enable_agent_communication: true,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      if (!response.body) {
        throw new Error("No response body");
      }

      // Call onTaskStarted immediately after task creation
      if (onTaskStarted) {
        // We need to extract task ID from the response or create a temporary one
        // For now, we'll use a timestamp-based ID and update it when we get the real task ID
        const tempTaskId = `temp-${Date.now()}`;
        onTaskStarted(tempTaskId);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      // Buffered SSE parser: accumulates lines across chunks and parses events on blank line
      let textBuffer = "";
      let currentEventType: string | null = null;
      let currentDataLines: string[] = [];

      const processEvent = () => {
        if (currentDataLines.length === 0 && !currentEventType) {
          return;
        }
        const dataStr = currentDataLines.join("\n").trim();
        if (dataStr === "") {
          currentDataLines = [];
          currentEventType = null;
          return;
        }
        try {
          const parsed = JSON.parse(dataStr);
          const type = currentEventType || (parsed as any).type || "message";
          const data = (parsed as any).data ?? parsed;
          handleSSEMessage({ type, data });
        } catch (_err) {
          // Non-JSON payloads (e.g., heartbeats or [DONE])
          if (dataStr === "[DONE]" || dataStr.toLowerCase().includes("ping")) {
            // ignore heartbeats
          } else {
            handleSSEMessage({
              type: currentEventType || "message",
              data: { message: dataStr },
            });
          }
        }
        currentEventType = null;
        currentDataLines = [];
      };

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          textBuffer += decoder.decode(value, { stream: true });

          // Process complete lines; keep the last partial line in buffer
          const parts = textBuffer.split(/\r?\n/);
          textBuffer = parts.pop() || "";

          for (const rawLine of parts) {
            const line = rawLine; // already trimmed split
            if (line === "") {
              // blank line denotes end of event
              processEvent();
              continue;
            }
            if (line.startsWith(":")) {
              // comment/heartbeat
              continue;
            }
            if (line.startsWith("event:")) {
              currentEventType = line.slice(6).trimStart();
              continue;
            }
            if (line.startsWith("data:")) {
              // support both 'data: ' and 'data:'
              const data = line.slice(5).trimStart();
              currentDataLines.push(data);
              continue;
            }
            // Fallback: treat as data continuation
            currentDataLines.push(line);
          }
        }
        // Flush any pending event on stream end
        processEvent();
      } finally {
        reader.releaseLock();
      }
    } catch (error) {
      const errorMessage: WelcomeMessage = {
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

  return (
    <div
      className={cn(
        "mx-auto flex h-full w-full flex-col gap-0 overflow-hidden rounded-lg transition-all duration-700 ease-out",
        "transition-all duration-700 ease-out",
        "justify-between",
        startCentered ? "justify-center" : "justify-between",
        (startCentered && !hasUserMessages) ? "max-w-3xl mx-auto" : "",
        // hasUserMessages ? 'justify-between border bg-chatBackground' : 'justify-center')}>
        // className,
        // hasUserMessages
        //   ? "justify-between border border-b-0 bg-chatBackground"
        //   : "justify-between"
      )}
    >
      {!hasUserMessages && placeholder ? (
        <div className="flex flex-1 items-center justify-center">
          <div className="relative flex flex-col items-center justify-center">
            {/* <div className="absolute w-[120%] h-[300%] z-0 rounded-full bg-gradient-to-b from-primary/0 via-accent/5 to-accent-foreground/0"> </div> */}
            <h1 className="relative z-10 text-primary/20 dark:text-accent-foreground/20">
              {placeholder}
            </h1>
          </div>
        </div>
      ) : null}
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
            // Handle different message types
            if ("type" in message) {
              // This is a MessageComponentType - use MessageRenderer
              return (
                <MessageRenderer
                  key={`${message.data.id}-${message.data.event_type}-${index}`}
                  message={message}
                  agent_name={agent.name}
                />
              );
            } else if (message.role === "user") {
              // User message
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
          })}
          <div ref={messagesEndRef} className="aa-messages-end" />
        </div>

        <ScrollToBottomButton
          visible={!isAtBottom}
          onScrollToBottom={() => {
            if (messagesContainerRef.current) {
              messagesContainerRef.current.scrollTop = messagesContainerRef.current.scrollHeight;
            }
            requestAnimationFrame(() => {
              const atBottom = checkIfAtBottom();
              setIsAtBottom(atBottom);
            });
          }}
        />
      </div>
      <div
        ref={cardContainerRef}
        className={cn(
          "card mx-auto w-full cursor-auto bg-white hover:shadow-none dark:bg-zinc-900",
          "px-2 pb-2 pt-0 border-t",
          "transition-[max-width] duration-700 ease-out",
          (startCentered && !hasUserMessages) ? "max-w-3xl" : "",
        )}

      >
        <form
          onSubmit={sendMessage}
          className="relative flex flex-col gap-2 transition-all duration-700 ease-out"
        >
          <Textarea
            ref={textareaRef}
            value={inputDisplay || formatTextForTextarea(input)}
            onChange={(e) => {
              const displayValue = e.target.value;
              setInputDisplay(displayValue);
              
              // Convert display value back to storage format
              const mentionsInInput = input.match(/@\[[^\]]+\]/g) || [];
              
              // Build replacement map: display format -> storage format
              const replacementMap = new Map<string, string>();
              mentionsInInput.forEach((mentionWithId) => {
                const mentionDisplay = formatTextForTextarea(mentionWithId);
                if (!replacementMap.has(mentionDisplay)) {
                  replacementMap.set(mentionDisplay, mentionWithId);
                }
              });
              
              // Replace mentions in display value, going from longest to shortest
              let newInput = displayValue;
              const sortedReplacements = Array.from(replacementMap.entries())
                .sort((a, b) => b[0].length - a[0].length);
              
              sortedReplacements.forEach(([display, storage]) => {
                const escaped = display.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                newInput = newInput.replace(new RegExp(escaped, 'g'), storage);
              });
              
              setInput(newInput);
              handleMentionInputChange(e);
            }}
            placeholder={t("writeNewTaskFor", { agentName: agent.name })}
            disabled={isLoading}
            className="min-h-auto h-auto resize-none border-none pb-0 pr-12 pt-3 transition-all duration-700 ease-out"
            rows={3}
            onKeyDown={(e) => {
              // Handle mention menu navigation first
              if (handleMentionKeyDown(e)) {
                return;
              }
              
              // Handle message sending
              if (e.key === "Enter" && !e.shiftKey && !showMentions) {
                e.preventDefault();
                sendMessage(e);
              }
            }}
          />
          <div className="flex items-center justify-between gap-2">
            <div className="flex flex-row flex-wrap gap-2">
              {selectedFiles.length > 0 &&
                selectedFiles.map((file, index) => (
                  <AttachmentCard
                    key={index}
                    file={file}
                    onAction={() => removeFile(index)}
                    actionType="remove"
                  />
                ))}
            </div>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={openFileDialog}
                disabled={isLoading}
                className="h-8 w-8 rounded-full p-0 hover:bg-zinc-200 hover:text-text dark:hover:bg-gray-800"
              >
                <Paperclip className="h-4 w-4" />
              </Button>
              <Button
                type="submit"
                size="icon"
                disabled={
                  isLoading || (!input.trim() && selectedFiles.length === 0)
                }
                className="h-8 w-8 rounded-full shadow-sm transition-all duration-200 hover:shadow-md"
              >
                {isLoading ? (
                  <LoadingSpinner variant="light" size="sm" />
                ) : (
                  <ArrowUp className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>
        </form>
        {/* Mention menu */}
        <MentionMenu
          show={showMentions}
          agents={filteredAgents}
          position={mentionPosition}
          selectedIndex={selectedMentionIndex}
          menuRef={mentionMenuRef}
          onAgentSelect={handleAgentSelect}
        />
        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={handleFileSelect}
          className="hidden"
          accept="*/*"
        />
      </div>
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

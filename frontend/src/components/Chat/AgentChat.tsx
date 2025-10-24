"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Bot,
  ChevronDown,
  MessageCircle,
  Paperclip,
  Send,
  User,
  X,
} from "lucide-react";
import { AttachmentCard } from "@/components/ui/attachment-card";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { env } from "@/env";
import { useSSE } from "@/hooks/useSSE";
import { cn } from "@/lib/utils";
import { AssistantMessage as AssistantMessageComponent } from "./componets/AssistantMessage";
import { UserMessage as UserMessageComponent } from "./componets/UserMessage";
import { parseEventToMessage, shouldDisplayEvent } from "./EventParser";
import { MessageComponentType, MessageRenderer } from "./MessageComponents";

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

interface AgentChatProps {
  agent: {
    id: string;
    name: string;
    description?: string | null;
  };
  taskId?: string;
  initialMessages?: ChatMessage[];
  onTaskCreated?: (taskId: string) => void;
  className?: string;
  height?: string;
}

export default function AgentChat({
  agent,
  taskId,
  initialMessages = [],
  onTaskCreated,
  className = "",
  height = "600px",
}: AgentChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(
    taskId || null
  );
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const currentAssistantMessageRef = useRef<MessageComponentType | null>(null);
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
    if (isAtBottom) {
      // Отменяем предыдущий RAF если он есть
      if (scrollRAFRef.current) {
        cancelAnimationFrame(scrollRAFRef.current);
      }

      // Используем requestAnimationFrame для более плавного скролла
      scrollRAFRef.current = requestAnimationFrame(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });

        // Проверяем позицию после скролла
        scrollRAFRef.current = requestAnimationFrame(() => {
          const atBottom = checkIfAtBottom();
          if (!atBottom) {
            // Принудительно скроллим еще раз если не достигли низа
            messagesEndRef.current?.scrollIntoView({ behavior: "auto" });
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
      } else {
        setMessages([
          {
            id: "welcome",
            content: `Hello! I'm ${agent.name}. How can I help you today?`,
            role: "assistant" as const,
            timestamp: new Date().toISOString(),
            agent_id: agent.id,
          } as WelcomeMessage,
        ]);
      }
    }
  }, []); // Empty dependency array - only run once

  // Handle SSE events
  const handleSSEMessage = useCallback(
    (event: { type: string; data: any }) => {
      // Normalize event types to UI-friendly canonical names
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

      const actualEventType =
        event.data?.event_type || event.data?.original_event_type || event.type;

      if (actualEventType === "message" && !event.data?.event_type) {
        return;
      }

      // Normalize to canonical event type
      const cleanEventType = normalizeEventType(actualEventType);

      if (!shouldDisplayEvent(cleanEventType)) {
        return;
      }

      // Tool started: add placeholder message to be replaced later
      if (cleanEventType === "ToolCallStarted") {
        const placeholder = parseEventToMessage(cleanEventType, event.data);
        if (placeholder) {
          setMessages((prev) => [...prev, placeholder]);
        }
        return;
      }

      // Tool completed: replace the last matching ToolCallStarted message
      if (cleanEventType === "ToolCallCompleted") {
        const originalData = event.data.original_data || event.data;
        const toolName = originalData.tool_name || event.data.tool_name;
        const toolCallId = originalData.tool_call_id || event.data.tool_call_id;

        setMessages((prev) => {
          const lastToolCallIndex = [...prev]
            .reverse()
            .findIndex(
              (msg) =>
                "type" in msg &&
                msg.type === "tool_call_started" &&
                msg.data.tool_name === toolName &&
                msg.data.tool_call_id === toolCallId
            );

          if (lastToolCallIndex !== -1) {
            const indexFromStart = prev.length - 1 - lastToolCallIndex;
            const resultMessage = parseEventToMessage(
              cleanEventType,
              event.data
            );
            if (resultMessage) {
              const newMessages = [...prev];
              newMessages[indexFromStart] = resultMessage;
              return newMessages;
            }
          } else {
            const resultMessage = parseEventToMessage(
              cleanEventType,
              event.data
            );
            if (resultMessage) {
              return [...prev, resultMessage];
            }
          }
          return prev;
        });
        return;
      }

      // LLM chunk: accumulate streaming content
      if (cleanEventType === "LLMCallChunk") {
        const originalData = event.data.original_data || event.data;
        const chunk = originalData.chunk || event.data.chunk;
        const chunkIndex =
          originalData.chunk_index || event.data.chunk_index || 0;
        const isFinal = originalData.is_final || event.data.is_final || false;
        const taskId = originalData.task_id || event.data.task_id;

        setMessages((prev) => {
          const lastMessage = prev[prev.length - 1];
          if (
            lastMessage &&
            "type" in lastMessage &&
            lastMessage.type === "llm_chunk" &&
            lastMessage.data.id === taskId
          ) {
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
            const newMessage = parseEventToMessage(cleanEventType, event.data);
            if (newMessage) {
              return [...prev, newMessage];
            }
            return prev;
          }
        });

        if (isFinal) {
          setMessages((prev) => {
            const lastMessage = prev[prev.length - 1];
            if (
              lastMessage &&
              "type" in lastMessage &&
              lastMessage.type === "llm_chunk" &&
              lastMessage.data.id === taskId
            ) {
              const finalMessage = {
                type: "llm_response",
                data: {
                  id: lastMessage.data.id,
                  timestamp: lastMessage.data.timestamp,
                  agent_id: lastMessage.data.agent_id,
                  event_type: "LLMCallCompleted",
                  content: lastMessage.data.chunk,
                  role: "assistant",
                },
              } as MessageComponentType;
              return [...prev.slice(0, -1), finalMessage];
            }
            return prev;
          });
        }
        return;
      }

      // Workflow terminal events: stop loading
      if (
        cleanEventType === "WorkflowCompleted" ||
        cleanEventType === "WorkflowFailed" ||
        cleanEventType === "task_failed"
      ) {
        setIsLoading(false);
      }

      // Default: parse and append
      const messageComponent = parseEventToMessage(cleanEventType, event.data);
      if (messageComponent) {
        setMessages((prev) => [...prev, messageComponent]);
      }
    },
    [agent.id]
  );

  // SSE event handlers
  const handleSSEError = useCallback((error: Event) => {
    console.error("SSE connection error:", error);
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

  // Auto-resize textarea function
  const adjustTextareaHeight = () => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      const scrollHeight = textarea.scrollHeight;
      const maxHeight = 3 * 24; // 3 lines * 24px line height
      textarea.style.height = `${Math.min(scrollHeight, maxHeight)}px`;
    }
  };

  // Handle input change with auto-resize
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    adjustTextareaHeight();
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

    const userMessage: UserChatMessage = {
      id: Date.now().toString(),
      content: input,
      role: "user",
      timestamp: new Date().toISOString(),
      files: selectedFiles.length > 0 ? selectedFiles : undefined,
    };

    // Add user message immediately
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
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
          description: userMessage.content,
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

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const chunk = decoder.decode(value);
          const lines = chunk.split("\n");

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              try {
                const eventData = JSON.parse(line.slice(6));
                handleSSEMessage({
                  type: eventData.type || "message",
                  data: eventData.data || eventData,
                });
              } catch (parseError) {
                console.error("Failed to parse SSE event:", parseError);
              }
            }
          }
        }
      } finally {
        reader.releaseLock();
      }
    } catch (error) {
      console.error("Failed to send message:", error);
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
    <Card
      className={cn(
        "flex h-full max-h-full cursor-auto flex-col justify-between overflow-hidden p-0 shadow-none hover:shadow-none",
        className
      )}
    >
      <CardHeader className="border-b p-4">
        <CardTitle className="flex items-center gap-2">
          Chat with {agent.name}
        </CardTitle>
      </CardHeader>
      <CardContent className="relative flex flex-1 flex-col overflow-auto bg-chatBackground p-0">
        {/* Messages */}
        <div
          ref={messagesContainerRef}
          onScroll={handleScroll}
          className="flex-1 space-y-3 overflow-y-auto px-3 py-3"
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
            } else {
              // Assistant welcome message
              return (
                <AssistantMessageComponent
                  key={message.id}
                  id={message.id}
                  content={message.content}
                  timestamp={message.timestamp}
                  agent_id={message.agent_id}
                  agent_name={agent.name}
                />
              );
            }
          })}
          <div ref={messagesEndRef} className="aa-messages-end" />
        </div>

        {/* Scroll to bottom button */}
        <div
          className={`absolute bottom-4 right-4 z-20 transition-opacity duration-200 ${isAtBottom ? "pointer-events-none opacity-0" : "opacity-100"}`}
        >
          <Button
            onClick={() => {
              // Принудительно скроллим к низу
              messagesEndRef.current?.scrollIntoView({ behavior: "auto" });

              // Проверяем позицию после скролла
              requestAnimationFrame(() => {
                const atBottom = checkIfAtBottom();
                setIsAtBottom(atBottom);
              });
            }}
            size="sm"
            className="h-8 w-8 rounded-full bg-white text-text shadow-lg hover:text-white dark:bg-zinc-900 dark:text-zinc-200"
          >
            <ChevronDown className="h-4 w-4" />
          </Button>
        </div>
      </CardContent>
      <CardFooter className="p-0">
        {/* Input */}
        <div className="w-full border-t p-4">
          {/* Selected Files Display */}
          {selectedFiles.length > 0 && (
            <div className="mb-3 flex flex-row flex-wrap gap-2">
              {selectedFiles.map((file, index) => (
                <AttachmentCard
                  key={index}
                  file={file}
                  onAction={() => removeFile(index)}
                  actionType="remove"
                />
              ))}
            </div>
          )}

          <form onSubmit={sendMessage} className="flex gap-3">
            <div className="relative flex-1">
              <Textarea
                ref={textareaRef}
                value={input}
                onChange={handleInputChange}
                placeholder={`Message ${agent.name}...`}
                disabled={isLoading}
                className="max-h-[72px] min-h-[40px] resize-none rounded-3xl border py-2 pr-12 transition-colors duration-200 focus:border-primary/50"
                rows={1}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage(e);
                  }
                }}
              />
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={openFileDialog}
                disabled={isLoading}
                className="absolute right-2 top-1 h-8 w-8 rounded-full p-0 hover:bg-zinc-200 hover:text-text dark:hover:bg-gray-800"
              >
                <Paperclip className="h-4 w-4" />
              </Button>
            </div>
            <Button
              type="submit"
              size="icon"
              disabled={
                isLoading || (!input.trim() && selectedFiles.length === 0)
              }
              className="h-10 w-10 rounded-full shadow-sm transition-all duration-200 hover:shadow-md"
            >
              {isLoading ? (
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              ) : (
                <Send className="h-4 w-4" />
              )}
            </Button>
          </form>

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
      </CardFooter>
    </Card>
  );
}
